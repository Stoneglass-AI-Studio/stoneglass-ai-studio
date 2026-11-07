# SPDX-License-Identifier: GPL-3.0-or-later

"""Bounded runtime probing and explicit selection; no optional imports in-process."""

import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from time import monotonic
from typing import Any

from stoneglass.inference.contracts import (
    InferenceContext, ProgressEvent, ProgressStage, RuntimeCapabilities, RuntimeDevice,
    RuntimeKind, RuntimeRequest, TaskCancelled,
)
from stoneglass.inference.errors import ErrorCode, InferenceError


def parse_capabilities(raw: str) -> RuntimeCapabilities:
    data = json.loads(raw)
    if not isinstance(data, dict) or data.get("schema") != 1:
        raise ValueError("Unknown probe response.")
    for key in ("torch_version", "hip_version", "cuda_version"):
        if data.get(key) is not None and not isinstance(data[key], str):
            raise ValueError("Invalid version field.")
    if not isinstance(data.get("platform"), str) or not isinstance(data.get("devices"), list):
        raise ValueError("Invalid probe response.")
    devices: list[RuntimeDevice] = []
    for item in data["devices"]:
        kind = RuntimeKind(item["kind"])
        index = item["index"]
        if item.get("validated") is not True or not isinstance(item["name"], str):
            raise ValueError("Unvalidated runtime device.")
        if kind is RuntimeKind.CPU:
            if index is not None:
                raise ValueError("Invalid CPU index.")
        elif type(index) is not int or not 0 <= index < 64:
            raise ValueError("Invalid GPU index.")
        if not data.get("torch_version") or (
            kind is RuntimeKind.ROCM and not data.get("hip_version")
        ) or (kind is RuntimeKind.CUDA and not data.get("cuda_version")):
            raise ValueError("Device does not match the PyTorch build.")
        if any(d.kind == kind and d.index == index for d in devices):
            raise ValueError("Duplicate runtime device.")
        devices.append(RuntimeDevice(kind, index, item["name"]))
    diagnostics = data.get("diagnostics", [])
    if not isinstance(diagnostics, list) or any(not isinstance(s, str) for s in diagnostics):
        raise ValueError("Invalid diagnostics.")
    return RuntimeCapabilities(
        data["platform"], data.get("torch_version"), data.get("hip_version"),
        data.get("cuda_version"), tuple(devices), tuple(diagnostics),
    )


class TorchRuntimeDetector:
    """Call from a worker. Probe cancellation kills only the owned child process.

    A successful device entry validates float32 arithmetic only. It does not
    establish model, precision, memory, operator or vendor support certification.
    """

    def __init__(
        self, process_factory: Callable[..., Any] = subprocess.Popen, *, timeout: float = 20,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if timeout <= 0:
            raise ValueError("Probe timeout must be positive.")
        self._process_factory = process_factory
        self._timeout = timeout
        self._clock = clock

    def detect(self, context: InferenceContext) -> RuntimeCapabilities:
        context.report_event(ProgressEvent(ProgressStage.RUNTIME, 0, "Checking installed PyTorch runtimes"))
        context.check_cancelled()
        process = None
        try:
            process = self._process_factory(
                [sys.executable, "-B", str(Path(__file__).with_name("_torch_probe.py"))],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
                errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            deadline = self._clock() + self._timeout
            while True:
                context.check_cancelled()
                remaining = deadline - self._clock()
                if remaining <= 0:
                    return RuntimeCapabilities(sys.platform, diagnostics=("probe_timeout",))
                try:
                    stdout, _ = process.communicate(timeout=min(0.1, remaining))
                    break
                except subprocess.TimeoutExpired:
                    continue
            context.check_cancelled()
            if process.returncode != 0:
                return RuntimeCapabilities(sys.platform, diagnostics=("probe_failed",))
            result = parse_capabilities(stdout)
            context.report_event(ProgressEvent(ProgressStage.RUNTIME, 100, "Runtime check completed"))
            return result
        except TaskCancelled:
            raise
        except (OSError, ValueError, TypeError, KeyError):
            return RuntimeCapabilities(sys.platform, diagnostics=("probe_failed",))
        finally:
            if process is not None and process.poll() is None:
                process.kill()
                process.communicate(timeout=2)


def select_runtime(
    capabilities: RuntimeCapabilities, request: RuntimeRequest, supported: frozenset[RuntimeKind],
) -> RuntimeDevice:
    if request.kind is not None and not isinstance(request.kind, RuntimeKind):
        raise InferenceError(ErrorCode.RUNTIME_UNAVAILABLE, "Unknown runtime selection.")
    if request.device_index is not None and (
        type(request.device_index) is not int or request.device_index < 0
        or request.kind is RuntimeKind.CPU
    ):
        raise InferenceError(ErrorCode.RUNTIME_UNAVAILABLE, "Invalid runtime device index.")
    candidates = [d for d in capabilities.devices if d.kind in supported and (
        request.kind is None or d.kind is request.kind
    ) and (request.device_index is None or d.index == request.device_index)]
    if request.kind is None:
        candidates = [d for d in candidates if d.kind is not RuntimeKind.CPU or request.allow_cpu_fallback]
        candidates.sort(key=lambda d: d.kind is RuntimeKind.CPU)
    if not candidates:
        raise InferenceError(
            ErrorCode.RUNTIME_UNAVAILABLE,
            "No validated runtime matches this backend and selection. CPU fallback requires opt-in.",
        )
    return candidates[0]
