# SPDX-License-Identifier: GPL-3.0-or-later
"""UI workflows use mocked inference and static PNG fixtures, never GPU/models."""
import hashlib
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from threading import Event
from unittest.mock import Mock, patch
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QImage, QColor, QPainter
from PySide6.QtTest import QTest
from inference_support import make_rig
from qt_support import APP, wait_until
from stoneglass.domain.settings import GenerationSettings
from stoneglass.inference.contracts import GenerationResult, ProgressEvent, ProgressStage, RuntimeCapabilities, RuntimeDevice, RuntimeKind
from stoneglass.inference.errors import ErrorCode, InferenceError
from stoneglass.services.application import ApplicationServices
from stoneglass.services.paths import AppPaths
from stoneglass.ui.main_window import MainWindow


def png_fixture(path: Path, size=512) -> None:
    image = QImage(size, size, QImage.Format.Format_RGB32)
    image.fill(QColor("#245070"))
    painter = QPainter(image); painter.fillRect(0, 0, size // 2, size, QColor("#b05030")); painter.end()
    if not image.save(str(path), "PNG"): raise RuntimeError("Fixture encoding failed")


class Stage3UITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name); paths = AppPaths(self.root); paths.ensure()
        self.checkpoint = self.root / "unit.safetensors"; self.checkpoint.write_text("mock-only reference, never loaded")
        self.manifest = self.root / "manifest.json"; self.manifest.write_text("{}")
        self.output = self.root / "fixture.png"; png_fixture(self.output)
        self.rig = make_rig(self.checkpoint)
        self.rig.backend.generate.return_value = GenerationResult(self.output, 12345, 512, 512, "unit")
        self.window = MainWindow(replace(ApplicationServices.create(paths), inference=self.rig.service), start_hardware_scan=False)
        self.window.show(); APP.processEvents()
        self.page = self.window.generate_page
        self.models = self.window.models_page
        self.models.checkpoint.setText(str(self.checkpoint)); self.models.manifest.setText(str(self.manifest))
        self.page.width.setValue(512); self.page.height.setValue(512); self.page.steps.setValue(20)
        self.page.guidance.setValue(5.0); self.page.seed.setValue(12345)
        self.page.positive_prompt.setPlainText("PRIVATE positive test")
        self.page.negative_prompt.setPlainText("PRIVATE negative test")

    def tearDown(self):
        self.rig.backend.unload.side_effect = None
        self.window.tasks.cancel_all()
        wait_until(lambda: not self.window.tasks.busy, 5000)
        self.window.close(); wait_until(lambda: not self.window.tasks.busy and not self.window.isVisible(), 5000)
        self.window.deleteLater(); APP.processEvents(); self.temp.cleanup()

    def ready(self):
        self.window.navigation.setCurrentRow(1)
        QTest.mouseClick(self.models.validate_button, Qt.MouseButton.LeftButton)
        wait_until(lambda: not self.window.tasks.busy)
        self.assertIsNotNone(self.window.generation_controller.ready)
        self.window.navigation.setCurrentRow(0)
        self.assertTrue(self.page.generate_button.isEnabled())
        self.assertIn("Validated CUDA", self.window.settings_page.compute_backend.text())

    def start(self): QTest.mouseClick(self.page.generate_button, Qt.MouseButton.LeftButton)

    def test_selection_readiness_and_setting_limits_gate_generation(self):
        self.assertFalse(self.page.generate_button.isEnabled())
        self.ready()
        self.page.width.setValue(2048); self.page.height.setValue(2048)
        self.assertFalse(self.page.generate_button.isEnabled())
        self.assertEqual(self.page.width.value(), 2048)
        self.page.width.setValue(512); self.page.height.setValue(512)
        self.assertTrue(self.page.generate_button.isEnabled())
        self.models.checkpoint.setText(str(self.root / "another.safetensors"))
        self.assertFalse(self.page.generate_button.isEnabled())
        self.assertIsNone(self.window.generation_controller.ready)

    def test_success_previews_validated_output_after_worker_cleanup(self):
        self.ready(); self.start(); wait_until(lambda: not self.window.tasks.busy)
        controller = self.window.generation_controller
        self.assertIsNotNone(controller.last_outcome)
        self.assertEqual(self.page.preview.image_info.path, self.output)
        self.assertEqual(self.page.preview.canvas.original.width(), 512)
        self.assertTrue(self.page.preview.save_action.isEnabled())
        self.assertFalse(self.page.cancel_button.isEnabled())
        self.assertTrue(self.page.generate_button.isEnabled())
        self.rig.backend.load_model.assert_called_once()
        self.rig.backend.unload.assert_called_once()
        passed = self.rig.backend.generate.call_args.args[0]
        self.assertEqual(passed.positive_prompt, "PRIVATE positive test")
        self.assertEqual(passed.negative_prompt, "PRIVATE negative test")
        self.assertEqual(passed.settings, GenerationSettings(512, 512, 20, 5.0, 12345))
        self.window.save_preferences()
        self.assertNotIn("PRIVATE", self.window.services.paths.settings_file.read_text())
        restored = self.window.services.settings.load()
        self.assertEqual(restored.model_path, str(self.checkpoint))
        self.assertEqual(restored.resource_manifest_path, str(self.manifest))

    def test_progress_is_real_steps_and_other_stages_are_indeterminate(self):
        entered, release = Event(), Event(); self.addCleanup(release.set)
        def generate(request, context):
            context.report_event(ProgressEvent(ProgressStage.GENERATING, 25, "SDXL sampling step 5 of 20"))
            entered.set(); release.wait(3)
            context.check_cancelled()
            return self.rig.backend.generate.return_value
        self.rig.backend.generate.side_effect = generate
        self.ready(); self.start()
        wait_until(lambda: entered.is_set() and self.page.progress_bar.value() == 25)
        self.assertEqual(self.page.progress_bar.maximum(), 100)
        self.window.generation_controller.progress(ProgressEvent(ProgressStage.DECODING, 0, "Decoding the image with the local VAE"))
        self.assertEqual(self.page.progress_bar.maximum(), 0)
        self.assertIn("VAE", self.page.inference_status.text())
        self.window.generation_controller.progress(ProgressEvent(ProgressStage.GENERATING, 100, "Waiting for local runtime work; native initialization may be slow"))
        self.assertIn("VAE", self.page.inference_status.text())
        self.assertEqual(self.page.progress_bar.maximum(), 0)
        release.set(); wait_until(lambda: not self.window.tasks.busy)

    def test_cancel_and_recovery_keep_gui_responsive_and_stop_conflicting_actions(self):
        entered = Event()
        def generate(request, context):
            entered.set()
            while True:
                context.check_cancelled(); Event().wait(0.005)
        self.rig.backend.generate.side_effect = generate
        self.ready(); self.start(); wait_until(entered.is_set)
        self.assertFalse(self.page.generate_button.isEnabled())
        self.assertFalse(self.models.validate_button.isEnabled())
        ticks = []; QTimer.singleShot(0, lambda: ticks.append(True)); wait_until(lambda: bool(ticks))
        self.start(); self.assertEqual(self.rig.backend.generate.call_count, 1)
        QTest.mouseClick(self.page.cancel_button, Qt.MouseButton.LeftButton)
        wait_until(lambda: not self.window.tasks.busy)
        self.assertIn("Cancelled", self.page.inference_status.text())
        self.assertTrue(self.page.generate_button.isEnabled())
        self.rig.backend.generate.side_effect = None
        self.start(); wait_until(lambda: not self.window.tasks.busy)
        self.assertIsNotNone(self.window.generation_controller.last_outcome)
        self.assertEqual(self.rig.backend.unload.call_count, 2)

    def test_missing_model_and_unsupported_hardware_do_not_enable_generate(self):
        self.models.checkpoint.setText(str(self.root / "missing.safetensors"))
        self.window.generation_controller.validate(); wait_until(lambda: not self.window.tasks.busy)
        self.assertFalse(self.page.generate_button.isEnabled())
        self.rig.detector.detect.assert_not_called()
        self.models.checkpoint.setText(str(self.checkpoint))
        self.rig.detector.detect.return_value = RuntimeCapabilities("test", "unit", devices=(RuntimeDevice(RuntimeKind.CPU, None, "CPU"),))
        self.window.generation_controller.validate(); wait_until(lambda: not self.window.tasks.busy)
        self.assertFalse(self.page.generate_button.isEnabled())
        self.assertIn("runtime", self.models.status.text().lower())

    def test_corrupt_or_missing_output_never_becomes_successful_preview(self):
        self.ready(); self.output.write_bytes(b"corrupt fixture")
        self.start(); wait_until(lambda: not self.window.tasks.busy)
        self.assertIsNone(self.window.generation_controller.last_outcome)
        self.assertIsNone(self.page.preview.image_info)
        self.assertTrue(self.output.exists())
        self.assertIn("corrupt", self.page.inference_status.text())
        self.rig.backend.unload.assert_called_once()

    def test_export_preserves_full_resolution_original_bytes(self):
        self.ready(); self.start(); wait_until(lambda: not self.window.tasks.busy)
        target = self.root / "export.png"
        with patch("stoneglass.ui.generation_controller.QFileDialog.getSaveFileName", return_value=(str(target), "PNG")):
            self.page.preview.save_action.trigger()
        wait_until(lambda: not self.window.tasks.busy)
        self.assertEqual(hashlib.sha256(target.read_bytes()).digest(), hashlib.sha256(self.output.read_bytes()).digest())
        self.assertEqual(QImage(str(target)).width(), 512)
        self.assertTrue(self.output.exists())

    def test_cleanup_failure_disables_generation_until_validation_retries_cleanup(self):
        self.ready(); self.rig.backend.unload.side_effect = RuntimeError("PRIVATE failure")
        self.start(); wait_until(lambda: not self.window.tasks.busy)
        self.assertFalse(self.page.generate_button.isEnabled())
        self.assertNotIn("PRIVATE", self.page.inference_status.text())
        self.assertTrue(self.rig.service.requires_cleanup)
        self.rig.backend.unload.side_effect = None
        self.window.generation_controller.validate(); wait_until(lambda: not self.window.tasks.busy)
        self.assertTrue(self.page.generate_button.isEnabled())

    def test_runtime_loss_invalidates_readiness_until_revalidation(self):
        self.ready()
        self.rig.backend.load_model.side_effect = InferenceError(ErrorCode.RUNTIME_UNAVAILABLE, "Supported GPU is no longer available.")
        self.start(); wait_until(lambda: not self.window.tasks.busy)
        self.assertFalse(self.page.generate_button.isEnabled())
        self.assertIsNone(self.window.generation_controller.ready)
        self.assertFalse(self.rig.service.requires_cleanup)
        self.rig.backend.load_model.side_effect = None
        self.ready()

    def test_shutdown_during_generation_cancels_and_reaps_before_window_closes(self):
        entered = Event()
        def generate(request, context):
            entered.set()
            while True: context.check_cancelled(); Event().wait(0.005)
        self.rig.backend.generate.side_effect = generate
        self.ready(); self.start(); wait_until(entered.is_set)
        self.assertFalse(self.window.close())
        wait_until(lambda: not self.window.tasks.busy and not self.window.isVisible())
        self.assertFalse(self.rig.service.requires_cleanup)
        self.rig.backend.unload.assert_called_once()
