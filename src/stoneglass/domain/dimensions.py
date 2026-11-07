# SPDX-License-Identifier: GPL-3.0-or-later

"""Dimension choices shared by validation and desktop controls."""

MIN_DIMENSION = 256
MAX_DIMENSION = 2048
DIMENSION_STEP = 64

RESOLUTION_PRESETS = ((512, 512), (768, 1024), (1024, 768), (1024, 1024))
ASPECT_RATIOS = ((1, 1), (3, 2), (2, 3), (16, 9), (9, 16))
# Automatic choices stay within the largest explicit resolution preset's area.
# This is a UI sizing limit, not a claim about a future model's VRAM needs.
ASPECT_PRESET_MAX_PIXELS = 1024 * 1024


def matching_aspect(width: int, height: int) -> tuple[int, int] | None:
    return next((ratio for ratio in ASPECT_RATIOS if width * ratio[1] == height * ratio[0]), None)


def dimensions_for_aspect(width: int, height: int, ratio: tuple[int, int]) -> tuple[int, int]:
    """Choose the closest area on the grid within the automatic preset budget.

    Only explicit selection applies this limit; manual and restored dimensions
    remain valid up to MAX_DIMENSION. Exact ratios are retained, and equal-area
    differences prefer the smaller result. Some ratios require increasing very
    small inputs to meet the minimum dimension and grid constraints.
    """
    if ratio not in ASPECT_RATIOS:
        raise ValueError("Unsupported aspect ratio")
    numerator, denominator = ratio
    candidates = (
        (numerator * DIMENSION_STEP * scale, denominator * DIMENSION_STEP * scale)
        for scale in range(1, MAX_DIMENSION // (max(ratio) * DIMENSION_STEP) + 1)
    )
    valid = (size for size in candidates
             if min(size) >= MIN_DIMENSION and size[0] * size[1] <= ASPECT_PRESET_MAX_PIXELS)
    return min(valid, key=lambda size: (abs(size[0] * size[1] - width * height), size[0] * size[1]))
