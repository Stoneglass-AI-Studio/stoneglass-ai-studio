# SPDX-License-Identifier: GPL-3.0-or-later
"""Provider/service integration using existing contracts and one owned worker."""

import os
import uuid
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from stoneglass.services.inference import InferenceService

from stoneglass.inference.contracts import (
    BackendCapabilities, GenerationRequest, GenerationResult, InferenceContext, ModelSpec,
    ModelVariant, ProgressStage, RuntimeCapabilities, RuntimeDevice, RuntimeKind,
)
from stoneglass.inference.errors import ErrorCode, InferenceError
from stoneglass.inference.resources import invalid, read_manifest, strict_local, validate_sdxl
from stoneglass.inference.runtime import parse_capabilities
from stoneglass.inference.worker import WorkerLauncher, WorkerClient, WorkerSettings
from stoneglass.inference.worker_server import model_payload


def preflight(model: ModelSpec, context: InferenceContext) -> None:
    if model.architecture != "sdxl" or model.variant is not ModelVariant.BASE or model.adapters:
        raise invalid("The initial provider accepts complete SDXL-base checkpoints without extra adapters.")
    if model.resource_manifest is None:
        raise invalid("Select a schema-1 local SDXL resource manifest containing all 14 configuration/tokenizer resources.")
    manifest = read_manifest(model.resource_manifest)
    if strict_local(model.path) != manifest.checkpoint:
        raise invalid("The selected checkpoint and local manifest must match.")
    validate_sdxl(manifest, context)


class ProcessRuntimeDetector:
    def __init__(self, settings: WorkerSettings, launcher: WorkerLauncher | None = None, *, reviewed_profile: bool = False) -> None:
        self._settings, self._launcher = settings, launcher
        self._reviewed_profile = reviewed_profile
        self._client: WorkerClient | None = None

    @property
    def requires_cleanup(self) -> bool:
        return self._client is not None

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def detect(self, context: InferenceContext) -> RuntimeCapabilities:
        self.close()
        client = self._client = WorkerClient(self._settings, self._launcher)
        try:
            from stoneglass.inference.contracts import ProgressEvent
            context.report_event(ProgressEvent(ProgressStage.RUNTIME, 0, "Starting local worker and checking the installed GPU runtime"))
            report = client.call("detect", {}, context, timeout=self._settings.runtime_timeout, stage=ProgressStage.RUNTIME)
            if self._reviewed_profile:
                devices = [d for d in report.get("devices", []) if d.get("kind") == "rocm"
                           and "9060 XT" in d.get("name", "") and d.get("gcn_arch") == "gfx1200"]
                if (report.get("torch_version") != "2.13.0+rocm10.0.0" or not report.get("hip_version")
                        or report.get("cuda_version") is not None or not devices):
                    raise InferenceError(ErrorCode.RUNTIME_UNAVAILABLE,
                        "This UI profile requires the reviewed .venv-rocm and an available RX 9060 XT gfx1200. CPU and NVIDIA UI profiles are not available yet.")
                report = {**report, "devices": devices}
            import json
            return parse_capabilities(json.dumps(report))
        finally:
            self.close()


class SDXLProcessBackend:
    def __init__(self, settings: WorkerSettings, launcher: WorkerLauncher | None = None) -> None:
        self._settings = settings
        self._run = settings.output_directory / ("worker-" + uuid.uuid4().hex)
        self._client = WorkerClient(replace(settings, output_directory=self._run), launcher)
        self._pending: tuple[Path, GenerationResult] | None = None

    def load_model(self, model: ModelSpec, runtime: RuntimeDevice, context: InferenceContext) -> None:
        # Rechecked inside the process under read leases immediately before loading.
        preflight(model, context)
        self._client.call("load", {"model": model_payload(model), "runtime": asdict(runtime),
                                  "output_directory": str(self._run)}, context,
                          timeout=self._settings.load_timeout, stage=ProgressStage.LOADING)

    def generate(self, request: GenerationRequest, context: InferenceContext) -> GenerationResult:
        if self._pending is not None:
            raise InferenceError(ErrorCode.BUSY, "A previous result still needs to be committed or cleaned up.")
        # Prompts cross only the inherited pipe; not command arguments or files.
        payload = {"positive_prompt": request.positive_prompt, "negative_prompt": request.negative_prompt,
                   "settings": asdict(request.settings), "model_id": request.model_id}
        response = self._client.call("generate", payload, context,
                                     timeout=self._settings.generation_timeout, stage=ProgressStage.GENERATING)
        try:
            name = response["image_path"]
            if (not isinstance(name, str) or Path(name).name != name or "/" in name or "\\" in name
                    or not name.startswith("stoneglass-") or not name.endswith(".png") or len(name) > 100
                    or set(response) != {"image_path", "seed", "width", "height", "model_id"}):
                raise ValueError()
            result = GenerationResult(self._settings.output_directory / name, response["seed"],
                                      response["width"], response["height"], response["model_id"])
            self._pending = (self._run / name, result)
            return result
        except (KeyError, TypeError, ValueError):
            raise InferenceError(ErrorCode.WORKER_FAILED, "The worker returned invalid output metadata.") from None

    def commit_result(self, result: GenerationResult) -> None:
        if self._pending is None or self._pending[1] != result:
            raise InferenceError(ErrorCode.WORKER_FAILED, "There is no matching pending result to commit.")
        source = strict_local(self._pending[0])
        from stoneglass.services.images import validate_png
        validate_png(source, result.width, result.height)
        strict_local(result.image_path.parent, directory=True)
        if result.image_path.exists():
            raise InferenceError(ErrorCode.GENERATION_FAILED, "The generated-image destination already exists.")
        os.replace(source, result.image_path)
        self._pending = None

    def diagnostics(self, context: InferenceContext) -> dict[str, Any]:
        return self._client.call("diagnostics", {}, context, timeout=10, stage=ProgressStage.GENERATING)

    def unload(self) -> None:
        # Terminate/reap the owned OS job even when cooperative Python unloading
        # cannot run (hung native GPU call, cancellation or malformed protocol).
        self._client.close()
        self._pending = None
        if self._run.exists():
            strict_local(self._run, directory=True)
            for path in self._run.iterdir():
                if not path.name.startswith("stoneglass-") or path.suffix not in (".png", ".tmp") or not path.is_file():
                    raise InferenceError(ErrorCode.CLEANUP_FAILED, "Unexpected worker output was preserved for review.")
                strict_local(path).unlink()
            self._run.rmdir()


class SDXLProcessProvider:
    capabilities = BackendCapabilities(
        "local-sdxl-worker", frozenset({"sdxl"}), frozenset({ModelVariant.BASE}),
        frozenset({RuntimeKind.ROCM}), generation_available=False,
    )

    def __init__(self, settings: WorkerSettings, launcher: WorkerLauncher | None = None, *, enable_generation: bool = False, reviewed_profile: bool = False) -> None:
        self.settings, self.launcher = settings, launcher
        self._reviewed_profile = reviewed_profile
        self.capabilities = replace(type(self).capabilities, generation_available=enable_generation)

    def validate_resources(self, model: ModelSpec, context: InferenceContext) -> None:
        if self._reviewed_profile:
            from stoneglass.inference.reviewed_profile import require_reviewed_profile
            require_reviewed_profile(model)
        preflight(model, context)

    def create(self) -> SDXLProcessBackend:
        return SDXLProcessBackend(self.settings, self.launcher)


def create_sdxl_service(project: Path, data: Path, launcher: WorkerLauncher | None = None, *, enable_generation: bool = False, reviewed_profile: bool = False) -> "InferenceService":
    """Compose the local provider; registration never probes or loads a model."""
    from stoneglass.services.inference import InferenceService
    settings = WorkerSettings.for_project(project, data)
    return InferenceService((SDXLProcessProvider(settings, launcher, enable_generation=enable_generation, reviewed_profile=reviewed_profile),),
                            ProcessRuntimeDetector(settings, launcher, reviewed_profile=reviewed_profile))
