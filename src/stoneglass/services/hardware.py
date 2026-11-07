# SPDX-License-Identifier: GPL-3.0-or-later

"""Windows adapter inventory without importing any compute framework."""

import json
import logging
import os
import platform
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from stoneglass.domain.hardware import GpuInfo, GpuVendor, HardwareReport

logger = logging.getLogger(__name__)

QUERY = (
    "$ErrorActionPreference = 'Stop'; "
    "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false); "
    "@(Get-CimInstance -ClassName Win32_VideoController | "
    "Select-Object Name, AdapterCompatibility, PNPDeviceID, DriverVersion) | "
    "ConvertTo-Json -Compress"
)


def identify_vendor(name: str, manufacturer: str, device_id: str) -> GpuVendor:
    device = device_id.upper()
    if "VEN_1002" in device:
        return GpuVendor.AMD
    if "VEN_10DE" in device:
        return GpuVendor.NVIDIA
    if "VEN_8086" in device:
        return GpuVendor.INTEL
    description = f"{name} {manufacturer}".casefold()
    if any(word in description for word in ("amd", "radeon", "advanced micro devices")):
        return GpuVendor.AMD
    if "nvidia" in description:
        return GpuVendor.NVIDIA
    if "intel" in description:
        return GpuVendor.INTEL
    return GpuVendor.UNKNOWN


def parse_adapters(raw: str) -> tuple[GpuInfo, ...]:
    data = json.loads(raw.lstrip("\ufeff")) if raw.strip() else []
    if data is None:
        return ()
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
        raise ValueError("Unexpected display-adapter response.")
    adapters: list[GpuInfo] = []
    for row in data:
        name = str(row.get("Name") or "Unnamed display adapter")
        adapters.append(GpuInfo(
            name=name,
            vendor=identify_vendor(name, str(row.get("AdapterCompatibility") or ""),
                                   str(row.get("PNPDeviceID") or "")),
            driver_version=str(row.get("DriverVersion") or "Unknown"),
        ))
    return tuple(adapters)


class HardwareService:
    def __init__(
        self, runner: Callable[..., Any] = subprocess.run,
        system: str | None = None,
    ) -> None:
        self._runner = runner
        self._system = sys.platform if system is None else system

    def detect(self) -> HardwareReport:
        system_name = platform.platform()
        if self._system != "win32":
            return HardwareReport(system_name, warning="GPU detection is available on Windows only.")
        powershell = Path(os.environ.get("SystemRoot", r"C:\Windows")) / (
            "System32/WindowsPowerShell/v1.0/powershell.exe"
        )
        try:
            result = self._runner(
                [str(powershell), "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", QUERY],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=15, check=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            gpus = parse_adapters(result.stdout)
            logger.info("Hardware inventory completed: %d display adapter(s)", len(gpus))
            return HardwareReport(system_name, gpus)
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            diagnostic = getattr(exc, "stderr", None) or str(exc)
            logger.exception("Windows display adapter detection failed: %s", diagnostic[:2000])
            return HardwareReport(
                system_name, warning="GPU detection failed. Check the local log for details."
            )
