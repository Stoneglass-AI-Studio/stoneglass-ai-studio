# SPDX-License-Identifier: GPL-3.0-or-later
"""One generation transaction over the existing inference service, then terminate."""
from dataclasses import dataclass
from typing import Any
from stoneglass.inference.contracts import GenerationRequest, GenerationResult, InferenceContext, ModelReadiness, ProgressEvent, RuntimeRequest, TaskCancelled
from stoneglass.services.images import ImageInfo, validate_png
from stoneglass.services.inference import InferenceService


@dataclass(frozen=True)
class GenerationOutcome:
    result: GenerationResult
    image: ImageInfo
    diagnostics: dict[str, Any]


class CleanupContext:
    def __init__(self, context: InferenceContext) -> None: self.context = context
    def check_cancelled(self) -> None: pass
    def report_progress(self, percent: int, message: str) -> None:
        try: self.context.report_progress(percent, message)
        except TaskCancelled: pass
    def report_event(self, event: ProgressEvent) -> None:
        try: self.context.report_event(event)
        except TaskCancelled: pass


def generate_once(service: InferenceService, ready: ModelReadiness, request: GenerationRequest, context: InferenceContext) -> GenerationOutcome:
    cleanup = CleanupContext(context)
    try:
        service.load_model(ready.model, RuntimeRequest(ready.runtime.kind, ready.runtime.index), context)
        result = service.generate(request, context)
        # The production committer has already validated its pending PNG. Check
        # the committed file again; cancellation after commit preserves success.
        image = validate_png(result.image_path, result.width, result.height)
        diagnostics = service.diagnostics(cleanup)
        outcome = GenerationOutcome(result, image, diagnostics)
    finally:
        service.unload(cleanup)
    return outcome
