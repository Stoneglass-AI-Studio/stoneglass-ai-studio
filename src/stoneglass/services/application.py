# SPDX-License-Identifier: GPL-3.0-or-later

from dataclasses import dataclass, field
from pathlib import Path
from stoneglass.inference.worker import WorkerLauncher

from stoneglass.services.hardware import HardwareService
from stoneglass.services.inference import InferenceService
from stoneglass.services.paths import AppPaths
from stoneglass.services.settings import SettingsStore


@dataclass(frozen=True)
class ApplicationServices:
    paths: AppPaths
    settings: SettingsStore
    hardware: HardwareService
    inference: InferenceService = field(default_factory=InferenceService)
    project: Path = Path(__file__).resolve().parents[3]

    @classmethod
    def create(cls, paths: AppPaths, *, launcher: WorkerLauncher | None = None) -> "ApplicationServices":
        from stoneglass.inference.process_backend import create_sdxl_service
        project = Path(__file__).resolve().parents[3]
        inference = create_sdxl_service(project, paths.root, launcher,
                                        enable_generation=True, reviewed_profile=True)
        return cls(paths, SettingsStore(paths.settings_file), HardwareService(), inference, project)
