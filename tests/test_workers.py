# SPDX-License-Identifier: GPL-3.0-or-later

import unittest
from threading import Event, get_ident

from PySide6.QtCore import QObject, QTimer, Slot

from qt_support import APP, wait_until
from stoneglass.infrastructure.workers import TaskManager, WorkerContext


class Receiver(QObject):
    def __init__(self) -> None:
        super().__init__()
        self.results: list[tuple[object, int]] = []

    @Slot(object)
    def receive(self, value: object) -> None:
        self.results.append((value, get_ident()))


class WorkerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = TaskManager()

    def tearDown(self) -> None:
        self.manager.cancel_all()
        wait_until(lambda: not self.manager.busy)
        self.manager.deleteLater()
        APP.processEvents()

    def test_task_runs_off_gui_thread_and_delivers_result_on_gui_thread(self) -> None:
        gui_thread = get_ident()
        receiver = Receiver()
        progress: list[tuple[int, str]] = []

        def operation(context: WorkerContext) -> int:
            context.report_progress(50, "Working")
            return get_ident()

        handle = self.manager.start("thread-test", operation)
        handle.succeeded.connect(receiver.receive)
        handle.progress.connect(lambda percent, message: progress.append((percent, message)))
        wait_until(lambda: not self.manager.busy)
        self.assertEqual(len(receiver.results), 1)
        self.assertNotEqual(receiver.results[0][0], gui_thread)
        self.assertEqual(receiver.results[0][1], gui_thread)
        self.assertEqual(progress, [(50, "Working")])

    def test_worker_errors_are_signalled_and_logged(self) -> None:
        errors: list[str] = []

        def fail(context: WorkerContext) -> None:
            raise RuntimeError("Test failure")

        with self.assertLogs("stoneglass.infrastructure.workers", level="ERROR"):
            handle = self.manager.start("error-test", fail)
            handle.failed.connect(errors.append)
            wait_until(lambda: not self.manager.busy)
        self.assertEqual(errors, ["RuntimeError: Test failure"])

    def test_cooperative_cancellation_keeps_gui_responsive(self) -> None:
        started = Event()
        release = Event()
        cancelled: list[bool] = []
        ticks: list[bool] = []

        def operation(context: WorkerContext) -> None:
            started.set()
            release.wait(timeout=2)
            context.check_cancelled()

        handle = self.manager.start("cancel-test", operation)
        handle.cancelled.connect(lambda: cancelled.append(True))
        wait_until(started.is_set)
        QTimer.singleShot(0, lambda: ticks.append(True))
        wait_until(lambda: bool(ticks))
        self.assertTrue(self.manager.busy)
        handle.cancel()
        release.set()
        wait_until(lambda: not self.manager.busy)
        self.assertEqual(cancelled, [True])
