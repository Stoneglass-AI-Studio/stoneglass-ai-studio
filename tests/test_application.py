# SPDX-License-Identifier: GPL-3.0-or-later

import json
import sys
import tempfile
import unittest
from pathlib import Path
from dataclasses import replace
from threading import Event
from unittest.mock import Mock

from PySide6.QtCore import QPoint, QSize, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel, QScrollArea

from qt_support import APP, wait_until
from stoneglass.app import build_window
from stoneglass.domain.hardware import GpuInfo, GpuVendor, HardwareReport
from stoneglass.domain.dimensions import ASPECT_RATIOS, RESOLUTION_PRESETS
from stoneglass.infrastructure.workers import WorkerContext
from stoneglass.services.application import ApplicationServices
from stoneglass.services.paths import AppPaths
from stoneglass.services.settings import SettingsStore


class ApplicationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.paths = AppPaths(Path(self.temporary.name))
        self.window = build_window(self.paths, start_hardware_scan=False)
        self.window.show()
        APP.processEvents()

    def tearDown(self) -> None:
        self.window.tasks.cancel_all()
        wait_until(lambda: not self.window.tasks.busy)
        self.window.close()
        self.window.deleteLater()
        APP.processEvents()
        # Windows holds the rotating log open until its handler is closed.
        import logging
        for handler in logging.getLogger("stoneglass").handlers[:]:
            handler.close()
            logging.getLogger("stoneglass").removeHandler(handler)
        self.temporary.cleanup()

    def test_initialization_navigation_and_honest_unavailable_state(self) -> None:
        self.assertEqual(self.window.windowTitle(), "Stoneglass")
        self.assertEqual(self.window.pages.count(), 4)
        self.assertEqual(
            [self.window.navigation.item(i).text() for i in range(4)],
            ["Generate", "Models", "Gallery", "Settings"],
        )
        for index in range(4):
            self.window.navigation.setCurrentRow(index)
            self.assertEqual(self.window.pages.currentIndex(), index)
        self.assertFalse(self.window.generate_page.generate_button.isEnabled())
        self.assertTrue((self.paths.log_dir / "stoneglass.log").exists())
        self.assertNotIn("torch", sys.modules)
        self.assertNotIn("diffusers", sys.modules)

    def test_preferences_autosave_and_prompts_remain_session_only(self) -> None:
        page = self.window.generate_page
        page.positive_prompt.setPlainText("PRIVATE_POSITIVE_PROMPT")
        page.negative_prompt.setPlainText("PRIVATE_NEGATIVE_PROMPT")
        page.steps.setValue(41)
        wait_until(lambda: self.paths.settings_file.exists())
        data = json.loads(self.paths.settings_file.read_text())
        self.assertEqual(data["generation"]["steps"], 41)
        self.window.close()
        self.window.show()
        for path in (self.paths.settings_file, self.paths.log_dir / "stoneglass.log"):
            self.assertNotIn("PRIVATE_", path.read_text(encoding="utf-8"))
        restored = SettingsStore(self.paths.settings_file).load()
        self.assertEqual(restored.generation.steps, 41)

    def test_hardware_result_reaches_settings_page(self) -> None:
        hardware = Mock()
        hardware.detect.return_value = HardwareReport("Windows 11", (
            GpuInfo("AMD Radeon RX 9060 XT", GpuVendor.AMD),
        ))
        self.window.services = ApplicationServices(
            self.paths, self.window.services.settings, hardware,
        )
        self.window.navigation.setCurrentRow(3)
        QTest.mouseClick(self.window.settings_page.rescan_button, Qt.MouseButton.LeftButton)
        wait_until(lambda: not self.window.tasks.busy)
        fields = self.window.settings_page.gpu_fields[0]
        self.assertEqual(fields.name.text(), "AMD Radeon RX 9060 XT")
        self.assertEqual(fields.vendor.text(), "AMD")
        self.assertEqual(fields.driver.text(), "Unknown")
        self.assertEqual(self.window.settings_page.operating_system.text(), "Windows 11")
        self.assertEqual(self.window.settings_page.vram_status.text(), "Not reported")
        self.assertIn("Not configured", self.window.settings_page.compute_backend.text())
        self.assertTrue(self.window.settings_page.rescan_button.isEnabled())

    def test_sidebar_keyboard_toggle_preserves_navigation_and_focus(self) -> None:
        self.window.activateWindow()
        self.window.sidebar.toggle_button.setFocus()
        APP.processEvents()
        expanded_width = self.window.sidebar.width()
        QTest.keyClick(self.window.sidebar.toggle_button, Qt.Key.Key_Space)
        self.assertTrue(self.window.sidebar.collapsed)
        self.assertLess(self.window.sidebar.width(), expanded_width)
        self.assertTrue(self.window.sidebar.toggle_button.hasFocus())
        self.assertEqual(self.window.sidebar.toggle_button.accessibleName(), "Expand navigation")
        self.navigation_select_collapsed()
        QTest.keyClick(self.window, Qt.Key.Key_B, Qt.KeyboardModifier.ControlModifier)
        self.assertFalse(self.window.sidebar.collapsed)
        self.assertEqual(self.window.sidebar.width(), expanded_width)
        self.assertEqual(self.window.pages.currentIndex(), 1)
        self.assertEqual(self.window.navigation.item(1).text(), "Models")

    def navigation_select_collapsed(self) -> None:
        self.window.navigation.setFocus()
        QTest.keyClick(self.window.navigation, Qt.Key.Key_Down)
        self.assertEqual(self.window.pages.currentIndex(), 1)
        self.assertEqual(self.window.navigation.item(1).text(), "")
        self.assertEqual(self.window.navigation.item(1).toolTip(), "Models")
        self.assertEqual(
            self.window.navigation.item(1).data(Qt.ItemDataRole.AccessibleTextRole), "Models"
        )

    def test_sidebar_and_custom_dimensions_restore_after_restart(self) -> None:
        self.window.sidebar.set_collapsed(True)
        page = self.window.generate_page
        page.width.setValue(832)
        page.height.setValue(640)
        wait_until(lambda: self.paths.settings_file.exists())
        self.assertTrue(json.loads(self.paths.settings_file.read_text())["sidebar_collapsed"])
        self.window.close()
        self.window.deleteLater()
        APP.processEvents()
        self.window = build_window(self.paths, start_hardware_scan=False)
        self.window.show()
        self.assertTrue(self.window.sidebar.collapsed)
        self.assertEqual((self.window.generate_page.width.value(), self.window.generate_page.height.value()), (832, 640))
        self.assertEqual(self.window.generate_page.dimensions.resolution_preset.currentText(), "Custom")
        self.assertEqual(self.window.generate_page.dimensions.aspect_ratio.currentText(), "Custom")

    def test_preset_dimensions_persist_and_restore_matching_controls(self) -> None:
        dimensions = self.window.generate_page.dimensions
        dimensions.resolution_preset.setCurrentIndex(dimensions.resolution_preset.findData(QSize(768, 1024)))
        self.window.save_preferences()
        restored = SettingsStore(self.paths.settings_file).load()
        self.assertEqual((restored.generation.width, restored.generation.height), (768, 1024))
        dimensions.aspect_ratio.setCurrentIndex(dimensions.aspect_ratio.findData(QSize(16, 9)))
        self.window.save_preferences()
        restored = SettingsStore(self.paths.settings_file).load()
        self.assertEqual(restored.generation.width * 9, restored.generation.height * 16)
        self.window.close()
        self.window.deleteLater()
        APP.processEvents()
        self.window = build_window(self.paths, start_hardware_scan=False)
        self.window.show()
        self.assertEqual(self.window.generate_page.dimensions.aspect_ratio.currentData(), QSize(16, 9))
        self.assertEqual(self.window.generate_page.dimensions.resolution_preset.currentText(), "Custom")

    def test_small_window_both_sidebar_states_have_no_horizontal_scroll(self) -> None:
        self.window.resize(960, 640)
        for collapsed in (False, True):
            self.window.sidebar.set_collapsed(collapsed)
            for index in range(4):
                self.window.navigation.setCurrentRow(index)
                APP.processEvents()
                for scroll in self.window.pages.currentWidget().findChildren(QScrollArea):
                    self.assertEqual(scroll.horizontalScrollBar().maximum(), 0, (collapsed, index))
            for page_index, button in (
                (0, self.window.generate_page.generate_button), (3, self.window.settings_page.save_button),
            ):
                self.window.navigation.setCurrentRow(page_index)
                APP.processEvents()
                origin = button.mapTo(self.window, QPoint(0, 0))
                self.assertTrue(self.window.rect().contains(origin))
                self.assertTrue(self.window.rect().contains(origin + button.rect().bottomRight()))
        self.assertFalse(self.window.generate_page.generate_button.isEnabled())
        self.assertTrue(self.window.generate_page.preview.toolbar.isHidden())
        self.assertEqual(self.window.generate_page.preview.toolbar.actions(), [])

    def test_long_storage_paths_wrap_without_horizontal_scrolling(self) -> None:
        self.window.resize(960, 640)
        self.window.navigation.setCurrentRow(3)
        path = "D:\\" + "nested-folder\\" * 35 + "Stoneglass"
        value = self.window.settings_page.path_values["Application data"]
        value.setText(path)
        APP.processEvents()
        self.assertEqual(value.text(), path)
        self.assertTrue(value.wordWrap())
        self.assertGreater(value.height(), value.fontMetrics().lineSpacing())
        self.assertEqual(self.window.settings_page.scroll.horizontalScrollBar().maximum(), 0)

    def test_settings_field_captions_do_not_overlap_values(self) -> None:
        self.window.resize(960, 640)
        page = self.window.settings_page
        page.show_hardware(HardwareReport("Windows 11", (GpuInfo("AMD Radeon", GpuVendor.AMD, "32.0.1"),)))
        self.window.navigation.setCurrentRow(3)
        for collapsed in (False, True):
            self.window.sidebar.set_collapsed(collapsed)
            APP.processEvents()
            for caption in page.findChildren(QLabel):
                value = caption.buddy()
                if value is not None:
                    caption_right = caption.mapTo(page, QPoint(caption.width(), 0)).x()
                    value_left = value.mapTo(page, QPoint(0, 0)).x()
                    self.assertLess(caption_right, value_left, caption.text())

    def test_multiple_gpu_fields_refresh_without_stale_adapters(self) -> None:
        page = self.window.settings_page
        page.show_hardware(HardwareReport("Windows 11", (
            GpuInfo("AMD Radeon", GpuVendor.AMD, "32.0.1"),
            GpuInfo("NVIDIA RTX 3090", GpuVendor.NVIDIA, "56.2"),
        )))
        self.assertEqual([fields.name.text() for fields in page.gpu_fields], ["AMD Radeon", "NVIDIA RTX 3090"])
        self.assertEqual(page.gpu_fields[1].driver.text(), "56.2")
        page.show_hardware(HardwareReport("Windows 11", warning="GPU detection failed."))
        self.assertEqual(page.gpu_fields, [])
        self.assertIn("failed", page.hardware_details.text())

    def test_preset_selections_change_only_dimensions(self) -> None:
        page = self.window.generate_page
        page.positive_prompt.setPlainText("An unchanged positive prompt\nwith a second line.")
        page.negative_prompt.setPlainText("An unchanged negative prompt.")
        page.steps.setValue(47)
        page.guidance.setValue(4.5)
        page.seed.setValue(9182)
        for collapsed in (False, True):
            self.window.sidebar.set_collapsed(collapsed)
            for combo, choices in (
                (page.dimensions.resolution_preset, RESOLUTION_PRESETS),
                (page.dimensions.aspect_ratio, ASPECT_RATIOS),
            ):
                for choice in choices:
                    with self.subTest(collapsed=collapsed, selector=combo.accessibleName(), choice=choice):
                        before = self.window.current_preferences()
                        positive, negative = page.positive_prompt.toPlainText(), page.negative_prompt.toPlainText()
                        index = combo.findData(QSize(*choice))
                        combo.setCurrentIndex(index)
                        combo.activated.emit(index)
                        after = self.window.current_preferences()
                        self.assertEqual(replace(after, generation=replace(
                            after.generation, width=before.generation.width, height=before.generation.height,
                        )), before)
                        self.assertEqual(page.positive_prompt.toPlainText(), positive)
                        self.assertEqual(page.negative_prompt.toPlainText(), negative)

    def test_navigation_and_sidebar_transitions_preserve_selected_dimensions(self) -> None:
        page = self.window.generate_page
        for size in ((512, 512), (832, 640), (1920, 1280)):
            page.width.setValue(size[0])
            page.height.setValue(size[1])
            resolution = page.dimensions.resolution_preset.currentText()
            aspect = page.dimensions.aspect_ratio.currentText()
            for collapsed in (False, True, False):
                self.window.sidebar.set_collapsed(collapsed)
                for index in (1, 2, 3, 0):
                    self.window.navigation.setCurrentRow(index)
                    APP.processEvents()
                    self.assertEqual((page.width.value(), page.height.value()), size)
                    self.assertEqual(page.dimensions.resolution_preset.currentText(), resolution)
                    self.assertEqual(page.dimensions.aspect_ratio.currentText(), aspect)

    def test_large_manual_dimensions_restore_without_applying_aspect_budget(self) -> None:
        for collapsed in (False, True):
            self.window.sidebar.set_collapsed(collapsed)
            self.window.generate_page.width.setValue(1920)
            self.window.generate_page.height.setValue(1280)
            self.window.close()
            self.window.deleteLater()
            APP.processEvents()
            self.window = build_window(self.paths, start_hardware_scan=False)
            self.window.show()
            page = self.window.generate_page
            self.assertEqual((page.width.value(), page.height.value()), (1920, 1280))
            self.assertEqual(page.dimensions.aspect_ratio.currentText(), "3:2")
            self.assertEqual(page.dimensions.resolution_preset.currentText(), "Custom")
            self.assertEqual(self.window.sidebar.collapsed, collapsed)

    def test_save_button_writes_settings(self) -> None:
        self.window.navigation.setCurrentRow(3)
        QTest.mouseClick(self.window.settings_page.save_button, Qt.MouseButton.LeftButton)
        self.assertTrue(self.paths.settings_file.exists())
        self.assertEqual(self.window.settings_page.save_status.text(), "Preferences saved locally.")

    def test_close_waits_without_blocking_or_destroying_running_thread(self) -> None:
        started = Event()
        release = Event()

        def operation(context: WorkerContext) -> None:
            started.set()
            release.wait(timeout=2)
            context.check_cancelled()

        self.window.tasks.start("close-test", operation)
        wait_until(started.is_set)
        self.assertFalse(self.window.close())
        self.assertTrue(self.window.isVisible())
        release.set()
        wait_until(lambda: not self.window.tasks.busy and not self.window.isVisible())
