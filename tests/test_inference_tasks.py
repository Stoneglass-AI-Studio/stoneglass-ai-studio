# SPDX-License-Identifier: GPL-3.0-or-later

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from threading import Event, get_ident

from PySide6.QtCore import QObject, QTimer, Slot

from inference_support import make_rig
from qt_support import APP, wait_until
from stoneglass.inference.contracts import InferenceState, InferenceStatus, ProgressEvent, ProgressStage, RuntimeRequest
from stoneglass.inference.errors import ErrorCode, InferenceError
from stoneglass.infrastructure.inference_tasks import InferenceTasks
from stoneglass.infrastructure.workers import TaskManager
from stoneglass.services.application import ApplicationServices
from stoneglass.services.paths import AppPaths
from stoneglass.ui.main_window import MainWindow


class Receiver(QObject):
    def __init__(self) -> None:
        super().__init__()
        self.values: list[tuple[object,int]] = []

    @Slot(object)
    def receive(self, value: object) -> None:
        self.values.append((value,get_ident()))


class InferenceTaskTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.rig = make_rig(Path(self.temporary.name))
        self.manager = TaskManager()
        self.adapter = InferenceTasks(self.rig.service, self.manager)

    def tearDown(self) -> None:
        self.manager.cancel_all()
        wait_until(lambda: not self.manager.busy)
        if self.rig.service.requires_cleanup:
            self.adapter.shutdown()
            wait_until(lambda: not self.manager.busy)
        self.adapter.deleteLater()
        self.manager.deleteLater()
        APP.processEvents()
        self.temporary.cleanup()

    def test_model_operation_and_typed_progress_cross_existing_worker_boundary(self) -> None:
        gui_thread = get_ident()
        worker_threads: list[int] = []
        def load(model, runtime, context):
            worker_threads.append(get_ident())
            context.report_event(ProgressEvent(ProgressStage.LOADING, 37, "Unit test progress"))
        self.rig.backend.load_model.side_effect = load
        results,events = Receiver(),Receiver()
        handle = self.adapter.load_model(self.rig.model)
        handle.succeeded.connect(results.receive)
        handle.progress_event.connect(events.receive)
        wait_until(lambda: not self.manager.busy)
        self.assertEqual(len(worker_threads), 1)
        self.assertNotEqual(worker_threads[0], gui_thread)
        self.assertEqual(results.values[0][1], gui_thread)
        self.assertEqual(results.values[0][0].state, InferenceState.READY)
        self.assertTrue(any(event.percent == 37 for event,thread in events.values))
        self.assertTrue(all(thread == gui_thread for event,thread in events.values))

    def test_overlapping_submissions_are_rejected_before_spawning_more_workers(self) -> None:
        handle = self.adapter.load_model(self.rig.model)
        with self.assertRaises(InferenceError) as caught:
            self.adapter.detect_runtimes()
        self.assertEqual(caught.exception.info.code, ErrorCode.BUSY)
        wait_until(lambda: not self.manager.busy)
        self.assertEqual(self.rig.provider.create.call_count, 1)

    def test_typed_failure_is_readable_and_does_not_log_adapter_prompts(self) -> None:
        self.rig.backend.load_model.side_effect = RuntimeError("PRIVATE_PROMPT_FROM_ADAPTER")
        errors = Receiver()
        failures: list[str] = []
        with self.assertLogs("stoneglass", level="ERROR") as logs:
            handle = self.adapter.load_model(self.rig.model)
            handle.error.connect(errors.receive)
            handle.failed.connect(failures.append)
            wait_until(lambda: not self.manager.busy)
        self.assertEqual(errors.values[0][0].code, ErrorCode.LOAD_FAILED)
        self.assertEqual(errors.values[0][1], get_ident())
        self.assertEqual(failures, ["Local model loading failed."])
        self.assertNotIn("PRIVATE", "\n".join(logs.output))

    def test_cleanup_remains_nonblocking_and_cannot_be_cancelled_away(self) -> None:
        self.adapter.load_model(self.rig.model)
        wait_until(lambda: not self.manager.busy)
        entered,release = Event(),Event()
        self.addCleanup(release.set)
        def unload():
            entered.set()
            if not release.wait(3):
                raise RuntimeError("Test barrier timed out.")
        self.rig.backend.unload.side_effect = unload
        results = Receiver()
        cancelled: list[bool] = []
        handle = self.adapter.shutdown()
        handle.succeeded.connect(results.receive)
        handle.cancelled.connect(lambda: cancelled.append(True))
        handle.cancel()
        try:
            wait_until(entered.is_set)
            ticks: list[bool] = []
            QTimer.singleShot(0, lambda: ticks.append(True))
            wait_until(lambda: bool(ticks))
            self.assertTrue(self.manager.busy)
        finally:
            release.set()
        wait_until(lambda: not self.manager.busy)
        self.assertEqual(cancelled, [])
        self.assertEqual(results.values[0][0].state, InferenceState.CLOSED)


class InferenceWindowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        paths = AppPaths(Path(self.temporary.name))
        paths.ensure()
        self.rig = make_rig(paths.root)
        services = replace(ApplicationServices.create(paths), inference=self.rig.service)
        self.window = MainWindow(services, start_hardware_scan=False)
        self.window.show()
        APP.processEvents()

    def tearDown(self) -> None:
        self.rig.backend.unload.side_effect = None
        self.window.tasks.cancel_all()
        wait_until(lambda: not self.window.tasks.busy)
        self.window.close()
        wait_until(lambda: not self.window.tasks.busy and not self.window.isVisible())
        self.window.deleteLater()
        APP.processEvents()
        self.temporary.cleanup()

    def test_request_snapshot_preserves_ui_and_never_enables_phase2a_generation(self) -> None:
        page = self.window.generate_page
        page.positive_prompt.setPlainText("PRIVATE_SESSION_PROMPT")
        page.negative_prompt.setPlainText("PRIVATE_SESSION_NEGATIVE")
        page.width.setValue(768)
        request = page.generation_request("chosen-model")
        self.assertEqual(request.positive_prompt, "PRIVATE_SESSION_PROMPT")
        self.assertEqual(request.settings.width, 768)
        self.assertEqual(request.model_id, "chosen-model")
        page.set_inference_status(InferenceStatus(InferenceState.READY, can_generate=True))
        self.assertFalse(page.generate_button.isEnabled())
        self.window.save_preferences()
        self.assertNotIn("PRIVATE_SESSION", self.window.services.paths.settings_file.read_text())
        self.assertEqual(page.positive_prompt.toPlainText(), request.positive_prompt)

    def test_close_defers_to_background_model_cleanup(self) -> None:
        self.rig.service.load_model(self.rig.model, RuntimeRequest(), self.rig.context)
        entered,release = Event(),Event()
        def unload():
            entered.set()
            if not release.wait(3):
                raise RuntimeError("Test barrier timed out.")
        self.rig.backend.unload.side_effect = unload
        self.assertFalse(self.window.close())
        try:
            wait_until(entered.is_set)
            ticks: list[bool] = []
            QTimer.singleShot(0, lambda: ticks.append(True))
            wait_until(lambda: bool(ticks))
            self.assertTrue(self.window.isVisible())
        finally:
            release.set()
        wait_until(lambda: not self.window.tasks.busy and not self.window.isVisible())
        self.assertEqual(self.rig.service.status.state, InferenceState.CLOSED)

    def test_failed_close_cleanup_keeps_window_open_for_retry_without_loop(self) -> None:
        self.rig.service.load_model(self.rig.model, RuntimeRequest(), self.rig.context)
        self.rig.backend.unload.side_effect = RuntimeError("PRIVATE_CLEANUP_ERROR")
        with self.assertLogs("stoneglass", level="ERROR"):
            self.assertFalse(self.window.close())
            wait_until(lambda: not self.window.tasks.busy)
        self.assertTrue(self.window.isVisible())
        self.assertTrue(self.window.centralWidget().isEnabled())
        self.assertEqual(self.rig.backend.unload.call_count, 1)
        self.assertIn("retry", self.window.statusBar().currentMessage())
        self.assertNotIn("PRIVATE", self.window.statusBar().currentMessage())
