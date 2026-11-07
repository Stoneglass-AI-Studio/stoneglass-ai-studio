# SPDX-License-Identifier: GPL-3.0-or-later

from dataclasses import dataclass

from stoneglass.services.hardware import HardwareService
from stoneglass.services.paths import AppPaths
from stoneglass.services.settings import SettingsStore


@dataclass(frozen=True)
class ApplicationServices:
    paths: AppPaths
    settings: SettingsStore
    hardware: HardwareService

    @classmethod
    def create(cls, paths: AppPaths) -> "ApplicationServices":
        return cls(paths, SettingsStore(paths.settings_file), HardwareService())
