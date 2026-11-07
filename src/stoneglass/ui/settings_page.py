# SPDX-License-Identifier: GPL-3.0-or-later

from dataclasses import dataclass

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from stoneglass.domain.hardware import HardwareReport
from stoneglass.services.paths import AppPaths
from stoneglass.ui.components import card, label, page_header, selectable_value


@dataclass(frozen=True)
class GpuFields:
    name: QLabel
    vendor: QLabel
    driver: QLabel


class SettingsPage(QWidget):
    rescan_requested = Signal()
    save_requested = Signal()

    def __init__(self, paths: AppPaths) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 26, 30, 24)
        page_header(layout, "Settings", "Your machine. Your workspace. Your data.")
        scroll = QScrollArea()
        self.scroll = scroll
        scroll.setWidgetResizable(True)
        body = QWidget()
        column = QVBoxLayout(body)
        column.setContentsMargins(0, 0, 12, 0)
        column.setSpacing(16)

        hardware, content = card()
        header = QHBoxLayout()
        header.addWidget(label("Hardware", "sectionTitle"))
        header.addStretch()
        self.rescan_button = QPushButton("Refresh hardware")
        self.rescan_button.clicked.connect(self.rescan_requested)
        header.addWidget(self.rescan_button)
        content.addLayout(header)
        self.hardware_details = label("Hardware detection has not run.", "muted", True)
        content.addWidget(self.hardware_details)
        system = QGridLayout()
        self.operating_system = self._field(system, 0, "Operating system", "Not detected")
        self.compute_backend = self._field(system, 1, "Compute backend", "Not configured · Phase 1")
        self.vram_status = self._field(system, 2, "VRAM", "Not reported")
        content.addLayout(system)
        self.gpu_container = QWidget()
        self.gpu_container.setObjectName("form")
        self.gpu_layout = QVBoxLayout(self.gpu_container)
        self.gpu_layout.setContentsMargins(0, 0, 0, 0)
        self.gpu_layout.setSpacing(14)
        self.gpu_fields: list[GpuFields] = []
        content.addWidget(self.gpu_container)
        content.addWidget(label(
            "Adapter detection does not confirm inference support. VRAM is not inferred from "
            "Windows inventory because its memory field is unreliable for modern GPUs.", "muted", True
        ))
        column.addWidget(hardware)

        storage, content = card()
        content.addWidget(label("Local storage & privacy", "sectionTitle"))
        self.path_values: dict[str, QLabel] = {}
        for name, path in (
            ("Application data", paths.root), ("Settings file", paths.settings_file), ("Logs", paths.log_dir),
        ):
            content.addWidget(label(name, "fieldLabel"))
            value = selectable_value(str(path), name)
            self.path_values[name] = value
            content.addWidget(value)
        content.addSpacing(4)
        privacy = QGridLayout()
        self._field(privacy, 0, "Preferences", "Window, sidebar, and generation preferences stay on this device.")
        self._field(privacy, 1, "Prompts", "Session only. Never written to settings or application logs.")
        self._field(privacy, 2, "Privacy", "No accounts, telemetry, cloud services, or model downloads.")
        content.addLayout(privacy)
        column.addWidget(storage)

        future, content = card()
        content.addWidget(label("Inference configuration · unavailable", "sectionTitle"))
        content.addWidget(label(
            "GPU-specific compute runtimes, model paths, memory policies, and sampler selection "
            "are reserved for a later phase. No inference backend is currently available.", "muted", True
        ))
        column.addWidget(future)
        column.addStretch()
        scroll.setWidget(body)
        layout.addWidget(scroll)
        actions = QHBoxLayout()
        actions.setSpacing(14)
        self.save_button = QPushButton("Save preferences")
        self.save_button.clicked.connect(self.save_requested)
        actions.addWidget(self.save_button)
        self.save_status = label("", "muted", True)
        actions.addWidget(self.save_status, 1)
        layout.addLayout(actions)

    @staticmethod
    def _field(layout: QGridLayout, row: int, name: str, text: str) -> QLabel:
        layout.setHorizontalSpacing(16)
        layout.setVerticalSpacing(12)
        layout.setColumnStretch(1, 1)
        caption = label(name, "fieldLabel", True)
        caption.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        caption.setFixedWidth(128)
        value = selectable_value(text, name)
        caption.setBuddy(value)
        layout.addWidget(caption, row, 0)
        layout.addWidget(value, row, 1)
        return value

    def show_hardware(self, report: HardwareReport) -> None:
        self.operating_system.setText(report.platform)
        self.operating_system.setToolTip(report.platform)
        count = len(report.gpus)
        self.hardware_details.setText(report.warning or (
            f"{count} display {'adapter' if count == 1 else 'adapters'} detected." if count
            else "No display adapters reported by Windows."
        ))
        while self.gpu_layout.count():
            item = self.gpu_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().hide()
                item.widget().deleteLater()
        self.gpu_fields.clear()
        for index, gpu in enumerate(report.gpus, start=1):
            group = QWidget()
            group.setObjectName("form")
            group_layout = QVBoxLayout(group)
            group_layout.setContentsMargins(0, 0, 0, 0)
            group_layout.setSpacing(12)
            if len(report.gpus) > 1:
                group_layout.addWidget(label(f"Display adapter {index}", "sectionTitle"))
            fields = QGridLayout()
            name = self._field(fields, 0, "GPU name", gpu.name)
            vendor = self._field(fields, 1, "Vendor", gpu.vendor.value)
            driver = self._field(fields, 2, "Driver version", gpu.driver_version)
            self.gpu_fields.append(GpuFields(name, vendor, driver))
            group_layout.addLayout(fields)
            self.gpu_layout.addWidget(group)
