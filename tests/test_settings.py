# SPDX-License-Identifier: GPL-3.0-or-later

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from stoneglass.domain.settings import AppSettings, GenerationSettings
from stoneglass.services.paths import AppPaths
from stoneglass.services.settings import SettingsError, SettingsStore


class SettingsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "settings.json"
        self.store = SettingsStore(self.path)

    def test_missing_file_returns_defaults_without_writing(self) -> None:
        self.assertEqual(self.store.load(), AppSettings())
        self.assertFalse(self.path.exists())

    def test_round_trip_persists_preferences_only(self) -> None:
        expected = AppSettings(
            window_width=1440, maximized=True, sidebar_collapsed=True,
            generation=GenerationSettings(width=768, steps=45, seed=123),
        )
        self.store.save(expected)
        self.assertEqual(SettingsStore(self.path).load(), expected)
        self.assertNotIn("prompt", self.path.read_text())
        self.assertEqual(list(self.path.parent.glob("*.tmp")), [])

    def test_malformed_file_is_preserved_and_save_is_blocked(self) -> None:
        self.path.write_text("{broken", encoding="utf-8")
        with self.assertLogs("stoneglass.services.settings", level="WARNING"):
            self.assertEqual(self.store.load(), AppSettings())
        self.assertIn("Using defaults", self.store.warning or "")
        with self.assertRaises(SettingsError):
            self.store.save(AppSettings())
        self.assertEqual(self.path.read_text(), "{broken")

    def test_future_schema_is_preserved(self) -> None:
        self.path.write_text('{"schema_version": 99}', encoding="utf-8")
        with self.assertLogs("stoneglass.services.settings", level="WARNING"):
            self.store.load()
        with self.assertRaises(SettingsError):
            self.store.save(AppSettings())
        self.assertEqual(json.loads(self.path.read_text())["schema_version"], 99)

    def test_invalid_values_are_normalized(self) -> None:
        settings = AppSettings.from_dict({
            "window_width": -1, "window_height": "huge", "maximized": "false",
            "generation": {"width": 1000, "height": 9000, "steps": True,
                           "guidance": float("nan"), "seed": -999},
        })
        self.assertEqual(settings.window_width, 960)
        self.assertEqual(settings.window_height, 820)
        self.assertFalse(settings.maximized)
        self.assertEqual(settings.generation, GenerationSettings(
            width=960, height=2048, steps=30, guidance=7.0, seed=-1,
        ))

    def test_failed_atomic_replace_preserves_previous_file(self) -> None:
        self.store.save(AppSettings())
        with patch("stoneglass.services.settings.os.replace", side_effect=PermissionError("Locked")):
            with self.assertLogs("stoneglass.services.settings", level="ERROR"):
                with self.assertRaises(SettingsError):
                    self.store.save(replace(AppSettings(), window_width=1500))
        self.assertEqual(self.store.load(), AppSettings())
        self.assertFalse(list(self.path.parent.glob("*.tmp")))

    def test_older_phase_one_settings_default_to_expanded_sidebar(self) -> None:
        data = AppSettings().to_dict()
        del data["sidebar_collapsed"]
        self.path.write_text(json.dumps(data), encoding="utf-8")
        self.assertFalse(self.store.load().sidebar_collapsed)
        self.assertIsNone(self.store.warning)

    def test_sidebar_preference_requires_a_boolean(self) -> None:
        for value in ("true", "false", 1, None):
            self.assertFalse(AppSettings.from_dict({"sidebar_collapsed": value}).sidebar_collapsed)
        self.assertTrue(AppSettings.from_dict({"sidebar_collapsed": True}).sidebar_collapsed)

    def test_data_directory_override(self) -> None:
        with patch.dict("os.environ", {"STONEGLASS_DATA_DIR": self.temporary.name}):
            self.assertEqual(AppPaths.discover().root, Path(self.temporary.name).resolve())
