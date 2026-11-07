# SPDX-License-Identifier: GPL-3.0-or-later

"""Validated, versioned application preferences. Prompts are never persisted."""

from dataclasses import asdict, dataclass, field
from typing import Any

from stoneglass.domain.dimensions import DIMENSION_STEP, MAX_DIMENSION, MIN_DIMENSION


def bounded_int(value: object, default: int, minimum: int, maximum: int) -> int:
    if type(value) is not int:
        return default
    return max(minimum, min(maximum, value))


@dataclass(frozen=True)
class GenerationSettings:
    width: int = 1024
    height: int = 1024
    steps: int = 30
    guidance: float = 7.0
    seed: int = -1

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GenerationSettings":
        guidance = data.get("guidance", 7.0)
        if type(guidance) not in (int, float) or not 0 <= guidance <= 30:
            guidance = 7.0
        return cls(
            width=bounded_int(data.get("width"), 1024, MIN_DIMENSION, MAX_DIMENSION)
            // DIMENSION_STEP * DIMENSION_STEP,
            height=bounded_int(data.get("height"), 1024, MIN_DIMENSION, MAX_DIMENSION)
            // DIMENSION_STEP * DIMENSION_STEP,
            steps=bounded_int(data.get("steps"), 30, 1, 150),
            guidance=float(guidance),
            seed=bounded_int(data.get("seed"), -1, -1, 2_147_483_647),
        )


@dataclass(frozen=True)
class AppSettings:
    schema_version: int = 1
    window_width: int = 1280
    window_height: int = 820
    maximized: bool = False
    sidebar_collapsed: bool = False
    generation: GenerationSettings = field(default_factory=GenerationSettings)
    model_path: str = ""
    resource_manifest_path: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AppSettings":
        generation = data.get("generation", {})
        return cls(
            window_width=bounded_int(data.get("window_width"), 1280, 960, 7680),
            window_height=bounded_int(data.get("window_height"), 820, 640, 4320),
            maximized=data.get("maximized") is True,
            sidebar_collapsed=data.get("sidebar_collapsed") is True,
            generation=GenerationSettings.from_dict(
                generation if isinstance(generation, dict) else {}
            ),
            model_path=data.get("model_path", "") if isinstance(data.get("model_path", ""), str) else "",
            resource_manifest_path=data.get("resource_manifest_path", "") if isinstance(data.get("resource_manifest_path", ""), str) else "",
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
