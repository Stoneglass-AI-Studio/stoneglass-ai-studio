# SPDX-License-Identifier: GPL-3.0-or-later
"""Explicit model-free checks, executed only by the dedicated inference worker."""

import importlib
import time
from typing import Any

from stoneglass.inference.contracts import InferenceContext, ProgressEvent, ProgressStage
from stoneglass.inference.errors import ErrorCode, InferenceError
from stoneglass.inference.offline import assert_offline_policy


def validate_runtime(context: InferenceContext) -> dict[str, Any]:
    """Small actual GPU operations and class imports; never constructs a model."""
    assert_offline_policy()
    started = time.monotonic()

    def progress(percent: int, message: str) -> None:
        context.check_cancelled()
        context.report_event(ProgressEvent(ProgressStage.RUNTIME, percent, message))

    progress(0, "Importing the local ROCm runtime; cold initialization may take several minutes")
    torch = importlib.import_module("torch")
    progress(5, "PyTorch imported; checking the actual local HIP device")
    if (str(torch.__version__) != "2.13.0+rocm10.0.0" or not torch.version.hip
            or torch.version.cuda is not None or not torch.cuda.is_available()):
        raise InferenceError(ErrorCode.RUNTIME_UNAVAILABLE, "The reviewed local ROCm PyTorch runtime is unavailable.")
    properties = torch.cuda.get_device_properties(0)
    if "9060 XT" not in properties.name or getattr(properties, "gcnArchName", "") != "gfx1200":
        raise InferenceError(ErrorCode.RUNTIME_UNAVAILABLE, "This validation profile requires the RX 9060 XT gfx1200.")
    report: dict[str, Any] = {"schema": 1, "model_loaded": False, "image_generated": False,
        "torch": str(torch.__version__), "hip": torch.version.hip, "cuda_build": torch.version.cuda,
        "gpu": properties.name, "architecture": properties.gcnArchName,
        "vram_bytes": properties.total_memory, "checks": {}}
    try:
        with torch.inference_mode(), torch.cuda.device(0):
            for percent, dtype in ((15, torch.float32), (30, torch.float16), (45, torch.bfloat16)):
                progress(percent, f"Checking {dtype} GPU arithmetic and matrix multiplication")
                values = torch.ones((128, 128), dtype=dtype, device="cuda:0")
                actual = (values + 1) @ values
                torch.cuda.synchronize(0)
                error = (actual.float() - 256).abs().max().item()
                if not torch.isfinite(actual).all().item() or error >= 0.01:
                    raise InferenceError(ErrorCode.RUNTIME_UNAVAILABLE, "Local GPU arithmetic validation failed.")
                report["checks"][str(dtype)] = {"passed": True, "maximum_error": error}
                del values, actual
            progress(60, "Checking FP16 attention against the explicit math implementation")
            from torch.nn.attention import sdpa_kernel, SDPBackend
            functional = importlib.import_module("torch.nn.functional")
            q = (torch.arange(2 * 4 * 32 * 64, device="cuda:0", dtype=torch.float32)
                 .reshape(2, 4, 32, 64) / 10000).to(torch.float16)
            with sdpa_kernel(SDPBackend.MATH):
                baseline = functional.scaled_dot_product_attention(q, q, q)
            actual = functional.scaled_dot_product_attention(q, q, q)
            torch.cuda.synchronize(0)
            error = (baseline - actual).abs().max().item()
            if not torch.isfinite(actual).all().item() or error >= 0.02:
                raise InferenceError(ErrorCode.RUNTIME_UNAVAILABLE, "Local GPU attention validation failed.")
            report["checks"]["attention"] = {"passed": True, "maximum_error": error}
            del q, baseline, actual
            progress(75, "Checking FP16 GPU convolution")
            values = torch.ones((1, 4, 16, 16), device="cuda:0", dtype=torch.float16)
            weights = torch.ones((8, 4, 3, 3), device="cuda:0", dtype=torch.float16)
            actual = functional.conv2d(values, weights)
            torch.cuda.synchronize(0)
            error = (actual.float() - 36).abs().max().item()
            if tuple(actual.shape) != (1, 8, 14, 14) or not torch.isfinite(actual).all().item() or error >= 0.01:
                raise InferenceError(ErrorCode.RUNTIME_UNAVAILABLE, "Local GPU convolution validation failed.")
            report["checks"]["convolution"] = {"passed": True, "maximum_error": error, "shape": list(actual.shape)}
            del values, weights, actual
        progress(90, "Checking local SDXL, CLIP and supporting library imports without loading weights")
        from stoneglass.inference.sdxl import _dependencies
        deps = _dependencies()
        classes = (deps.diffusers.StableDiffusionXLPipeline, deps.transformers.CLIPTokenizer,
                   deps.transformers.CLIPTextModel, deps.transformers.CLIPTextModelWithProjection)
        if not callable(classes[0].from_single_file) or not all(isinstance(cls, type) for cls in classes):
            raise InferenceError(ErrorCode.RUNTIME_UNAVAILABLE, "Local SDXL/CLIP imports are incomplete.")
        report["versions"] = {name: importlib.import_module(name).__version__ for name in
                              ("diffusers", "transformers", "accelerate", "safetensors", "torchvision")}
        report["checks"]["sdxl_clip_imports"] = {"passed": True}
        assert_offline_policy()
        progress(100, "Model-free local ROCm validation completed")
        report["elapsed_seconds"] = round(time.monotonic() - started, 3)
        return report
    finally:
        torch.cuda.empty_cache()
