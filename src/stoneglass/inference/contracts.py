# SPDX-License-Identifier: GPL-3.0-or-later

"""Backend boundary, independent of Qt, PyTorch, and Diffusers."""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from stoneglass.domain.settings import GenerationSettings


@dataclass(frozen=True)
class GenerationRequest:
    positive_prompt: str
    negative_prompt: str
    settings: GenerationSettings


@dataclass(frozen=True)
class GenerationResult:
    image_path: Path
    seed: int


class TaskCancelled(Exception):
    """Raised when cooperative cancellation was requested."""


class TaskContext(Protocol):
    def check_cancelled(self) -> None: ...

    def report_progress(self, percent: int, message: str) -> None: ...


class InferenceBackend(Protocol):
    """A future adapter owns its pipeline and executes in a background worker.

    Implementations must check cancellation between stages and on inference
    callbacks. Model validation and backend selection are deferred to Phase 2.
    """

    def load_model(self, model_path: Path, context: TaskContext) -> None: ...

    def generate(
        self, request: GenerationRequest, context: TaskContext
    ) -> GenerationResult: ...

    def unload(self) -> None: ...
