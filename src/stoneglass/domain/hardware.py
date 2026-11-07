# SPDX-License-Identifier: GPL-3.0-or-later

from dataclasses import dataclass
from enum import Enum


class GpuVendor(str, Enum):
    AMD = "AMD"
    NVIDIA = "NVIDIA"
    INTEL = "Intel"
    UNKNOWN = "Unknown"


@dataclass(frozen=True)
class GpuInfo:
    name: str
    vendor: GpuVendor
    driver_version: str = "Unknown"


@dataclass(frozen=True)
class HardwareReport:
    platform: str
    gpus: tuple[GpuInfo, ...] = ()
    warning: str | None = None

    @property
    def summary(self) -> str:
        if self.gpus:
            return " · ".join(f"{gpu.vendor.value}: {gpu.name}" for gpu in self.gpus)
        return self.warning or "No display adapters reported."
