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
from stoneglass.infrastructure.inference_tasks import InferenceTasks
from stoneglass.services.application import ApplicationServices
from stoneglass.services.settings import SettingsError
from stoneglass.ui.components import label
from stoneglass.ui.generate_page import GeneratePage
from stoneglass.ui.placeholder_page import PlaceholderPage
from stoneglass.ui.settings_page import SettingsPage
from stoneglass.ui.sidebar import Sidebar
from stoneglass.ui.models_page import ModelsPage
from stoneglass.ui.generation_controller import GenerationController

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
        self.inference_tasks = InferenceTasks(services.inference, self.tasks, self)
        self.inference_tasks.status_changed.connect(self.generate_page.set_inference_status)
        self.models_page = ModelsPage(self.settings.model_path, self.settings.resource_manifest_path,
                                     services.project / ".local-data/sdxl-bundles/base-initial/manifest.json")
        self.gallery_page = PlaceholderPage(
            "Gallery", "A home for images created on your machine.", "Nothing here yet",
            "Gallery indexing and browsing are not available yet. Generated PNGs remain in local storage and can be exported from Generate.",
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
        self.generate_page.select_model_requested.connect(lambda: self.navigation.setCurrentRow(1))
        self.generation_controller = GenerationController(self.inference_tasks, self.tasks, self.generate_page, self.models_page, self)
        self.generation_controller.status_message.connect(self.statusBar().showMessage)

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(600)
        self._save_timer.timeout.connect(self.save_preferences)
        self.generate_page.preferences_changed.connect(self._schedule_save)
        self.sidebar.collapsed_changed.connect(self._schedule_save)
        self.generation_controller.selection_changed.connect(self._schedule_save)
        self.generation_controller.selection_changed.connect(self._show_runtime_readiness)
        self.tasks.idle.connect(self._show_runtime_readiness)
        self.settings_page.save_requested.connect(self.save_preferences)
        self.settings_page.rescan_requested.connect(self.scan_hardware)

        self.statusBar().showMessage("Ready · Select and validate a local model in Models")
        self.statusBar().addPermanentWidget(label("OFFLINE · LOCAL", "muted"))
        if services.settings.warning:
            self.settings_page.save_status.setText(services.settings.warning)
            self.statusBar().showMessage(services.settings.warning)
        if start_hardware_scan:
            QTimer.singleShot(0, self.scan_hardware)
        else:
            self.settings_page.hardware_details.setText("Hardware detection has not run.")

    @Slot()
    def _show_runtime_readiness(self) -> None:
        ready = self.generation_controller.ready
        backend = {"rocm": "ROCm", "cuda": "CUDA", "cpu": "CPU"}[ready.runtime.kind.value] if ready else ""
        self.settings_page.compute_backend.setText(
            f"Validated {backend} · {ready.runtime.name} · Worker closes after each generation"
            if ready else "Not validated · Select a local model in Models"
        )

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
            "model_path": self.models_page.checkpoint.text(),
            "resource_manifest_path": self.models_page.manifest.text(),
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

    @Slot(str)
    def _inference_shutdown_failed(self, message: str) -> None:
        self._closing = False
        self.centralWidget().setEnabled(True)
        self.statusBar().showMessage(f"{message} Close the window again to retry cleanup.")

    def closeEvent(self, event: QCloseEvent) -> None:
        self._save_timer.stop()
        if self.tasks.busy:
            self._closing = True
            self.tasks.cancel_all()
            self.centralWidget().setEnabled(False)
            self.statusBar().showMessage("Closing · Waiting for the background task to finish…")
            event.ignore()
            return
        if self.services.inference.requires_cleanup:
            self._closing = True
            self.centralWidget().setEnabled(False)
            self.statusBar().showMessage("Closing · Releasing inference resources…")
            handle = self.inference_tasks.shutdown()
            handle.failed.connect(self._inference_shutdown_failed)
            event.ignore()
            return
        self.save_preferences()
        warning = self.settings_page.save_status.text()
        if warning != "Preferences saved locally.":
            # Make a failed final save readable even when the user never opened Settings.
            QMessageBox.warning(self, "Preferences could not be saved", warning)
        logger.info("Application window closed")
        event.accept()
