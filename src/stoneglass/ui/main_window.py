# SPDX-License-Identifier: GPL-3.0-or-later

import logging
from dataclasses import asdict

from PySide6.QtCore import QTimer, Qt, Slot
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QHBoxLayout, QMainWindow, QMessageBox, QStackedWidget, QWidget,
)

from stoneglass.domain.hardware import HardwareReport
from stoneglass.domain.settings import AppSettings
from stoneglass.infrastructure.workers import TaskManager, WorkerContext
from stoneglass.services.application import ApplicationServices
from stoneglass.services.settings import SettingsError
from stoneglass.ui.components import label
from stoneglass.ui.generate_page import GeneratePage
from stoneglass.ui.placeholder_page import PlaceholderPage
from stoneglass.ui.settings_page import SettingsPage
from stoneglass.ui.sidebar import Sidebar

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(
        self, services: ApplicationServices, *, start_hardware_scan: bool = True,
    ) -> None:
        super().__init__()
        self.services = services
        self._closing = False
        self._scan_active = False
        self.settings = services.settings.load()
        self.tasks = TaskManager(self)
        self.tasks.idle.connect(self._on_idle)
        self.setWindowTitle("Stoneglass")
        self.setMinimumSize(960, 640)
        self.resize(self.settings.window_width, self.settings.window_height)
        if self.settings.maximized:
            self.setWindowState(Qt.WindowState.WindowMaximized)

        central = QWidget()
        shell = QHBoxLayout(central)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)
        self.sidebar = Sidebar(self.settings.sidebar_collapsed)
        self.navigation = self.sidebar.navigation
        shell.addWidget(self.sidebar)

        self.pages = QStackedWidget()
        self.generate_page = GeneratePage(self.settings.generation)
        self.models_page = PlaceholderPage(
            "Models", "Your future local model library.", "No models loaded",
            "Model discovery, loading, and management are not implemented in Phase 1. "
            "Stoneglass has not downloaded any models. The future Python inference engine "
            "will be part of Stoneglass itself.",
        )
        self.gallery_page = PlaceholderPage(
            "Gallery", "A home for images created on your machine.", "Nothing here yet",
            "Image generation, gallery indexing, and image browsing are unavailable in Phase 1. "
            "Your preview remains empty until a future inference backend produces an image.",
        )
        self.settings_page = SettingsPage(services.paths)
        for page in (
            self.generate_page, self.models_page, self.gallery_page, self.settings_page,
        ):
            self.pages.addWidget(page)
        shell.addWidget(self.pages, 1)
        self.setCentralWidget(central)
        self.navigation.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.navigation.setCurrentRow(0)

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(600)
        self._save_timer.timeout.connect(self.save_preferences)
        self.generate_page.preferences_changed.connect(self._schedule_save)
        self.sidebar.collapsed_changed.connect(self._schedule_save)
        self.settings_page.save_requested.connect(self.save_preferences)
        self.settings_page.rescan_requested.connect(self.scan_hardware)

        self.statusBar().showMessage("Ready · Inference unavailable in Phase 1")
        self.statusBar().addPermanentWidget(label("OFFLINE · LOCAL", "muted"))
        if services.settings.warning:
            self.settings_page.save_status.setText(services.settings.warning)
            self.statusBar().showMessage(services.settings.warning)
        if start_hardware_scan:
            QTimer.singleShot(0, self.scan_hardware)
        else:
            self.settings_page.hardware_details.setText("Hardware detection has not run.")

    @Slot()
    def _schedule_save(self) -> None:
        self._save_timer.start()

    def current_preferences(self) -> AppSettings:
        geometry = self.normalGeometry() if self.isMaximized() else self.geometry()
        return AppSettings.from_dict({
            "window_width": geometry.width(), "window_height": geometry.height(),
            "maximized": self.isMaximized(),
            "sidebar_collapsed": self.sidebar.collapsed,
            "generation": asdict(self.generate_page.preferences()),
        })

    @Slot()
    def save_preferences(self) -> None:
        self._save_timer.stop()
        try:
            self.settings = self.current_preferences()
            self.services.settings.save(self.settings)
            self.settings_page.save_status.setText("Preferences saved locally.")
        except SettingsError as exc:
            self.settings_page.save_status.setText(str(exc))
            self.statusBar().showMessage(str(exc))

    @Slot()
    def scan_hardware(self) -> None:
        if self._closing or self._scan_active:
            return
        self._scan_active = True
        self.settings_page.rescan_button.setEnabled(False)
        self.settings_page.hardware_details.setText("Detecting Windows display adapters…")
        self.statusBar().showMessage("Detecting hardware in the background…")

        def detect(context: WorkerContext) -> HardwareReport:
            context.report_progress(0, "Reading Windows display adapters")
            result = self.services.hardware.detect()
            context.check_cancelled()
            return result

        handle = self.tasks.start("hardware-detection", detect)
        handle.succeeded.connect(self._hardware_ready)
        handle.failed.connect(self._hardware_failed)
        handle.finished.connect(self._scan_finished)

    @Slot(object)
    def _hardware_ready(self, report: HardwareReport) -> None:
        self.settings_page.show_hardware(report)
        self.statusBar().showMessage(report.summary)

    @Slot(str)
    def _hardware_failed(self, message: str) -> None:
        self.settings_page.hardware_details.setText(
            f"Hardware detection failed: {message}\nLogs: {self.services.paths.log_dir}"
        )
        self.statusBar().showMessage("Hardware detection failed. See Settings for details.")

    @Slot()
    def _scan_finished(self) -> None:
        self._scan_active = False
        self.settings_page.rescan_button.setEnabled(True)

    @Slot()
    def _on_idle(self) -> None:
        if self._closing:
            QTimer.singleShot(0, self.close)

    def closeEvent(self, event: QCloseEvent) -> None:
        self._save_timer.stop()
        if self.tasks.busy:
            self._closing = True
            self.tasks.cancel_all()
            self.centralWidget().setEnabled(False)
            self.statusBar().showMessage("Closing · Waiting for the background task to finish…")
            event.ignore()
            return
        self.save_preferences()
        warning = self.settings_page.save_status.text()
        if warning != "Preferences saved locally.":
            # Make a failed final save readable even when the user never opened Settings.
            QMessageBox.warning(self, "Preferences could not be saved", warning)
        logger.info("Application window closed")
        event.accept()
