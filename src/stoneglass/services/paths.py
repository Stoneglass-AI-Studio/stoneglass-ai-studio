# SPDX-License-Identifier: GPL-3.0-or-later

import os
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppPaths:
    root: Path

    @classmethod
    def discover(cls) -> "AppPaths":
        override = os.environ.get("STONEGLASS_DATA_DIR")
        if override:
            return cls(Path(override).expanduser().resolve())
        if sys.platform == "win32":
            base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        else:
            base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
        return cls(base / "Stoneglass")

    @property
    def settings_file(self) -> Path:
        return self.root / "settings.json"

    @property
    def log_dir(self) -> Path:
        return self.root / "logs"

    def ensure(self) -> None:
        self.log_dir.mkdir(parents=True, exist_ok=True)
