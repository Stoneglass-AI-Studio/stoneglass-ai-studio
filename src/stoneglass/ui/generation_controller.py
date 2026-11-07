# SPDX-License-Identifier: GPL-3.0-or-later
"""GUI-thread coordination over existing task/service contracts; no inference here."""
from pathlib import Path
from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtWidgets import QFileDialog, QWidget
from PySide6.QtGui import QShortcut, QKeySequence
from stoneglass.inference.contracts import ModelReadiness, ProgressEvent, ProgressStage
from stoneglass.inference.errors import ErrorCode, ErrorInfo
from stoneglass.inference.validation import validate_request
from stoneglass.infrastructure.inference_tasks import InferenceTasks
from stoneglass.infrastructure.workers import TaskHandle, TaskManager, WorkerContext
from stoneglass.services.generation import GenerationOutcome
from stoneglass.services.images import export_png
from stoneglass.ui.generate_page import GeneratePage
from stoneglass.ui.models_page import ModelsPage


class GenerationController(QObject):
    status_message = Signal(str)
    selection_changed = Signal()
    completed = Signal(object)

    def __init__(self, tasks: InferenceTasks, manager: TaskManager,
                 generate: GeneratePage, models: ModelsPage, parent: QWidget) -> None:
        super().__init__(parent)
        self.tasks, self.manager, self.page, self.models = tasks, manager, generate, models
        self.ready: ModelReadiness | None = None
        self.active: TaskHandle | None = None
        self.last_outcome: GenerationOutcome | None = None
        self._validating = False
        self._last_progress: ProgressEvent | None = None
        models.selection_changed.connect(self.invalidate)
        models.validate_requested.connect(self.validate)
        models.cancel_requested.connect(self.cancel)
        generate.generate_button.clicked.connect(self.generate)
        generate.cancel_button.clicked.connect(self.cancel)
        generate.preferences_changed.connect(self.refresh)
        generate.positive_prompt.textChanged.connect(self.refresh)
        generate.negative_prompt.textChanged.connect(self.refresh)
        generate.preview.export_requested.connect(self.save)
        self.cancel_shortcut = QShortcut(QKeySequence("Escape"), parent)
        self.cancel_shortcut.activated.connect(self.cancel)
        self._exporting = False
        self.refresh()

    @Slot()
    def invalidate(self) -> None:
        self.ready = None
        self.models.status.setText("Selection changed. Validate the checkpoint and matching local resources.")
        self.selection_changed.emit()
        self.refresh()

    @Slot()
    def refresh(self) -> None:
        busy = self.active is not None
        reason = "Select and validate a supported local checkpoint and matching manifest."
        allowed = self.ready is not None and not busy and not self.tasks.service.requires_cleanup
        if allowed:
            try:
                request = self.page.generation_request(self.ready.model.model_id)
                validate_request(request, self.ready.model)
                if request.settings.width * request.settings.height > 1024 * 1024:
                    raise ValueError("This SDXL profile supports at most 1,048,576 pixels at batch one.")
            except Exception as exc:
                reason, allowed = str(exc), False
        if self.ready is not None:
            self.page.model_status.setText(f"{self.ready.model.path.name} · {self.ready.runtime.name}")
            if allowed: reason = "Generate locally using the validated SDXL profile."
        else: self.page.model_status.setText("Select and validate a local model in Models.")
        self.page.generate_button.setEnabled(allowed)
        self.page.generate_button.setToolTip(reason)
        self.page.cancel_button.setEnabled(busy)
        self.models.cancel_button.setEnabled(busy)
        self.models.validate_button.setEnabled(not busy and bool(self.models.checkpoint.text()) and bool(self.models.manifest.text()))
        self.models.checkpoint.setEnabled(not busy); self.models.manifest.setEnabled(not busy)
        # Browse buttons live alongside the two fields. Freeze selection during an operation.
        for button in self.models.findChildren(type(self.models.validate_button)):
            if button.text() == "Browse…": button.setEnabled(not busy)
        self.page.select_model_button.setEnabled(not busy)
        self.page.preview.save_action.setEnabled(not busy and not self._exporting and self.page.preview.image_info is not None)

    def _watch(self, handle: TaskHandle, validating: bool) -> None:
        self.active, self._validating = handle, validating
        self._last_progress = None
        handle.progress_event.connect(self.progress)
        handle.failed.connect(self.failed)
        handle.error.connect(self.typed_error)
        handle.cancelled.connect(self.cancelled)
        handle.succeeded.connect(self.validated if validating else self.succeeded)
        handle.finished.connect(self.finished)
        self.page.progress_bar.setRange(0, 0); self.page.progress_bar.show()
        self.refresh()

    @Slot()
    def validate(self) -> None:
        if self.active is not None: return
        self.ready = None
        try:
            self._watch(self.tasks.validate_selection(self.models.selection()), True)
            self.models.status.setText("Validating local resources and the installed GPU runtime…")
        except Exception as exc: self.failed(str(exc)); self.refresh()

    @Slot(object)
    def validated(self, ready: ModelReadiness) -> None:
        self.ready = ready
        message = f"Validated: {ready.model.path.name} · {ready.runtime.name}. Ready for local generation."
        self.models.status.setText(message)
        self.page.inference_status.setText(message)
        self.status_message.emit("Local model and runtime validated")

    @Slot()
    def generate(self) -> None:
        if self.active is not None or self.ready is None or not self.page.generate_button.isEnabled(): return
        self.page.inference_status.setText("Starting the local generation task…")
        try:
            self._watch(self.tasks.generate_once(self.ready, self.page.generation_request(self.ready.model.model_id)), False)
        except Exception as exc: self.failed(str(exc)); self.refresh()

    @Slot(object)
    def progress(self, event: ProgressEvent) -> None:
        # The transport's generic keepalive must not replace a known sampling,
        # decode or save phase with an initialization message during a slow call.
        previous = self._last_progress
        if event.message.startswith("Waiting for local runtime work"):
            if previous is not None and (previous.stage in (ProgressStage.DECODING, ProgressStage.SAVING)
                    or previous.message.startswith("SDXL sampling step")):
                event = ProgressEvent(previous.stage, previous.percent, previous.message + " · Still working locally")
        else:
            self._last_progress = event
        if event.stage is ProgressStage.GENERATING and event.message.startswith("SDXL sampling step"):
            self.page.progress_bar.setRange(0, 100); self.page.progress_bar.setValue(event.percent)
        else: self.page.progress_bar.setRange(0, 0)
        self.page.inference_status.setText(event.message)
        if self._validating: self.models.status.setText(event.message)
        self.status_message.emit(event.message)

    @Slot(object)
    def succeeded(self, outcome: GenerationOutcome) -> None:
        try:
            self.page.preview.show_outcome(outcome)
        except (OSError, ValueError) as exc:
            self.failed(str(exc)); return
        self.last_outcome = outcome
        self.page.inference_status.setText("Generation complete · Image validated and worker closed.")
        self.status_message.emit("Generation complete · PNG saved locally")
        self.completed.emit(outcome)

    @Slot(str)
    def failed(self, message: str) -> None:
        self.page.inference_status.setText(message)
        self.models.status.setText(message + " Validate again to recheck resources or retry cleanup.")
        self.status_message.emit(message)
        if self._validating or self.tasks.service.requires_cleanup: self.ready = None

    @Slot(object)
    def typed_error(self, info: ErrorInfo) -> None:
        if info.code in {ErrorCode.INVALID_RESOURCES, ErrorCode.RUNTIME_UNAVAILABLE,
                         ErrorCode.BACKEND_UNAVAILABLE, ErrorCode.NOT_READY,
                         ErrorCode.LOAD_FAILED, ErrorCode.WORKER_FAILED, ErrorCode.OFFLINE_POLICY}:
            self.ready = None

    @Slot()
    def cancel(self) -> None:
        if self.active is not None:
            self.active.cancel()
            self.page.inference_status.setText("Cancelling · Waiting for owned worker cleanup…")
            self.page.cancel_button.setEnabled(False); self.models.cancel_button.setEnabled(False)

    @Slot()
    def cancelled(self) -> None:
        self.page.inference_status.setText("Cancelled · Worker stopped. You can try again.")
        if self._validating: self.models.status.setText("Validation cancelled. Select Validate model to retry.")
        self.status_message.emit("Inference task cancelled")

    @Slot()
    def finished(self) -> None:
        self.active = None
        self.page.progress_bar.hide()
        self.refresh()

    @Slot()
    def save(self) -> None:
        info = self.page.preview.image_info
        if info is None or self.active is not None or self._exporting: return
        filename, _ = QFileDialog.getSaveFileName(self.page, "Save full-resolution PNG", info.path.name, "PNG images (*.png)")
        if not filename: return
        destination = Path(filename)
        if not destination.suffix: destination = destination.with_suffix(".png")
        self.page.preview.save_action.setEnabled(False)
        self._exporting = True
        def copy(context: WorkerContext) -> Path:
            context.check_cancelled()
            return export_png(info, destination, overwrite=True)
        handle = self.manager.start("image-export", copy)
        handle.succeeded.connect(lambda path: self.status_message.emit(f"PNG saved: {path}"))
        handle.failed.connect(lambda message: self.status_message.emit(f"PNG export failed: {message}"))
        handle.finished.connect(self._export_finished)

    @Slot()
    def _export_finished(self) -> None:
        self._exporting = False
        self.refresh()
