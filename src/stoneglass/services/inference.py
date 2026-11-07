# SPDX-License-Identifier: GPL-3.0-or-later

"""Serialized model ownership and inference orchestration, independent of Qt."""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from threading import Lock
from typing import Any, NoReturn

from stoneglass.inference.contracts import (
    BackendCapabilities, BackendProvider, GenerationRequest, GenerationResult,
    InferenceBackend, InferenceContext, InferenceState, InferenceStatus, ModelSpec,
    ProgressEvent, ProgressStage, RuntimeCapabilities, RuntimeDetector, RuntimeDevice,
    RuntimeRequest, TaskCancelled,
    ResourceValidatingProvider, ResultCommitter,
    ModelReadiness,
)
from stoneglass.inference.errors import ErrorCode, ErrorInfo, InferenceError
from stoneglass.inference.runtime import TorchRuntimeDetector, select_runtime
from stoneglass.inference.validation import validate_model, validate_request

logger = logging.getLogger(__name__)


class InferenceService:
    """One owned pipeline; overlapping operations fail fast rather than queue.

    All expensive methods are synchronous worker operations. The Qt adapter
    supplies background execution; this service never imports Qt. The default
    provider registry is empty, so no production generation is available.
    """

    def __init__(
        self, providers: tuple[BackendProvider, ...] = (), detector: RuntimeDetector | None = None,
    ) -> None:
        self._providers = tuple(providers)
        self._detector = detector if detector is not None else TorchRuntimeDetector()
        self._operation_lock = Lock()
        self._status_lock = Lock()
        self._status = InferenceStatus()
        self._backend: InferenceBackend | None = None
        self._capabilities: BackendCapabilities | None = None

    @property
    def status(self) -> InferenceStatus:
        with self._status_lock:
            return self._status

    @property
    def requires_cleanup(self) -> bool:
        return self._backend is not None or getattr(self._detector, "requires_cleanup", False) is True

    @contextmanager
    def _operation(self, *, allow_closed: bool = False) -> Iterator[None]:
        if not self._operation_lock.acquire(blocking=False):
            raise InferenceError(ErrorCode.BUSY, "An inference operation is already running.")
        try:
            if self.status.state is InferenceState.CLOSED and not allow_closed:
                raise InferenceError(ErrorCode.CLOSED, "The inference service has been closed.")
            yield
        finally:
            self._operation_lock.release()

    def _set_status(self, status: InferenceStatus) -> None:
        with self._status_lock:
            self._status = status

    def detect_runtimes(self, context: InferenceContext) -> RuntimeCapabilities:
        with self._operation():
            return self._detector.detect(context)

    def validate_selection(self, model: ModelSpec, context: InferenceContext) -> ModelReadiness:
        """Validate references/profile and probe runtime without loading weights."""
        with self._operation():
            model = validate_model(model)
            provider, device = self._select(model, RuntimeRequest(), context)
            if not provider.capabilities.generation_available:
                raise InferenceError(ErrorCode.BACKEND_UNAVAILABLE, "Generation is unavailable for this backend.")
            context.check_cancelled()
            return ModelReadiness(model, device, provider.capabilities.backend_id)

    def diagnostics(self, context: InferenceContext) -> dict[str, Any]:
        with self._operation():
            method = getattr(self._backend, "diagnostics", None)
            return method(context) if callable(method) else {}

    def _select(
        self, model: ModelSpec, request: RuntimeRequest, context: InferenceContext,
    ) -> tuple[BackendProvider, RuntimeDevice]:
        providers = [p for p in self._providers if model.architecture in p.capabilities.architectures
                     and model.variant in p.capabilities.variants]
        if not providers:
            raise InferenceError(
                ErrorCode.BACKEND_UNAVAILABLE, "No local backend implements this model architecture and variant."
            )
        for provider in providers:
            if isinstance(provider, ResourceValidatingProvider):
                provider.validate_resources(model, context)
        report = self._detector.detect(context)
        # Prefer GPU across all matching providers before considering CPU fallback.
        pairs: list[tuple[BackendProvider, RuntimeDevice]] = []
        for provider in providers:
            try:
                device = select_runtime(report, request, provider.capabilities.runtimes)
                pairs.append((provider, device))
            except InferenceError as exc:
                if exc.info.code is not ErrorCode.RUNTIME_UNAVAILABLE:
                    raise
        if not pairs:
            raise InferenceError(
                ErrorCode.RUNTIME_UNAVAILABLE, "No validated runtime supports this model and runtime selection."
            )
        pairs.sort(key=lambda pair: pair[1].kind.value == "cpu")
        return pairs[0]

    def load_model(
        self, model: ModelSpec, runtime: RuntimeRequest, context: InferenceContext,
    ) -> InferenceStatus:
        with self._operation():
            if self.status.state is InferenceState.FAILED:
                raise InferenceError(ErrorCode.CLEANUP_FAILED, "Retry unloading before loading another model.")
            context.report_event(ProgressEvent(ProgressStage.VALIDATING, 0, "Validating local model references"))
            model = validate_model(model)
            provider, device = self._select(model, runtime, context)
            context.check_cancelled()
            if self.status.model == model and self.status.runtime == device:
                return self.status
            # Validate the replacement before releasing an existing model. No
            # automatic restoration/download is attempted if replacement fails.
            self._cleanup(context)
            context.check_cancelled()
            try:
                self._backend = provider.create()
                self._capabilities = provider.capabilities
                self._set_status(InferenceStatus(InferenceState.LOADING, model, device))
                context.report_event(ProgressEvent(ProgressStage.LOADING, 0, "Loading local model"))
                self._backend.load_model(model, device, context)
                context.check_cancelled()
                context.report_event(ProgressEvent(ProgressStage.LOADING, 100, "Local model loaded"))
            except TaskCancelled:
                self._cleanup(context)
                raise
            except Exception as exc:
                self._fail(ErrorCode.LOAD_FAILED, "Local model loading failed.", exc, context)
            self._set_status(replace(self.status, state=InferenceState.READY,
                                     can_generate=self._capabilities.generation_available))
            return self.status

    def generate(self, request: GenerationRequest, context: InferenceContext) -> GenerationResult:
        with self._operation():
            status = self.status
            if status.state is not InferenceState.READY or self._backend is None or status.model is None:
                raise InferenceError(ErrorCode.NOT_READY, "Load a compatible local model before generating.")
            if not status.can_generate:
                raise InferenceError(ErrorCode.BACKEND_UNAVAILABLE, "This backend does not implement image generation.")
            validate_request(request, status.model)
            context.check_cancelled()
            self._set_status(replace(status, state=InferenceState.GENERATING, can_generate=False))
            try:
                context.report_event(ProgressEvent(ProgressStage.GENERATING, 0, "Starting local inference"))
                result = self._backend.generate(request, context)
                context.check_cancelled()
                if not self._valid_result(result, request, status.model):
                    raise ValueError("Backend returned an invalid result.")
                context.report_event(ProgressEvent(ProgressStage.GENERATING, 100, "Local inference completed"))
                context.check_cancelled()
                if isinstance(self._backend, ResultCommitter):
                    self._backend.commit_result(result)
            except TaskCancelled:
                self._cleanup(context)
                raise
            except Exception as exc:
                self._fail(ErrorCode.GENERATION_FAILED, "Local image generation failed.", exc, context)
            self._set_status(status)
            return result

    @staticmethod
    def _valid_result(result: GenerationResult, request: GenerationRequest, model: ModelSpec) -> bool:
        # File encoding, atomic persistence and output ownership belong to the
        # adapter. Do not delete paths supplied by an adapter on its behalf.
        return (
            isinstance(result, GenerationResult) and isinstance(result.image_path, Path)
            and result.image_path.is_absolute() and not str(result.image_path).startswith(("\\\\", "//"))
            and type(result.seed) is int and 0 <= result.seed <= 2_147_483_647
            and (request.settings.seed == -1 or result.seed == request.settings.seed)
            and result.width == request.settings.width and result.height == request.settings.height
            and result.model_id == model.model_id
        )

    def _cleanup(self, context: InferenceContext) -> None:
        if getattr(self._detector, "requires_cleanup", False) is True:
            try:
                self._detector.close()
            except Exception:
                self._set_status(replace(self.status, state=InferenceState.FAILED))
                raise InferenceError(ErrorCode.CLEANUP_FAILED, "Runtime worker cleanup failed. Retry validation or closing the window.") from None
        if self._backend is None:
            self._set_status(InferenceStatus())
            return
        self._set_status(replace(self.status, state=InferenceState.UNLOADING, can_generate=False))
        try:
            # Cancellation and observer errors must never prevent resource release.
            try:
                context.report_event(ProgressEvent(ProgressStage.UNLOADING, 0, "Releasing model resources"))
            except Exception:
                pass
            self._backend.unload()
        except Exception as exc:
            info = ErrorInfo(ErrorCode.CLEANUP_FAILED, "Model cleanup failed. Retry unloading before continuing.")
            self._set_status(replace(self.status, state=InferenceState.FAILED, error=info))
            logger.error("Model cleanup failed (%s)", type(exc).__name__)
            # Retain ownership so a later unload/close can retry safely.
            raise InferenceError(info.code, info.message) from None
        self._backend = None
        self._capabilities = None
        self._set_status(InferenceStatus())

    def _fail(
        self, code: ErrorCode, message: str, exception: Exception, context: InferenceContext,
    ) -> NoReturn:
        logger.error("Inference operation failed [%s] (%s)", code.value, type(exception).__name__)
        # Only the project's typed boundary errors carry display-safe messages.
        # Preserve actionable preflight/isolation failures; redact arbitrary errors.
        if isinstance(exception, InferenceError):
            code, message = exception.info.code, exception.info.message
        self._cleanup(context)
        self._set_status(replace(self.status, error=ErrorInfo(code, message)))
        # Adapter exception strings/tracebacks may contain prompts. Do not chain
        # them into the generic worker's logging and user-error presentation.
        raise InferenceError(code, message) from None

    def unload(self, context: InferenceContext) -> InferenceStatus:
        with self._operation(allow_closed=True):
            if self.status.state is InferenceState.CLOSED:
                return self.status
            self._cleanup(context)
            return self.status

    def close(self, context: InferenceContext) -> InferenceStatus:
        with self._operation(allow_closed=True):
            if self.status.state is InferenceState.CLOSED:
                return self.status
            self._cleanup(context)
            self._set_status(InferenceStatus(InferenceState.CLOSED))
            return self.status
