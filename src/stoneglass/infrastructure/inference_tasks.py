# SPDX-License-Identifier: GPL-3.0-or-later

"""GUI-thread adapter to the existing worker manager, not a second thread pool."""

from collections.abc import Callable

from PySide6.QtCore import QObject, Signal, Slot

from stoneglass.inference.contracts import GenerationRequest, InferenceContext, ModelSpec, RuntimeRequest, ModelReadiness
from stoneglass.inference.errors import ErrorCode, InferenceError
from stoneglass.infrastructure.workers import TaskHandle, TaskManager
from stoneglass.services.inference import InferenceService


class InferenceTasks(QObject):
    """Submit from the GUI thread. Every expensive service call runs in a worker.

    The returned handle carries results, typed errors/events, readable failures
    and cancellation. The UI submits readiness and one-shot generation through
    this adapter. Cleanup jobs cannot be skipped by generic cancellation checks.
    """

    status_changed = Signal(object)

    def __init__(
        self, service: InferenceService, manager: TaskManager, parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self._manager = manager
        self._active: TaskHandle | None = None

    def _start(self, name: str, operation: Callable[[InferenceContext], object]) -> TaskHandle:
        if self._active is not None:
            raise InferenceError(ErrorCode.BUSY, "An inference task is already running.")
        self._active = self._manager.start(name, operation, check_cancellation=False)
        self._active.finished.connect(self._finished)
        return self._active

    @Slot()
    def _finished(self) -> None:
        self._active = None
        self.status_changed.emit(self.service.status)

    def detect_runtimes(self) -> TaskHandle:
        return self._start("inference-runtime-check", self.service.detect_runtimes)

    def load_model(self, model: ModelSpec, runtime: RuntimeRequest = RuntimeRequest()) -> TaskHandle:
        return self._start("inference-model-load", lambda context: self.service.load_model(model, runtime, context))

    def generate(self, request: GenerationRequest) -> TaskHandle:
        return self._start("inference-generation", lambda context: self.service.generate(request, context))

    def validate_selection(self, model: ModelSpec) -> TaskHandle:
        def validate(context: InferenceContext) -> ModelReadiness:
            if self.service.requires_cleanup:
                self.service.unload(context)
            return self.service.validate_selection(model, context)
        return self._start("inference-readiness", validate)

    def generate_once(self, ready: ModelReadiness, request: GenerationRequest) -> TaskHandle:
        from stoneglass.services.generation import generate_once
        return self._start("inference-generation-once", lambda context: generate_once(self.service, ready, request, context))

    def unload(self) -> TaskHandle:
        return self._start("inference-model-unload", self.service.unload)

    def shutdown(self) -> TaskHandle:
        return self._start("inference-shutdown", self.service.close)
