# SPDX-License-Identifier: GPL-3.0-or-later
"""Standalone developer acceptance driver; inference stays in Stoneglass's worker.

Preparation never constructs the SDXL backend. There is no mock/alternate pipeline
CLI mode. All evidence and images live under .test-artifacts/offline-acceptance.
"""

import argparse
import contextlib
import hashlib
import importlib.metadata
import io
import json
import os
import shutil
import struct
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))
if sys.flags.no_site:
    # Python 3.13 -S skips venv prefix setup and .pth hooks.
    environment = Path(sys.executable).parent.parent
    sys.prefix = sys.exec_prefix = str(environment)
    sys.path.append(str(environment / "Lib/site-packages"))

from stoneglass.domain.settings import GenerationSettings
from stoneglass.inference.contracts import GenerationRequest, ModelSpec, ProgressEvent, ProgressStage, RuntimeDevice, RuntimeKind
from stoneglass.inference.local_process import LocalWorkerLauncher, _spawn_owned, prepare_directory
from stoneglass.inference.offline import assert_library_policy, offline_environment
from stoneglass.inference.process_backend import SDXLProcessBackend
from stoneglass.inference.resources import read_manifest, strict_local, validate_sdxl
from stoneglass.inference.worker import LaunchSpec, PipeChannel, WorkerClient, WorkerSettings

ARTIFACTS = PROJECT / ".test-artifacts/offline-acceptance"
DEFAULT_MANIFEST = PROJECT / ".local-data/sdxl-bundles/base-initial/manifest.json"
CHECKPOINT_SHA256 = "c379d154eb476b67b390e31463c41c79ac9e766466315408886ebb7faa2ea098"
MODEL_ID = "offline-acceptance-albedobase-xl-v31"
PROMPT = "A photorealistic red sports car parked beside a mountain lake at sunset."
PINS = {
    "torch": "2.13.0+rocm10.0.0", "torchvision": "0.28.0+rocm10.0.0",
    "diffusers": "0.40.0", "transformers": "5.16.1", "accelerate": "1.15.0",
    "safetensors": "0.8.0", "huggingface-hub": "1.30.0", "tokenizers": "0.23.2",
    "numpy": "2.5.2", "pillow": "12.3.0", "rocm": "10.0.0", "rocm-bootstrap": "0.1.0",
    "rocm-sdk-core": "10.0.0", "rocm-sdk-libraries": "10.0.0", "rocm-sdk-device-gfx1200": "10.0.0",
    "amd-torch-device-gfx1200": "2.13.0+rocm10.0.0", "amd-torch-device-gfx12-0": "2.13.0+rocm10.0.0",
    "amd-torchvision-device-gfx1200": "0.28.0+rocm10.0.0",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with strict_local(path).open("rb") as stream:
        while block := stream.read(4 * 1024 * 1024):
            value.update(block)
    return value.hexdigest()


def write_json(path: Path, data: dict[str, Any]) -> None:
    temporary = path.with_suffix(".writing")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(data, stream, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


class Journal:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.started = time.monotonic()
        self.last_message = ""
        self.last_percent = -10
        self.last_console = self.started

    def log(self, message: str) -> None:
        line = f"[{time.monotonic() - self.started:7.1f}s] {message}"
        with (self.directory / "console.log").open("a", encoding="utf-8") as stream:
            stream.write(line + "\n")
        print(line, flush=True)

    def check_cancelled(self) -> None:
        pass  # Ctrl+C raises KeyboardInterrupt; production worker cleanup owns termination.

    def report_progress(self, percent: int, message: str) -> None:
        self.report_event(ProgressEvent(ProgressStage.VALIDATING, percent, message))

    def report_event(self, event: ProgressEvent) -> None:
        with (self.directory / "progress.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"at": utc_now(), "elapsed_seconds": time.monotonic() - self.started,
                "stage": event.stage.value, "percent": event.percent, "message": event.message}) + "\n")
        if (event.message != self.last_message or abs(event.percent - self.last_percent) >= 10
                or time.monotonic() - self.last_console >= 10):
            self.log(f"{event.stage.value}: {event.percent}% - {event.message}")
            self.last_message, self.last_percent = event.message, event.percent
            self.last_console = time.monotonic()


class RecordingLauncher(LocalWorkerLauncher):
    def __init__(self) -> None:
        self.processes: list[Any] = []

    def start(self, spec: LaunchSpec) -> Any:
        channel = super().start(spec)
        self.processes.append(channel._process)
        return channel

    def evidence(self) -> dict[str, Any]:
        return {"owned_processes": [{"launcher_pid": p.pid, "exit_code": p.poll(),
                "process_and_job_handles_closed": p._process is None and p._job is None} for p in self.processes],
                "all_owned_jobs_closed": bool(self.processes) and all(p._process is None and p._job is None for p in self.processes),
                "all_normal_exit": bool(self.processes) and all(p.poll() == 0 for p in self.processes)}


def inspect_environment() -> dict[str, Any]:
    """Read-only child mode. Metadata/file checks and pip check; no GPU imports."""
    assert_library_policy()
    missing, versions, checked = [], {}, 0
    for name, expected in PINS.items():
        try:
            distribution = importlib.metadata.distribution(name)
            versions[name] = distribution.version
            if distribution.version != expected:
                missing.append(f"{name}: expected {expected}, found {distribution.version}")
            files = distribution.files
            if not files:
                missing.append(f"{name}: installed file inventory is missing")
            for entry in files or ():
                if str(entry).endswith(".pyc"):
                    continue
                checked += 1
                if not distribution.locate_file(entry).is_file() and len(missing) < 30:
                    missing.append(f"{name}: missing installed file {entry}")
        except importlib.metadata.PackageNotFoundError:
            missing.append(f"Missing local dependency: {name}=={expected}")
    output = io.StringIO()
    with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
        from pip._internal.cli.main import main as pip_main
        pip_result = pip_main(["--disable-pip-version-check", "check"])
    return {"python": sys.version, "python_version": list(sys.version_info[:3]), "pointer_bits": struct.calcsize("P") * 8,
        "executable": sys.executable, "versions": versions, "missing": missing, "installed_files_checked": checked,
        "pip_check_exit": pip_result, "pip_check_output": output.getvalue()[:4000],
        "inference_imported": any(n in sys.modules for n in ("torch", "diffusers", "transformers"))}


def dependency_probe(run: Path) -> dict[str, Any]:
    python = strict_local(PROJECT / ".venv-rocm/Scripts/python.exe")
    root = run / "dependency-probe"
    environment = offline_environment(root)
    environment.update({"PIP_NO_INDEX": "1", "PIP_DISABLE_PIP_VERSION_CHECK": "1", "PIP_CONFIG_FILE": os.devnull})
    for key in ("HF_HOME", "HF_HUB_CACHE", "XDG_CACHE_HOME", "TEMP"):
        prepare_directory(Path(environment[key]))
    spec = LaunchSpec((str(python), "-I", "-S", "-B", "-X", "utf8", str(Path(__file__)), "--inspect-environment"), environment, run)
    process = _spawn_owned(spec)
    channel = PipeChannel(process)
    try:
        report = channel.receive(60)
        if report is None:
            raise RuntimeError("Local dependency inspection timed out. Nothing was installed or downloaded.")
        channel.finish_input()
    finally:
        channel.close()
    if process.poll() != 0:
        raise RuntimeError("Local dependency inspection failed. Restore the approved environment manually.")
    report["probe_cleanup"] = {"exit_code": process.poll(), "owned_process_and_job_closed": process._process is None and process._job is None}
    if report.get("error"):
        raise RuntimeError(f"Local dependency inspection failed: {report['error']}")
    if report["python_version"] != [3, 13, 12] or report["pointer_bits"] != 64:
        raise RuntimeError("The worker requires the existing Python 3.13.12 x64 environment.")
    if report["missing"] or report["pip_check_exit"] != 0 or report["inference_imported"]:
        raise RuntimeError("Local dependencies are incomplete/incompatible: " + "; ".join(report["missing"]) + " " + report["pip_check_output"])
    return report


def source_fingerprint() -> dict[str, str]:
    files = [*sorted((PROJECT / "src/stoneglass").rglob("*.py")), Path(__file__), PROJECT / "scripts/test-offline.ps1"]
    return {str(path.relative_to(PROJECT)): digest(path) for path in files}


def request() -> GenerationRequest:
    return GenerationRequest(PROMPT, "", GenerationSettings(width=512, height=512, steps=20, guidance=5.0, seed=12345), MODEL_ID)


def verify_image(path: Path) -> dict[str, Any]:
    from PySide6.QtGui import QImage
    path = strict_local(path)
    if path.read_bytes()[:8] != b"\x89PNG\r\n\x1a\n":
        raise RuntimeError("The committed output is not a PNG; it was preserved for review.")
    image = QImage(str(path))
    if image.isNull() or (image.width(), image.height()) != (512, 512):
        raise RuntimeError("Output-image decoding or dimensions failed; the file was preserved for review.")
    rgb = image.convertToFormat(QImage.Format.Format_RGB888)
    pixels = bytes(rgb.constBits())
    if max(pixels) - min(pixels) <= 1:
        raise RuntimeError("The output is uniform/invalid; the file was preserved for review.")
    return {"path": str(path), "sha256": digest(path), "bytes": path.stat().st_size,
            "width": image.width(), "height": image.height(), "png_and_qt_decode_valid": True,
            "minimum_channel": min(pixels), "maximum_channel": max(pixels)}


def check_local(manifest_path: Path, run: Path, journal: Journal) -> dict[str, Any]:
    if shutil.disk_usage(run).free < 1024 ** 3:
        raise RuntimeError("Keep at least 1 GiB of free local disk space for test output, logs and caches.")
    journal.log("Verifying required local package versions, installed files and dependency resolution (no GPU initialization).")
    dependencies = dependency_probe(run)
    write_json(run / "dependencies.json", dependencies)
    from PySide6.QtGui import QImageReader
    if b"png" not in [bytes(value) for value in QImageReader.supportedImageFormats()]:
        raise RuntimeError("The existing GUI environment's local PNG image decoder is unavailable.")
    manifest_path = strict_local(manifest_path)
    manifest = read_manifest(manifest_path)
    if manifest.checkpoint_sha256 != CHECKPOINT_SHA256:
        raise RuntimeError("This acceptance profile requires the reviewed AlbedoBase XL v3.1-Large checkpoint.")
    journal.log("Hashing the complete local checkpoint and all 14 configuration/tokenizer resources.")
    validate_sdxl(manifest, journal)
    return {"manifest": str(manifest_path), "manifest_sha256": digest(manifest_path),
        "checkpoint": str(manifest.checkpoint), "checkpoint_sha256": manifest.checkpoint_sha256,
        "configuration_files": len(manifest.resources), "configuration_bytes": sum(r.bytes for r in manifest.resources),
        "source_sha256": source_fingerprint(), "dependency_versions": dependencies["versions"]}


def prepare(manifest_path: Path, run: Path, journal: Journal) -> dict[str, Any]:
    local = check_local(manifest_path, run, journal)
    journal.log("Checking production worker ready/unload/close without importing inference libraries or loading weights.")
    launcher = RecordingLauncher()
    client = WorkerClient(WorkerSettings.for_project(PROJECT, run / "worker-state"), launcher)
    try:
        client.call("unload", {}, journal, timeout=30, stage=ProgressStage.UNLOADING)
    finally:
        client.close()
    cleanup = launcher.evidence()
    if not cleanup["all_owned_jobs_closed"] or not cleanup["all_normal_exit"]:
        raise RuntimeError("Preparation worker did not terminate normally; do not proceed to offline testing.")
    receipt = {"schema": 1, "prepared_at": utc_now(), "status": "prepared", "model_weights_loaded": False,
               "image_generated": False, "local": local, "startup_cleanup": cleanup}
    write_json(run / "preparation.json", receipt)
    write_json(ARTIFACTS / "prepared.json", receipt)
    return receipt


def execute(manifest_path: Path, run: Path, journal: Journal, result: dict[str, Any]) -> None:
    if not (ARTIFACTS / "prepared.json").exists():
        raise RuntimeError("Preparation receipt is missing. Run scripts/test-offline.ps1 -PrepareOnly while connected and review its result.")
    prepared = strict_local(ARTIFACTS / "prepared.json")
    receipt = json.loads(prepared.read_text(encoding="utf-8"))
    if receipt.get("status") != "prepared" or receipt.get("schema") != 1:
        raise RuntimeError("Run scripts/test-offline.ps1 -PrepareOnly and review its result before disconnecting.")
    if digest(strict_local(manifest_path)) != receipt["local"]["manifest_sha256"] or source_fingerprint() != receipt["local"]["source_sha256"]:
        raise RuntimeError("The manifest or test/application scripts changed after preparation. Re-run preparation while connected.")
    local = check_local(manifest_path, run, journal)
    if local != receipt["local"]:
        raise RuntimeError("Local prerequisites changed after preparation; stop and review them before loading weights.")
    result["local"] = local
    settings = WorkerSettings.for_project(PROJECT, run / "worker-state")
    cache = settings.data_directory / "huggingface"
    prepare_directory(cache / "hub")
    if any(cache.iterdir()) and any(path.is_file() for path in cache.rglob("*")):
        raise RuntimeError("The new worker's owned Hub cache is not empty. It will not be cleared or reused.")
    result["initial_owned_hub_cache_empty"] = True
    result["hub_cache"] = str(cache / "hub")
    manifest = read_manifest(manifest_path)
    model = ModelSpec(MODEL_ID, manifest.checkpoint, resource_manifest=manifest_path)
    launcher = RecordingLauncher()
    backend = SDXLProcessBackend(settings, launcher)
    try:
        journal.log("Starting fresh production ROCm worker. Loading validated local SDXL; cold native work may take minutes.")
        started = time.monotonic()
        backend.load_model(model, RuntimeDevice(RuntimeKind.ROCM, 0, "AMD Radeon RX 9060 XT"), journal)
        result["model_loaded"] = True
        result["load_wall_seconds"] = time.monotonic() - started
        result["load_diagnostics"] = backend._client.call("diagnostics", {}, journal, timeout=10, stage=ProgressStage.LOADING)
        journal.log("Generating the real image: 512x512, batch 1, 20 steps, CFG 5.0, seed 12345.")
        started = time.monotonic()
        result["generation_started"] = True
        output = backend.generate(request(), journal)
        result["generation_wall_seconds"] = time.monotonic() - started
        if (output.width, output.height, output.seed, output.model_id) != (512, 512, 12345, MODEL_ID):
            raise RuntimeError("The worker returned unexpected generation metadata.")
        backend.commit_result(output)
        result["image_generated"] = True
        result["committed_image_path"] = str(output.image_path)
        result["image_before_shutdown"] = verify_image(output.image_path)
        result["generation_diagnostics"] = backend._client.call("diagnostics", {}, journal, timeout=10, stage=ProgressStage.GENERATING)
        journal.log("Image committed. Unloading and closing the worker; the final PNG is outside its temporary run directory.")
        result["unload_diagnostics"] = backend._client.call("unload", {}, journal, timeout=60, stage=ProgressStage.UNLOADING)
    finally:
        # Production cleanup runs on success, failure and Ctrl+C. A killed parent
        # also closes the existing kill-on-close job; no stale-PID termination.
        cleanup_error = None
        for attempt in range(2):
            try:
                backend.unload()
                cleanup_error = None
                break
            except Exception as exc:
                cleanup_error = exc
                result.setdefault("cleanup_errors", []).append(f"{type(exc).__name__}: {exc}")
                journal.log(f"Owned cleanup attempt {attempt + 1} failed; retaining ownership for bounded retry.")
        try:
            result["cleanup"] = launcher.evidence()
        except Exception as exc:
            result["cleanup"] = {"all_owned_jobs_closed": False, "all_normal_exit": False, "evidence_error": str(exc)}
        result["private_worker_run_directory_removed"] = not backend._run.exists()
        if cleanup_error is not None:
            raise RuntimeError("Owned worker cleanup failed after retry; preserve diagnostics and stop for review.") from cleanup_error
    if not result["cleanup"]["all_owned_jobs_closed"] or not result["cleanup"]["all_normal_exit"]:
        raise RuntimeError("Worker cleanup/normal exit failed. Preserve evidence; do not claim offline acceptance.")
    result["image"] = verify_image(Path(result["committed_image_path"]))
    if result["image"]["sha256"] != result["image_before_shutdown"]["sha256"]:
        raise RuntimeError("The committed image changed during worker shutdown.")
    journal.log(f"Preserved valid image: {result['image']['path']}")


def main(argv: list[str] | None = None) -> int:
    if argv is None and sys.argv[1:] == ["--inspect-environment"]:
        try:
            report = inspect_environment()
        except Exception as exc:
            report = {"error": f"{type(exc).__name__}: {exc}"}
        print(json.dumps(report), flush=True)
        return 0 if "error" not in report else 1
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-directory", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--prepare-only", action="store_true")
    modes.add_argument("--operator-confirmed-disconnected", action="store_true")
    args = parser.parse_args(argv)
    run = strict_local(args.run_directory, directory=True)
    if run.parent != ARTIFACTS or not run.name.startswith(("preparation-", "offline-execution-")):
        parser.error("Use a new run directory under .test-artifacts/offline-acceptance created by the PowerShell launcher.")
    if (run / "result.json").exists():
        parser.error("An existing run will not be overwritten; use a new launcher run.")
    journal = Journal(run)
    result: dict[str, Any] = {"schema": 1, "phase": "preparation" if args.prepare_only else "offline-execution",
        "started_at": utc_now(), "status": "running", "local_checks_passed": False,
        "offline_acceptance_passed": False, "offline_acceptance_review": "pending_operator_execution" if args.prepare_only else "pending_online_review",
        "operator_confirmed_disconnected": args.operator_confirmed_disconnected,
        "model_loaded": False, "image_generated": False, "generation_started": False,
        "network_settings_changed": False, "external_services_required": False,
        "model_credit": {"model": "AlbedoBase XL v3.1-Large", "creator": "albedobond",
                         "model_url": "https://civitai.com/models/140737?modelVersionId=1041855",
                         "creator_url": "https://civitai.com/user/albedobond", "license_url": "https://civitai.com/models/license/1041855"},
        "request": {"prompt": PROMPT, "negative_prompt": "", "width": 512, "height": 512,
                    "steps": 20, "cfg": 5.0, "seed": 12345, "batch": 1}}
    write_json(run / "result.json", result)
    code = 1
    try:
        if args.prepare_only:
            result["preparation"] = prepare(args.manifest, run, journal)
            result["status"] = "prepared_no_generation"
        else:
            journal.log("Operator confirmed physical disconnection. This statement is recorded, not independently verified by a network probe.")
            execute(args.manifest, run, journal, result)
            result["status"] = "local_test_passed_pending_online_review"
        result["local_checks_passed"], code = True, 0
    except KeyboardInterrupt:
        result.update({"status": "cancelled", "error": "Operator interrupted the test; review cleanup evidence."})
        journal.log(result["error"])
        code = 130
    except Exception as exc:
        result.update({"status": "failed", "error_type": type(exc).__name__, "error": str(exc)})
        (run / "diagnostics.log").write_text(traceback.format_exc(), encoding="utf-8")
        journal.log(f"FAILED: {type(exc).__name__}: {exc}")
        journal.log("Nothing was downloaded or installed. Keep this evidence directory for review.")
    finally:
        result["finished_at"], result["elapsed_seconds"] = utc_now(), time.monotonic() - journal.started
        result["parent_inference_imported"] = any(n in sys.modules for n in ("torch", "diffusers", "transformers"))
        write_json(run / "result.json", result)
        write_json(ARTIFACTS / ("latest-preparation.json" if args.prepare_only else "latest-run.json"), {"run_directory": str(run), "result": str(run / "result.json")})
        journal.log(f"Finished: {result['status']} (exit {code}). Result: {run / 'result.json'}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
