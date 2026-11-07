# SPDX-License-Identifier: GPL-3.0-or-later

"""Local model references and strict requests, without UI clamping or downloads."""

from dataclasses import replace
from math import isfinite
from pathlib import Path

from stoneglass.domain.dimensions import DIMENSION_STEP, MAX_DIMENSION, MIN_DIMENSION
from stoneglass.inference.contracts import GenerationRequest, ModelSpec, ModelVariant
from stoneglass.inference.errors import ErrorCode, InferenceError


def local_path(path: Path) -> Path:
    if not isinstance(path, Path) or str(path).startswith(("\\\\", "//")):
        raise InferenceError(ErrorCode.INVALID_MODEL, "Use an existing local model path.")
    try:
        resolved = path.expanduser().resolve(strict=True)
        if str(resolved).startswith(("\\\\", "//")) or not (
            resolved.is_file() or resolved.is_dir()
        ):
            raise OSError()
        return resolved
    except (OSError, RuntimeError, ValueError):
        raise InferenceError(
            ErrorCode.INVALID_MODEL, "The local model or adapter path is unavailable."
        ) from None


def validate_model(model: ModelSpec) -> ModelSpec:
    if not model.model_id.strip() or not model.architecture.strip() or not isinstance(
        model.variant, ModelVariant
    ):
        raise InferenceError(ErrorCode.INVALID_MODEL, "The model specification is invalid.")
    if model.resource_manifest is not None:
        # Reject mapped drives/junctions before legacy resolve() can follow a
        # remote target. This stricter boundary applies to the new SDXL profile.
        from stoneglass.inference.resources import strict_local
        return replace(model, path=strict_local(model.path), resource_manifest=strict_local(model.resource_manifest),
                       adapters=tuple(strict_local(path) for path in model.adapters))
    return replace(model, path=local_path(model.path), adapters=tuple(map(local_path, model.adapters)),
                   resource_manifest=local_path(model.resource_manifest) if model.resource_manifest else None)


def validate_request(request: GenerationRequest, model: ModelSpec) -> None:
    settings = request.settings
    integers = (settings.width, settings.height, settings.steps, settings.seed)
    valid = (
        isinstance(request.positive_prompt, str) and isinstance(request.negative_prompt, str)
        and all(type(value) is int for value in integers)
        and all(MIN_DIMENSION <= size <= MAX_DIMENSION and size % DIMENSION_STEP == 0
                for size in (settings.width, settings.height))
        and 1 <= settings.steps <= 150 and -1 <= settings.seed <= 2_147_483_647
        and type(settings.guidance) in (int, float) and isfinite(settings.guidance)
        and 0 <= settings.guidance <= 30
        and request.model_id in (None, model.model_id)
    )
    if not valid:
        raise InferenceError(
            ErrorCode.INVALID_REQUEST, "Generation settings or the selected model are invalid."
        )
