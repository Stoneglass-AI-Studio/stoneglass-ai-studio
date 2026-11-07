# SPDX-License-Identifier: GPL-3.0-or-later
"""Operator-driven native UI acceptance; never clicks Generate or supplies inference."""
import argparse
import contextlib
import importlib.metadata
import io
import json
import os
import sys
import time
import traceback
from dataclasses import asdict
from pathlib import Path
from typing import Any

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "scripts"))
import offline_acceptance as checks  # Reuse read-only dependency/resource checks and bootstrap.

from stoneglass.inference.contracts import ModelSpec, ProgressEvent
from stoneglass.inference.reviewed_profile import require_reviewed_profile
from stoneglass.services.images import validate_png

ARTIFACTS = PROJECT / ".test-artifacts/offline-ui-acceptance"


def fingerprint() -> dict[str, str]:
    result = checks.source_fingerprint()
    paths = [Path(__file__), PROJECT / "scripts/test-offline-ui.ps1",
             PROJECT / "src/stoneglass/ui/theme.qss",
             *sorted((PROJECT / "src/stoneglass/ui/assets").glob("*.jpg"))]
    result.update({str(p.relative_to(PROJECT)): checks.digest(p) for p in paths})
    return result


class UIJournal(checks.Journal):
    def report_event(self, event: ProgressEvent) -> None:
        with (self.directory / "progress.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"at": checks.utc_now(), "elapsed_seconds": time.monotonic() - self.started,
                "stage": event.stage.value, "percent": event.percent, "message": event.message}) + "\n")
        if event.message != self.last_message or time.monotonic() - self.last_console >= 10:
            # Only actual step messages claim sampling progress. Raw protocol
            # percentages remain in the journal, not displayed as load estimates.
            self.log(f"{event.stage.value}: {event.message}")
            self.last_message, self.last_console = event.message, time.monotonic()


def gui_environment() -> dict[str, Any]:
    missing = []
    versions = {}
    for name in ("PySide6-Essentials", "shiboken6"):
        package = importlib.metadata.distribution(name)
        versions[name] = package.version
        if package.version != "6.12.0":
            raise RuntimeError(f"This UI acceptance profile requires the reviewed {name} 6.12.0.")
        if not package.files:
            raise RuntimeError(f"The local {name} installed-file inventory is missing.")
        for entry in package.files:
            if not str(entry).endswith(".pyc") and not package.locate_file(entry).is_file():
                missing.append(str(entry))
    if missing:
        raise RuntimeError("Required local Qt files are missing. Nothing will be installed.")
    os.environ.update(PIP_NO_INDEX="1", PIP_DISABLE_PIP_VERSION_CHECK="1", PIP_CONFIG_FILE=os.devnull)
    from pip._internal.cli.main import main as pip_main
    output = io.StringIO()
    with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
        code = pip_main(["--disable-pip-version-check", "check"])
    if code:
        raise RuntimeError("The existing GUI environment failed pip check: " + output.getvalue()[:2000])
    return {"python_version": list(sys.version_info[:3]), "versions": versions,
            "pip_check_exit": code, "pip_check_output": output.getvalue().strip()}


def local_profile(manifest_path: Path, run: Path, journal: UIJournal) -> dict[str, Any]:
    local = checks.check_local(manifest_path, run, journal)
    manifest = checks.read_manifest(manifest_path)
    require_reviewed_profile(ModelSpec(manifest.checkpoint.stem, manifest.checkpoint, resource_manifest=manifest_path))
    local.update(ui_source_sha256=fingerprint(), gui_environment=gui_environment())
    return local


def require_receipt(manifest_path: Path) -> dict[str, Any]:
    path = ARTIFACTS / "prepared.json"
    if not path.exists():
        raise RuntimeError("UI preparation receipt missing. Run scripts/test-offline-ui.ps1 -PrepareOnly first.")
    receipt = json.loads(checks.strict_local(path).read_text(encoding="utf-8"))
    if receipt.get("schema") != 1 or receipt.get("kind") != "offline-ui" or receipt.get("status") != "prepared":
        raise RuntimeError("A valid UI preparation receipt is required; the older backend receipt cannot authorize this test.")
    local = receipt["local"]
    if fingerprint() != local["ui_source_sha256"] or checks.digest(manifest_path) != local["manifest_sha256"]:
        raise RuntimeError("Source, assets, launcher or manifest changed after preparation. Prepare again before disconnecting.")
    return receipt


def empty_cache(data: Path) -> Path:
    hub = data / "inference-worker/huggingface/hub"
    checks.prepare_directory(hub)
    if any(p.is_file() for p in hub.parent.rglob("*")):
        raise RuntimeError("This run's owned Hub cache is not empty. It will not be cleared or reused.")
    return hub


def smoke_ui(run: Path) -> dict[str, Any]:
    from PySide6.QtCore import QEventLoop, QTimer
    from stoneglass.app import create_application
    from stoneglass.services.application import ApplicationServices
    from stoneglass.services.paths import AppPaths
    from stoneglass.ui.main_window import MainWindow
    app = create_application(["stoneglass-offline-ui-preparation"])
    app.setQuitOnLastWindowClosed(False)
    paths = AppPaths(run / "smoke-desktop-data"); paths.ensure()
    window = MainWindow(ApplicationServices.create(paths), start_hardware_scan=False)
    window.show()
    loop = QEventLoop(); QTimer.singleShot(200, loop.quit); loop.exec()
    safe = (not window.generate_page.generate_button.isEnabled() and not window.tasks.busy
            and not window.services.inference.requires_cleanup and window.generate_page.preview.image_info is None)
    window.close(); window.deleteLater(); app.processEvents()
    if not safe:
        raise RuntimeError("Model-free desktop startup was not idle with generation disabled.")
    return {"native_qt_platform": app.platformName(), "idle_generation_disabled": True, "model_loaded": False}


def prepare(manifest_path: Path, run: Path, journal: UIJournal) -> dict[str, Any]:
    local = local_profile(manifest_path, run, journal)
    launcher = checks.RecordingLauncher()
    client = checks.WorkerClient(checks.WorkerSettings.for_project(PROJECT, run / "startup-worker"), launcher)
    journal.log("Checking production worker ready/unload/close; no GPU initialization or weight loading.")
    try:
        client.call("unload", {}, journal, timeout=30, stage=checks.ProgressStage.UNLOADING)
    finally:
        client.close()
    cleanup = launcher.evidence()
    if not cleanup["all_owned_jobs_closed"] or not cleanup["all_normal_exit"]:
        raise RuntimeError("Preparation worker did not close normally. Stop for review.")
    receipt = {"schema": 1, "kind": "offline-ui", "status": "prepared", "prepared_at": checks.utc_now(),
               "local": local, "startup_cleanup": cleanup, "ui_smoke": smoke_ui(run),
               "model_weights_loaded": False, "image_generated": False}
    checks.write_json(run / "preparation.json", receipt)
    checks.write_json(ARTIFACTS / "prepared.json", receipt)
    return receipt


class Session:
    """Observe actual UI signals; operator alone validates, generates, cancels and saves."""
    def __init__(self, manifest_path: Path, run: Path, journal: UIJournal, result: dict[str, Any]) -> None:
        from PySide6.QtCore import QTimer
        from stoneglass.app import create_application
        from stoneglass.services.application import ApplicationServices
        from stoneglass.services.paths import AppPaths
        from stoneglass.services.logging_setup import configure_logging
        from stoneglass.ui.main_window import MainWindow
        self.run, self.journal, self.result = run, journal, result
        self.failures: list[str] = []
        self.actions: list[dict[str, Any]] = []
        self.exports: list[Path] = []
        self.outcome = None
        self.claimed = 0
        self.data = run / "desktop-data"
        hub = empty_cache(self.data)
        result.update(initial_owned_hub_cache_empty=True, hub_cache=str(hub))
        session = self

        class Launcher(checks.RecordingLauncher):
            def start(self, spec: checks.LaunchSpec) -> Any:
                cache = Path(spec.environment["HF_HUB_CACHE"])
                if not cache.is_relative_to(session.data) or (cache.exists() and any(p.is_file() for p in cache.rglob("*"))):
                    raise RuntimeError("A UI worker requires this run's empty owned Hub cache.")
                channel = super().start(spec)
                session.journal.log(f"Fresh owned UI worker launched (PID {self.processes[-1].pid}); Hub cache empty.")
                return channel

        self.launcher = Launcher()
        self.app = create_application(["stoneglass-offline-ui-acceptance"])
        self.app.setQuitOnLastWindowClosed(True)
        paths = AppPaths(self.data); paths.ensure(); configure_logging(paths.log_dir)
        self.window = MainWindow(ApplicationServices.create(paths, launcher=self.launcher))
        manifest = checks.read_manifest(manifest_path)
        self.window.models_page.checkpoint.setText(str(manifest.checkpoint))
        self.window.models_page.manifest.setText(str(manifest_path))
        page = self.window.generate_page
        page.width.setValue(512); page.height.setValue(512); page.steps.setValue(20)
        page.guidance.setValue(5.0); page.seed.setValue(12345)
        page.positive_prompt.setPlainText(checks.PROMPT); page.negative_prompt.clear()
        self.window.models_page.validate_button.clicked.connect(lambda: self.watch("readiness"))
        page.generate_button.clicked.connect(lambda: self.watch("generation"))
        page.preview.export_requested.connect(self.watch_export)
        self.window.generation_controller.completed.connect(self.completed)
        self.window.navigation.setCurrentRow(1)
        self.watchdog = QTimer(self.window); self.watchdog.setInterval(1000)
        self.watchdog.timeout.connect(self.deadline); self.watchdog.start()

    def deadline(self) -> None:
        if time.monotonic() - self.journal.started > 3600:
            if "Session exceeded one hour." not in self.failures:
                self.failures.append("Session exceeded one hour.")
            self.window.close()  # Existing close path cancels and waits for owned cleanup.

    def watch(self, kind: str) -> None:
        handle = self.window.generation_controller.active
        if handle is None:
            self.failures.append("The UI did not submit the requested inference task.")
            return
        action: dict[str, Any] = {"kind": kind, "started_seconds": time.monotonic()-self.journal.started, "status": "running"}
        self.actions.append(action)
        if kind == "generation":
            request = self.window.generate_page.generation_request()
            if (request.positive_prompt != checks.PROMPT or request.negative_prompt != ""
                    or request.settings != checks.request().settings):
                self.failures.append("Generation settings differ from the approved fixed offline request.")
                handle.cancel()
        handle.progress_event.connect(self.journal.report_event)
        handle.succeeded.connect(lambda _: action.update(status="succeeded"))
        handle.cancelled.connect(lambda: action.update(status="cancelled"))
        def failed(message: str) -> None:
            action.update(status="failed", error=message)
            self.failures.append(message); self.journal.log("UI task failed: " + message)
        handle.failed.connect(failed)
        def finished() -> None:
            action["elapsed_seconds"] = time.monotonic()-self.journal.started-action["started_seconds"]
            processes = self.launcher.processes[self.claimed:]; self.claimed = len(self.launcher.processes)
            action["workers"] = [{"pid": p.pid, "exit_code": p.poll(),
                "closed": p._process is None and p._job is None} for p in processes]
            allowed = (0, 1223) if action["status"] == "cancelled" else (0,)
            if action["status"] == "succeeded" and not processes:
                self.failures.append("A successful inference action lacks fresh worker evidence.")
            if any(not p["closed"] or p["exit_code"] not in allowed for p in action["workers"]):
                self.failures.append("UI action did not clean up its owned workers correctly.")
            self.result["actions"] = self.actions
            checks.write_json(self.run / "session-actions.json", {"actions": self.actions})
            self.journal.log(f"UI {kind}: {action['status']}; owned worker cleanup recorded.")
        handle.finished.connect(finished)

    def completed(self, outcome: Any) -> None:
        info = validate_png(outcome.image.path, 512, 512)
        if outcome.result.seed != 12345 or self.window.generate_page.preview.image_info != outcome.image:
            raise RuntimeError("UI output/preview does not match the fixed acceptance request.")
        if self.window.services.inference.requires_cleanup:
            raise RuntimeError("UI reported success while an inference worker still needs cleanup.")
        self.outcome = outcome
        self.result.update(image_before_shutdown=checks.verify_image(info.path), diagnostics=outcome.diagnostics,
                           preview_full_resolution=not self.window.generate_page.preview.canvas.original.isNull()
                               and self.window.generate_page.preview.canvas.original.width() == 512
                               and self.window.generate_page.preview.canvas.original.height() == 512)
        self.window.grab().save(str(self.run / "generated-preview.png"))
        self.journal.log("Real image validated and previewed. Choose Save PNG, save inside this evidence directory, then close Stoneglass normally.")
        self.journal.log("Suggested export: " + str(self.run / "exported-full-resolution.png"))

    def watch_export(self) -> None:
        from stoneglass.infrastructure.workers import TaskHandle
        # Save's original slot returns after its real file dialog and submits its
        # task; queued results cannot arrive until this GUI signal returns.
        for handle in self.window.tasks.findChildren(TaskHandle):
            if any(job.handle is handle and job.thread.objectName() == "image-export" for job in self.window.tasks._jobs.values()):
                handle.succeeded.connect(lambda path: self.exports.append(Path(path)))
                handle.failed.connect(lambda message: self.failures.append("PNG export failed: " + message))

    def run_ui(self) -> None:
        old_hook = sys.excepthook
        def unexpected(kind: type, exception: BaseException, tb: Any) -> None:
            self.failures.append("Unexpected UI exception; see diagnostics.log.")
            with (self.run / "diagnostics.log").open("a", encoding="utf-8") as stream:
                traceback.print_exception(kind, exception, tb, file=stream)
            self.window.close()
        sys.excepthook = unexpected
        try:
            self.window.show()
            self.journal.log("Operate Stoneglass: Validate model, Generate, inspect preview, Save PNG, then close normally. Do not change the fixed request.")
            self.app.exec()  # Real Qt event loop; no QtTest polling or scripted UI clicks.
        finally:
            sys.excepthook = old_hook
            if self.window.isVisible() or self.window.tasks.busy or self.window.services.inference.requires_cleanup:
                # Also use the production close/cancel path when the event loop
                # exits exceptionally. Never discard a live QThread/owned job.
                from PySide6.QtCore import QEventLoop, QTimer
                self.window.close()
                loop, timer = QEventLoop(), QTimer()
                deadline = time.monotonic() + 30
                def poll_cleanup() -> None:
                    clean = not self.window.tasks.busy and not self.window.services.inference.requires_cleanup
                    if clean and not self.window.isVisible(): loop.quit()
                    elif time.monotonic() >= deadline:
                        self.failures.append("Bounded UI shutdown did not finish. Preserve incomplete cleanup evidence.")
                        loop.quit()
                timer.timeout.connect(poll_cleanup); timer.start(50); loop.exec(); timer.stop()
            self.result.update(actions=self.actions, cleanup=self.launcher.evidence(), failures=self.failures,
                               ui_closed=not self.window.isVisible())
        if self.window.tasks.busy or self.window.services.inference.requires_cleanup:
            raise RuntimeError("The UI exited with unfinished tasks or retained worker ownership.")
        if self.failures or self.outcome is None or not self.result.get("preview_full_resolution"):
            raise RuntimeError("UI test incomplete or failed. A successful real generation and preview are required. " + "; ".join(self.failures))
        if not all(any(a["kind"] == kind and a["status"] == "succeeded" for a in self.actions) for kind in ("readiness", "generation")):
            raise RuntimeError("Successful operator readiness and generation actions must both be recorded.")
        image = checks.verify_image(self.outcome.image.path)
        if image["sha256"] != self.result["image_before_shutdown"]["sha256"]:
            raise RuntimeError("The output changed during UI shutdown.")
        matching_exports = [p for p in self.exports if p.is_relative_to(self.run) and p != self.outcome.image.path
                            and validate_png(p, 512, 512).sha256 == image["sha256"]]
        if not matching_exports:
            raise RuntimeError("A successful Save PNG export inside this evidence directory is required. Original image preserved.")
        if not self.result["cleanup"]["all_owned_jobs_closed"] or self.claimed != len(self.launcher.processes):
            raise RuntimeError("Owned worker cleanup evidence is incomplete.")
        if list((self.data / "generated").glob("worker-*")):
            raise RuntimeError("A private worker output directory remains; preserve evidence for review.")
        if any(p.is_file() for p in Path(self.result["hub_cache"]).parent.rglob("*")):
            raise RuntimeError("The owned Hub cache contains files after the local UI run; stop for review.")
        self.result.update(image=image, export=checks.verify_image(matching_exports[-1]), export_bytes_identical=True,
                           final_owned_hub_cache_empty=True, private_worker_directories_removed=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-directory", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, default=checks.DEFAULT_MANIFEST)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--prepare-only", action="store_true")
    modes.add_argument("--operator-confirmed-disconnected", action="store_true")
    args = parser.parse_args(argv)
    run = checks.strict_local(args.run_directory, directory=True)
    if run.parent != ARTIFACTS or not run.name.startswith(("preparation-", "ui-execution-")) or (run / "result.json").exists():
        parser.error("Use a fresh run directory created by scripts/test-offline-ui.ps1; existing results will not be overwritten.")
    os.environ["QT_QPA_PLATFORM"] = "windows"
    journal = UIJournal(run)
    result: dict[str, Any] = {"schema": 1, "kind": "offline-ui", "started_at": checks.utc_now(), "status": "running",
        "local_checks_passed": False, "offline_acceptance_passed": False,
        "offline_acceptance_review": "pending_operator_execution" if args.prepare_only else "pending_online_review",
        "operator_confirmed_disconnected": args.operator_confirmed_disconnected,
        "request": {"prompt": checks.PROMPT, "negative_prompt": "", **asdict(checks.request().settings), "batch": 1}}
    checks.write_json(run / "result.json", result)
    code = 1
    try:
        if args.prepare_only:
            result.update(preparation=prepare(args.manifest, run, journal), status="prepared_no_generation")
        else:
            receipt = require_receipt(args.manifest)
            local = local_profile(args.manifest, run, journal)
            if local != receipt["local"]:
                raise RuntimeError("Local prerequisites changed after preparation. Prepare again before disconnecting.")
            result["local"] = local
            Session(args.manifest, run, journal, result).run_ui()
            if fingerprint() != local["ui_source_sha256"]:
                raise RuntimeError("Source/assets changed during the UI test. Preserve evidence and prepare again.")
            result["status"] = "local_ui_checks_passed_pending_operator_confirmation_and_review"
        if any(n in sys.modules for n in ("torch", "diffusers", "transformers")):
            raise RuntimeError("The UI runner unexpectedly imported inference libraries in the parent process.")
        result["local_checks_passed"], code = True, 0
    except KeyboardInterrupt:
        result.update(status="cancelled", error="Operator interrupted the launcher. Preserve all evidence; no acceptance is claimed.")
        code = 130
    except Exception as exc:
        result.update(status="failed", error_type=type(exc).__name__, error=str(exc))
        with (run / "diagnostics.log").open("a", encoding="utf-8") as stream: stream.write(traceback.format_exc())
        journal.log("FAILED: " + str(exc))
    finally:
        result.update(finished_at=checks.utc_now(), elapsed_seconds=time.monotonic()-journal.started,
            parent_inference_imported=any(n in sys.modules for n in ("torch", "diffusers", "transformers")))
        checks.write_json(run / "result.json", result)
        checks.write_json(ARTIFACTS / ("latest-preparation.json" if args.prepare_only else "latest-run.json"), {"run_directory": str(run)})
        journal.log(f"Finished: {result['status']} (exit {code}). Evidence: {run}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
