# SPDX-License-Identifier: GPL-3.0-or-later
"""Standalone runner safety/failure tests. Never load weights or create images."""

import hashlib
import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("offline_acceptance_driver", ROOT / "scripts/offline_acceptance.py")
driver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(driver)


class OfflineAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="stoneglass-acceptance-unit-")
        self.artifacts = Path(self.temp.name) / "offline-acceptance"
        self.run = self.artifacts / "preparation-unit"
        self.run.mkdir(parents=True)
        self.paths = patch.object(driver, "ARTIFACTS", self.artifacts)
        self.paths.start()
        self.journal = driver.Journal(self.run)
        self.journal.log = Mock()
        self.manifest = Path(self.temp.name) / "manifest.json"
        self.manifest.write_text('{}', encoding="utf-8")
        self.local = {"manifest_sha256": hashlib.sha256(b'{}').hexdigest(), "source_sha256": {"source": "reviewed"}}

    def tearDown(self):
        self.paths.stop()
        self.temp.cleanup()

    def receipt(self):
        driver.write_json(self.artifacts / "prepared.json", {"schema": 1, "status": "prepared", "local": self.local})

    def test_prepare_never_constructs_generation_backend(self):
        worker = Mock()
        launcher = Mock()
        launcher.evidence.return_value = {"all_owned_jobs_closed": True, "all_normal_exit": True}
        with patch.object(driver, "check_local", return_value=self.local), \
             patch.object(driver, "RecordingLauncher", return_value=launcher), \
             patch.object(driver, "WorkerClient", return_value=worker), \
             patch.object(driver, "SDXLProcessBackend") as backend:
            receipt = driver.prepare(self.manifest, self.run, self.journal)
        backend.assert_not_called()
        self.assertEqual(worker.call.call_args.args[0], "unload")
        worker.close.assert_called_once()
        self.assertFalse(receipt["image_generated"])
        self.assertFalse(receipt["model_weights_loaded"])
        self.assertTrue((self.artifacts / "prepared.json").exists())

    def test_missing_or_stale_preparation_stops_before_backend(self):
        with patch.object(driver, "SDXLProcessBackend") as backend:
            with self.assertRaisesRegex(RuntimeError, "receipt is missing"):
                driver.execute(self.manifest, self.run, self.journal, {})
            self.receipt()
            with patch.object(driver, "source_fingerprint", return_value={"source": "changed"}), \
                 patch.object(driver, "check_local") as check:
                with self.assertRaisesRegex(RuntimeError, "changed after preparation"):
                    driver.execute(self.manifest, self.run, self.journal, {})
                check.assert_not_called()
            backend.assert_not_called()

    def test_nonempty_new_cache_is_preserved_and_blocks_generation(self):
        self.receipt()
        settings = driver.WorkerSettings.for_project(driver.PROJECT, self.run / "worker-state")
        existing = settings.data_directory / "huggingface/hub/preserve.txt"
        existing.parent.mkdir(parents=True)
        existing.write_text("preserve")
        with patch.object(driver, "source_fingerprint", return_value=self.local["source_sha256"]), \
             patch.object(driver, "check_local", return_value=self.local), \
             patch.object(driver, "SDXLProcessBackend") as backend:
            with self.assertRaisesRegex(RuntimeError, "not empty"):
                driver.execute(self.manifest, self.run, self.journal, {})
        backend.assert_not_called()
        self.assertEqual(existing.read_text(), "preserve")

    def test_load_failure_cleans_up_and_retries_without_generating(self):
        self.receipt()
        backend, launcher = Mock(), Mock()
        backend._run = self.run / "never-created"
        backend.load_model.side_effect = RuntimeError("unit fixture load failure")
        backend.unload.side_effect = [RuntimeError("unit fixture retry"), None]
        launcher.evidence.return_value = {"all_owned_jobs_closed": True, "all_normal_exit": False}
        result = {}
        with patch.object(driver, "source_fingerprint", return_value=self.local["source_sha256"]), \
             patch.object(driver, "check_local", return_value=self.local), \
             patch.object(driver, "read_manifest", return_value=SimpleNamespace(checkpoint=self.manifest)), \
             patch.object(driver, "RecordingLauncher", return_value=launcher), \
             patch.object(driver, "SDXLProcessBackend", return_value=backend):
            with self.assertRaisesRegex(RuntimeError, "unit fixture load failure"):
                driver.execute(self.manifest, self.run, self.journal, result)
        backend.generate.assert_not_called()
        self.assertEqual(backend.unload.call_count, 2)
        self.assertEqual(len(result["cleanup_errors"]), 1)
        self.assertTrue(result["cleanup"]["all_owned_jobs_closed"])

    def test_failure_is_saved_without_claiming_acceptance_or_overwriting_run(self):
        with patch.object(driver, "prepare", side_effect=RuntimeError("unit fixture prerequisite missing")), redirect_stdout(io.StringIO()):
            code = driver.main(["--run-directory", str(self.run), "--prepare-only"])
        result = json.loads((self.run / "result.json").read_text())
        self.assertEqual(code, 1)
        self.assertFalse(result["local_checks_passed"])
        self.assertFalse(result["offline_acceptance_passed"])
        self.assertEqual(result["status"], "failed")
        self.assertTrue((self.run / "diagnostics.log").exists())
        original = (self.run / "result.json").read_bytes()
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            driver.main(["--run-directory", str(self.run), "--prepare-only"])
        self.assertEqual((self.run / "result.json").read_bytes(), original)

    def test_explicit_mode_is_required(self):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            driver.main(["--run-directory", str(self.run)])
        self.assertFalse((self.run / "result.json").exists())

    def test_invalid_image_is_preserved_for_review(self):
        path = self.run / "not-an-image.png"
        path.write_bytes(b"unit fixture, deliberately not an image")
        with self.assertRaisesRegex(RuntimeError, "not a PNG"):
            driver.verify_image(path)
        self.assertTrue(path.exists())

    def test_fixed_request_matches_approved_profile(self):
        request = driver.request()
        self.assertEqual(request.positive_prompt, "A photorealistic red sports car parked beside a mountain lake at sunset.")
        self.assertEqual((request.settings.width, request.settings.height, request.settings.steps,
                          request.settings.guidance, request.settings.seed), (512, 512, 20, 5.0, 12345))
        self.assertEqual(request.negative_prompt, "")

    def test_repeated_waiting_progress_keeps_console_alive(self):
        event = driver.ProgressEvent(driver.ProgressStage.LOADING, 0, "Waiting for local runtime work")
        self.journal.report_event(event)
        self.journal.log.reset_mock()
        self.journal.last_console -= 11
        self.journal.report_event(event)
        self.journal.log.assert_called_once()
