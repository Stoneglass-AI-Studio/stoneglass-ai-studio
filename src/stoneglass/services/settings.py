# SPDX-License-Identifier: GPL-3.0-or-later

import json
import logging
import os
import tempfile
from pathlib import Path

from stoneglass.domain.settings import AppSettings

logger = logging.getLogger(__name__)


class SettingsError(Exception):
    """A readable settings error that can be presented to the user."""


class SettingsStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.warning: str | None = None
        self.writable = True

    def load(self) -> AppSettings:
        self.warning = None
        self.writable = True
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("Settings must contain a JSON object.")
            if type(data.get("schema_version")) is not int or data["schema_version"] != 1:
                self.writable = False
                raise ValueError("Unsupported settings version; existing file will be preserved.")
            return AppSettings.from_dict(data)
        except FileNotFoundError:
            return AppSettings()
        except (OSError, ValueError) as exc:
            # Never silently overwrite an unreadable or damaged configuration.
            self.writable = False
            self.warning = f"Settings could not be loaded. Using defaults. {exc}"
            logger.warning(self.warning, exc_info=True)
            return AppSettings()

    def save(self, settings: AppSettings) -> None:
        if not self.writable:
            raise SettingsError(
                f"Settings were not saved because {self.path} could not be read safely. "
                "Close Stoneglass and rename that file to restore saving."
            )
        temporary: Path | None = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.path.parent,
                prefix="settings-", suffix=".tmp", delete=False,
            ) as handle:
                temporary = Path(handle.name)
                json.dump(settings.to_dict(), handle, indent=2, allow_nan=False)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        except (OSError, ValueError) as exc:
            logger.exception("Could not save application settings")
            raise SettingsError(f"Could not save settings to {self.path}: {exc}") from exc
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    logger.warning("Could not remove temporary settings file", exc_info=True)
