# SPDX-License-Identifier: GPL-3.0-or-later

"""Mock-only inference fixtures. No image generation or model files are created."""

from dataclasses import dataclass
from pathlib import Path
from threading import Event
from unittest.mock import Mock

from stoneglass.inference.contracts import (
    BackendCapabilities, BackendProvider, InferenceBackend, ModelSpec, ModelVariant,
    ProgressEvent, RuntimeCapabilities, RuntimeDetector, RuntimeDevice, RuntimeKind, TaskCancelled,
)
from stoneglass.services.inference import InferenceService


class Context:
    def __init__(self) -> None:
        self.cancel = Event()
        self.events: list[ProgressEvent] = []

    def check_cancelled(self) -> None:
        if self.cancel.is_set():
            raise TaskCancelled()

    def report_progress(self, percent: int, message: str) -> None:
        self.check_cancelled()

    def report_event(self, event: ProgressEvent) -> None:
        self.check_cancelled()
        self.events.append(event)


@dataclass
class Rig:
    service: InferenceService
    backend: Mock
    provider: Mock
    detector: Mock
    model: ModelSpec
    context: Context


def make_rig(path: Path) -> Rig:
    backend = Mock(spec=InferenceBackend)
    provider = Mock(spec=BackendProvider)
    provider.capabilities = BackendCapabilities(
        "unit-test-only", frozenset({"sdxl", "future-family"}),
        frozenset({ModelVariant.BASE, ModelVariant.LCM}),
        frozenset({RuntimeKind.CUDA, RuntimeKind.ROCM, RuntimeKind.CPU}), True,
    )
    provider.create.return_value = backend
    detector = Mock(spec=RuntimeDetector)
    detector.detect.return_value = RuntimeCapabilities(
        "test", "test-version", cuda_version="test-cuda",
        devices=(RuntimeDevice(RuntimeKind.CUDA, 0, "Mock GPU"), RuntimeDevice(RuntimeKind.CPU, None, "CPU")),
    )
    return Rig(InferenceService((provider,), detector), backend, provider, detector,
               ModelSpec("test-model", path), Context())
