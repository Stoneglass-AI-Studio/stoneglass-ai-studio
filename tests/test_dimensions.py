# SPDX-License-Identifier: GPL-3.0-or-later

import unittest

from PySide6.QtCore import QSize, Qt
from PySide6.QtTest import QTest

from qt_support import APP
from stoneglass.domain.dimensions import (
    ASPECT_PRESET_MAX_PIXELS, ASPECT_RATIOS, RESOLUTION_PRESETS, dimensions_for_aspect,
)
from stoneglass.ui.dimension_controls import DimensionControls


class DimensionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.controls = DimensionControls(1024, 1024)
        self.controls.show()
        APP.processEvents()

    def tearDown(self) -> None:
        self.controls.close()
        self.controls.deleteLater()
        APP.processEvents()

    def test_each_resolution_updates_both_fields_and_aspect(self) -> None:
        for size in RESOLUTION_PRESETS:
            with self.subTest(size=size):
                combo = self.controls.resolution_preset
                combo.setCurrentIndex(combo.findData(QSize(*size)))
                self.assertEqual((self.controls.width.value(), self.controls.height.value()), size)
                self.assertEqual(combo.currentData(), QSize(*size))
        self.assertEqual(self.controls.aspect_ratio.currentData(), QSize(1, 1))

    def test_aspect_choices_are_exact_valid_and_closest_in_pixel_count(self) -> None:
        for size in ((256, 256), (1024, 1024), (2048, 2048), (768, 1024)):
            for ratio in ASPECT_RATIOS:
                with self.subTest(size=size, ratio=ratio):
                    self.controls.width.setValue(size[0])
                    self.controls.height.setValue(size[1])
                    combo = self.controls.aspect_ratio
                    # Keep the input size and exercise selection even when it already matches.
                    index = combo.findData(QSize(*ratio))
                    combo.currentIndexChanged.emit(index)
                    width, height = self.controls.width.value(), self.controls.height.value()
                    self.assertEqual(width * ratio[1], height * ratio[0])
                    self.assertTrue(256 <= min(width, height) <= max(width, height) <= 2048)
                    self.assertEqual(width % 64, 0)
                    self.assertEqual(height % 64, 0)
                    self.assertLessEqual(width * height, ASPECT_PRESET_MAX_PIXELS)
                    candidates = [(w, h) for w in range(256, 2049, 64) for h in range(256, 2049, 64)
                                  if w * ratio[1] == h * ratio[0] and w * h <= ASPECT_PRESET_MAX_PIXELS]
                    self.assertEqual(abs(width * height - size[0] * size[1]),
                                     min(abs(w * h - size[0] * size[1]) for w, h in candidates))

    def test_aspect_combo_updates_dimensions(self) -> None:
        combo = self.controls.aspect_ratio
        combo.setCurrentIndex(combo.findData(QSize(16, 9)))
        self.assertEqual((self.controls.width.value(), self.controls.height.value()), (1024, 576))
        self.assertEqual(self.controls.resolution_preset.currentText(), "Custom")
        self.assertEqual(combo.currentText(), "16:9")

    def test_manual_values_show_custom_and_recognize_matching_presets(self) -> None:
        self.controls.width.setValue(832)
        self.controls.height.setValue(640)
        self.assertEqual(self.controls.resolution_preset.currentText(), "Custom")
        self.assertEqual(self.controls.aspect_ratio.currentText(), "Custom")
        self.controls.width.setValue(1152)
        self.controls.height.setValue(768)
        self.assertEqual(self.controls.resolution_preset.currentText(), "Custom")
        self.assertEqual(self.controls.aspect_ratio.currentText(), "3:2")
        self.controls.width.setValue(768)
        self.controls.height.setValue(1024)
        self.assertEqual(self.controls.resolution_preset.currentData(), QSize(768, 1024))
        self.assertEqual(self.controls.aspect_ratio.currentText(), "Custom")

    def test_manual_off_grid_values_normalize_before_notifying_preferences(self) -> None:
        observed: list[tuple[int, int]] = []
        self.controls.preferences_changed.connect(
            lambda: observed.append((self.controls.width.value(), self.controls.height.value()))
        )
        self.controls.width.setValue(1000)
        self.assertEqual(self.controls.width.value(), 960)
        self.assertEqual(observed, [(960, 1024)])

    def test_preset_change_notifies_once_with_complete_dimensions(self) -> None:
        observed: list[tuple[int, int]] = []
        self.controls.preferences_changed.connect(
            lambda: observed.append((self.controls.width.value(), self.controls.height.value()))
        )
        self.controls.resolution_preset.setCurrentIndex(self.controls.resolution_preset.findData(QSize(512, 512)))
        self.assertEqual(observed, [(512, 512)])

    def test_presets_can_be_selected_with_keyboard(self) -> None:
        self.controls.resolution_preset.setFocus()
        QTest.keyClick(self.controls.resolution_preset, Qt.Key.Key_Up)
        self.assertEqual((self.controls.width.value(), self.controls.height.value()), (1024, 768))

    def test_unsupported_ratio_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            dimensions_for_aspect(1024, 1024, (0, 1))

    def test_typed_manual_value_is_committed_to_the_validated_grid(self) -> None:
        self.controls.width.setFocus()
        self.controls.width.selectAll()
        QTest.keyClicks(self.controls.width, "1000")
        QTest.keyClick(self.controls.width, Qt.Key.Key_Return)
        self.assertEqual(self.controls.width.value(), 960)
        self.assertEqual(self.controls.resolution_preset.currentText(), "Custom")

    def test_reselecting_a_matching_aspect_applies_budget_only_on_activation(self) -> None:
        self.controls.width.setValue(1920)
        self.controls.height.setValue(1280)
        combo = self.controls.aspect_ratio
        self.assertEqual(combo.currentText(), "3:2")
        self.assertEqual((self.controls.width.value(), self.controls.height.value()), (1920, 1280))
        combo.activated.emit(combo.currentIndex())
        self.assertEqual((self.controls.width.value(), self.controls.height.value()), (1152, 768))
        self.assertEqual(combo.currentText(), "3:2")

    def test_user_activation_does_not_duplicate_preference_notifications(self) -> None:
        observed: list[tuple[int, int]] = []
        self.controls.preferences_changed.connect(
            lambda: observed.append((self.controls.width.value(), self.controls.height.value()))
        )
        for combo, choice in (
            (self.controls.resolution_preset, QSize(512, 512)),
            (self.controls.aspect_ratio, QSize(16, 9)),
        ):
            observed.clear()
            index = combo.findData(choice)
            combo.setCurrentIndex(index)
            combo.activated.emit(index)
            self.assertEqual(len(observed), 1)
