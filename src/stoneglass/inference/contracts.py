# SPDX-License-Identifier: GPL-3.0-or-later

"""Backend boundary, independent of Qt, PyTorch, and Diffusers."""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Protocol, runtime_checkable

from stoneglass.domain.settings import GenerationSettings
from stoneglass.inference.errors import ErrorInfo


class RuntimeKind(str, Enum):
    ROCM = "rocm"
    CUDA = "cuda"
    CPU = "cpu"


@dataclass(frozen=True)
class RuntimeDevice:
    kind: RuntimeKind
    index: int | None
    name: str

    @property
    def torch_device(self) -> str:
        # PyTorch intentionally exposes HIP devices through its CUDA API.
        return "cpu" if self.kind is RuntimeKind.CPU else f"cuda:{self.index}"


@dataclass(frozen=True)
class RuntimeCapabilities:
    platform: str
    torch_version: str | None = None
    hip_version: str | None = None
    cuda_version: str | None = None
    devices: tuple[RuntimeDevice, ...] = ()
    diagnostics: tuple[str, ...] = ()


@dataclass(frozen=True)
class RuntimeRequest:
    """None means automatic GPU selection; CPU fallback is explicitly opt-in."""

    kind: RuntimeKind | None = None
    device_index: int | None = None
    allow_cpu_fallback: bool = False


class ModelVariant(str, Enum):
    BASE = "base"
    LCM = "lcm"


@dataclass(frozen=True)
class ModelSpec:
    model_id: str
    path: Path
    # Architecture identifiers are extensible; LCM is a variant, not a family.
    architecture: str = "sdxl"
    variant: ModelVariant = ModelVariant.BASE
    adapters: tuple[Path, ...] = ()
    resource_manifest: Path | None = None


class ProgressStage(str, Enum):
    RUNTIME = "runtime"
    VALIDATING = "validating"
    LOADING = "loading"
    GENERATING = "generating"
    DECODING = "decoding"
    SAVING = "saving"
    UNLOADING = "unloading"


@dataclass(frozen=True)
class ProgressEvent:
    """Percent is relative to this stage, not a fabricated overall estimate."""

    stage: ProgressStage
    percent: int
    message: str

    def __post_init__(self) -> None:
        if type(self.percent) is not int or not 0 <= self.percent <= 100:
            raise ValueError("Progress must be an integer from 0 to 100.")


@dataclass(frozen=True)
class GenerationRequest:
    positive_prompt: str = field(repr=False)
    negative_prompt: str = field(repr=False)
    settings: GenerationSettings
    model_id: str | None = None


@dataclass(frozen=True)
class GenerationResult:
    image_path: Path
    seed: int
    width: int
    height: int
    model_id: str


class TaskCancelled(Exception):
    """Raised when cooperative cancellation was requested."""


class TaskContext(Protocol):
    def check_cancelled(self) -> None: ...

    def report_progress(self, percent: int, message: str) -> None: ...


class InferenceContext(TaskContext, Protocol):
    def report_event(self, event: ProgressEvent) -> None: ...


@dataclass(frozen=True)
class BackendCapabilities:
    backend_id: str
    architectures: frozenset[str]
    variants: frozenset[ModelVariant]
    runtimes: frozenset[RuntimeKind]
    generation_available: bool = False


class InferenceBackend(Protocol):
    """Local-only adapter. No production implementation ships in Phase 2A.

    Own pipeline references and temporary files, use explicit devices on every
    worker call, check cancellation between stages/steps, and prohibit downloads.
    unload must be retryable, idempotent, and independent of cancellation.
    Successful results refer to atomically completed local image files; the
    adapter owns failure/cancellation cleanup of its temporary output.
    """

    def load_model(
        self, model: ModelSpec, runtime: RuntimeDevice, context: InferenceContext,
    ) -> None: ...

    def generate(
        self, request: GenerationRequest, context: InferenceContext,
    ) -> GenerationResult: ...

    def unload(self) -> None: ...


class BackendProvider(Protocol):
    @property
    def capabilities(self) -> BackendCapabilities: ...

    def create(self) -> InferenceBackend:
        """Construct without allocating models; allocations belong in load_model."""
        ...


@runtime_checkable
class ResourceValidatingProvider(Protocol):
    def validate_resources(self, model: ModelSpec, context: InferenceContext) -> None: ...


@runtime_checkable
class ResultCommitter(Protocol):
    def commit_result(self, result: GenerationResult) -> None:
        """Commit owned pending output after the service's final cancellation check."""
        ...


class RuntimeDetector(Protocol):
    def detect(self, context: InferenceContext) -> RuntimeCapabilities: ...


class InferenceState(str, Enum):
    EMPTY = "empty"
    LOADING = "loading"
    READY = "ready"
    GENERATING = "generating"
    UNLOADING = "unloading"
    FAILED = "failed"
    CLOSED = "closed"


@dataclass(frozen=True)
class InferenceStatus:
    state: InferenceState = InferenceState.EMPTY
    model: ModelSpec | None = None
    runtime: RuntimeDevice | None = None
    can_generate: bool = False
    error: ErrorInfo | None = None


@dataclass(frozen=True)
class ModelReadiness:
    """Validated local references and runtime; no loaded pipeline is implied."""
    model: ModelSpec
    runtime: RuntimeDevice
    backend_id: str
