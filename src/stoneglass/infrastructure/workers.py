# SPDX-License-Identifier: GPL-3.0-or-later

"""Owned Qt worker threads with results, progress, and cooperative cancellation."""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from threading import Event
from typing import Any
from uuid import uuid4

from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot

from stoneglass.inference.contracts import TaskCancelled

logger = logging.getLogger(__name__)


class WorkerContext:
    def __init__(self, cancel: Event, progress: Callable[[int, str], None]) -> None:
        self._cancel = cancel
        self._progress = progress

    def check_cancelled(self) -> None:
        if self._cancel.is_set():
            raise TaskCancelled()

    def report_progress(self, percent: int, message: str) -> None:
        self.check_cancelled()
        self._progress(max(0, min(100, percent)), message)


class TaskHandle(QObject):
    succeeded = Signal(object)
    failed = Signal(str)
    cancelled = Signal()
    progress = Signal(int, str)
    finished = Signal()

    def __init__(self, cancellation: Event, parent: QObject) -> None:
        super().__init__(parent)
        self._cancellation = cancellation

    def cancel(self) -> None:
        self._cancellation.set()


class _TaskThread(QThread):
    succeeded = Signal(object)
    failed = Signal(str)
    cancelled = Signal()
    progress = Signal(int, str)
    def __init__(
        self, operation: Callable[[WorkerContext], Any], cancel: Event, parent: QObject,
    ) -> None:
        super().__init__(parent)
        self._operation = operation
        self._cancel = cancel

    def run(self) -> None:
        context = WorkerContext(self._cancel, self.progress.emit)
        try:
            context.check_cancelled()
            result = self._operation(context)
            context.check_cancelled()
            self.succeeded.emit(result)
        except TaskCancelled:
            self.cancelled.emit()
        except Exception as exc:
            logger.exception("Background operation failed")
            self.failed.emit(f"{type(exc).__name__}: {exc}")


@dataclass
class _Job:
    thread: _TaskThread
    handle: TaskHandle


class TaskManager(QObject):
    """Call start/cancel_all only from the GUI thread.

    Owns every thread until it finishes. Window shutdown is deferred until idle;
    workers are never terminated forcibly. Task functions must use bounded I/O
    and check their context between stages. Only signals cross into the UI.
    """

    idle = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._jobs: dict[str, _Job] = {}

    @property
    def busy(self) -> bool:
        return bool(self._jobs)

    def start(self, name: str, operation: Callable[[WorkerContext], Any]) -> TaskHandle:
        job_id = uuid4().hex
        cancellation = Event()
        handle = TaskHandle(cancellation, self)
        thread = _TaskThread(operation, cancellation, self)
        thread.setObjectName(name)
        thread.setProperty("job_id", job_id)
        thread.succeeded.connect(handle.succeeded, Qt.ConnectionType.QueuedConnection)
        thread.failed.connect(handle.failed, Qt.ConnectionType.QueuedConnection)
        thread.cancelled.connect(handle.cancelled, Qt.ConnectionType.QueuedConnection)
        thread.progress.connect(handle.progress, Qt.ConnectionType.QueuedConnection)
        thread.finished.connect(self._on_thread_finished)
        self._jobs[job_id] = _Job(thread, handle)
        thread.start()
        return handle

    def cancel_all(self) -> None:
        for job in self._jobs.values():
            job.handle.cancel()

    @Slot()
    def _on_thread_finished(self) -> None:
        thread = self.sender()
        if not isinstance(thread, QThread):
            return
        job = self._jobs.pop(str(thread.property("job_id")))
        job.handle.finished.emit()
        job.handle.deleteLater()
        thread.deleteLater()
        if not self._jobs:
            self.idle.emit()
