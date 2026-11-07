# SPDX-License-Identifier: GPL-3.0-or-later
"""Launcher safeguards and postflight fixtures only; no GPU, weights or generation."""
import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from test_stage3_services import fixture_png

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("offline_ui_driver", ROOT / "scripts/offline_ui_acceptance.py")
driver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(driver)


class OfflineUIAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="stoneglass-ui-acceptance-unit-")
        self.artifacts = Path(self.temp.name)/"offline-ui-acceptance"
        self.run = self.artifacts/"preparation-unit"; self.run.mkdir(parents=True)
        self.paths = patch.object(driver, "ARTIFACTS", self.artifacts); self.paths.start()
        self.environment = patch.dict(driver.os.environ, {}, clear=False); self.environment.start()
        self.journal = driver.UIJournal(self.run); self.journal.log = Mock()
        self.manifest = self.run/"manifest.json"; self.manifest.write_text("{}")
        self.local = {"manifest_sha256": driver.checks.digest(self.manifest), "ui_source_sha256": {"test": "reviewed"}}

    def tearDown(self):
        self.environment.stop(); self.paths.stop(); self.temp.cleanup()

    def receipt(self, **changes):
        value = {"schema": 1, "kind": "offline-ui", "status": "prepared", "local": self.local}
        value.update(changes); driver.checks.write_json(self.artifacts/"prepared.json", value)

    def test_receipt_is_ui_specific_and_rejects_stale_source_or_manifest(self):
        with self.assertRaisesRegex(RuntimeError, "receipt missing"): driver.require_receipt(self.manifest)
        self.receipt(kind="backend")
        with self.assertRaisesRegex(RuntimeError, "older backend"): driver.require_receipt(self.manifest)
        self.receipt()
        with patch.object(driver, "fingerprint", return_value={"test": "changed"}):
            with self.assertRaisesRegex(RuntimeError, "changed after preparation"): driver.require_receipt(self.manifest)
        with patch.object(driver, "fingerprint", return_value={"test": "reviewed"}):
            self.assertEqual(driver.require_receipt(self.manifest)["kind"], "offline-ui")
            self.manifest.write_text('{"changed": true}')
            with self.assertRaisesRegex(RuntimeError, "changed after preparation"): driver.require_receipt(self.manifest)

    def test_prepare_only_checks_worker_startup_and_model_free_ui(self):
        client, launcher = Mock(), Mock()
        launcher.evidence.return_value = {"all_owned_jobs_closed": True, "all_normal_exit": True}
        with patch.object(driver, "local_profile", return_value=self.local), \
             patch.object(driver.checks, "WorkerClient", return_value=client), \
             patch.object(driver.checks, "RecordingLauncher", return_value=launcher), \
             patch.object(driver, "smoke_ui", return_value={"model_loaded": False}), \
             patch.object(driver, "Session") as session:
            receipt = driver.prepare(self.manifest, self.run, self.journal)
        session.assert_not_called(); client.close.assert_called_once()
        self.assertEqual(client.call.call_args.args[0], "unload")
        self.assertFalse(receipt["model_weights_loaded"]); self.assertFalse(receipt["image_generated"])
        self.assertTrue((self.artifacts/"prepared.json").is_file())

    def test_operator_session_opens_with_fixed_inputs_and_no_automatic_worker(self):
        from qt_support import APP
        from stoneglass.ui.main_window import MainWindow
        quit_before = APP.quitOnLastWindowClosed()
        with patch.object(driver.checks, "read_manifest", return_value=SimpleNamespace(checkpoint=self.run/"unit.safetensors")), \
             patch.object(MainWindow, "scan_hardware"), \
             patch("stoneglass.services.logging_setup.configure_logging"), \
             patch("stoneglass.inference.local_process.LocalWorkerLauncher.start") as start:
            session = driver.Session(self.manifest, self.run, self.journal, {})
            try:
                self.assertFalse(session.window.generate_page.generate_button.isEnabled())
                self.assertEqual(session.window.generate_page.positive_prompt.toPlainText(), driver.checks.PROMPT)
                self.assertEqual(session.window.generate_page.preferences(), driver.checks.request().settings)
                self.assertEqual(session.launcher.processes, [])
                self.assertTrue(session.result["initial_owned_hub_cache_empty"])
                start.assert_not_called()
            finally:
                APP.setQuitOnLastWindowClosed(quit_before)
                session.window.close(); session.window.deleteLater(); APP.processEvents()

    def test_nonempty_owned_cache_is_preserved_and_rejected(self):
        data = self.run/"data"; cache = driver.empty_cache(data)
        private = cache/"do-not-delete"; private.write_text("unit fixture")
        with self.assertRaisesRegex(RuntimeError, "not empty"): driver.empty_cache(data)
        self.assertTrue(private.exists())

    def test_mode_required_and_existing_evidence_never_overwritten(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            driver.main(["--run-directory", str(self.run)])
        self.assertFalse((self.run/"result.json").exists())
        original = b'{"existing":true}'; (self.run/"result.json").write_bytes(original)
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            driver.main(["--run-directory", str(self.run), "--prepare-only"])
        self.assertEqual((self.run/"result.json").read_bytes(), original)

    def test_changed_prerequisites_stop_before_ui_and_keep_acceptance_pending(self):
        with patch.object(driver, "require_receipt", return_value={"local": self.local}), \
             patch.object(driver, "local_profile", return_value={"changed": True}), \
             patch.object(driver, "Session") as session, redirect_stdout(io.StringIO()):
            code = driver.main(["--run-directory", str(self.run), "--operator-confirmed-disconnected"])
        session.assert_not_called(); self.assertEqual(code, 1)
        result = json.loads((self.run/"result.json").read_text())
        self.assertFalse(result["offline_acceptance_passed"]); self.assertFalse(result["local_checks_passed"])
        self.assertTrue((self.run/"diagnostics.log").exists())

    def postflight_fixture(self):
        # Static PNG bytes and a mocked closed window are explicitly test data.
        session = driver.Session.__new__(driver.Session)
        session.run, session.journal = self.run, self.journal
        session.data = self.run/"desktop-data"; cache = driver.empty_cache(session.data)
        output = session.data/"generated/fixture.png"; output.parent.mkdir(); fixture_png(output)
        session.result = {"preview_full_resolution": True, "hub_cache": str(cache),
                          "image_before_shutdown": driver.checks.verify_image(output)}
        session.outcome = SimpleNamespace(image=SimpleNamespace(path=output))
        session.app = Mock()
        session.window = Mock(); session.window.isVisible.return_value = False
        session.window.tasks.busy = False; session.window.services.inference.requires_cleanup = False
        session.launcher = Mock(); session.launcher.processes = []
        session.launcher.evidence.return_value = {"all_owned_jobs_closed": True, "all_normal_exit": True}
        session.claimed, session.failures, session.exports = 0, [], []
        session.actions = [{"kind": "readiness", "status": "succeeded"}, {"kind": "generation", "status": "succeeded"}]
        return session, output

    def test_postflight_requires_actual_save_export_and_preserves_output_on_failure(self):
        session, output = self.postflight_fixture()
        with self.assertRaisesRegex(RuntimeError, "Save PNG export"): session.run_ui()
        self.assertTrue(output.exists())
        exported = self.run/"exported.png"; exported.write_bytes(output.read_bytes()); session.exports.append(exported)
        session.run_ui()
        self.assertTrue(session.result["export_bytes_identical"])
        self.assertTrue(session.result["final_owned_hub_cache_empty"])

    def test_postflight_rejects_changed_image_and_unclosed_jobs(self):
        session, output = self.postflight_fixture()
        fixture_png(output, b'\x70\x50\x30')
        with self.assertRaisesRegex(RuntimeError, "changed during UI shutdown"): session.run_ui()
        session.result["image_before_shutdown"] = driver.checks.verify_image(output)
        exported = self.run/"export.png"; exported.write_bytes(output.read_bytes()); session.exports.append(exported)
        session.launcher.evidence.return_value = {"all_owned_jobs_closed": False}
        with self.assertRaisesRegex(RuntimeError, "cleanup evidence"): session.run_ui()

    def test_progress_does_not_display_estimated_loading_percentage(self):
        driver.UIJournal.report_event(self.journal, driver.checks.ProgressEvent(driver.checks.ProgressStage.LOADING, 97, "Waiting for local runtime work"))
        self.assertNotIn("97%", self.journal.log.call_args.args[0])
        event = json.loads((self.run/"progress.jsonl").read_text().splitlines()[0])
        self.assertEqual(event["percent"], 97)
