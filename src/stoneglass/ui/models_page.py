# SPDX-License-Identifier: GPL-3.0-or-later
"""Explicit local checkpoint/manifest selection; no discovery or acquisition."""
from pathlib import Path
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QLineEdit, QPushButton, QScrollArea, QVBoxLayout, QWidget
from stoneglass.inference.contracts import ModelSpec
from stoneglass.ui.components import card, label, page_header


class ModelsPage(QWidget):
    selection_changed = Signal()
    validate_requested = Signal()
    cancel_requested = Signal()

    def __init__(self, checkpoint: str, manifest: str, default_manifest: Path) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 26, 30, 24)
        page_header(layout, "Models", "Select a complete local model and its matching resources.")
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        content = QWidget(); column = QVBoxLayout(content)
        column.setContentsMargins(0, 12, 0, 12)
        panel, fields = card()
        fields.addWidget(label("Local SDXL model", "sectionTitle", True))
        fields.addWidget(label("Initial profile: AlbedoBase XL v3.1-Large with the reviewed local bundle, on RX 9060 XT. Other profiles are unavailable. Nothing is downloaded.", "muted", True))
        self.checkpoint = QLineEdit(checkpoint)
        default = str(default_manifest) if default_manifest.is_file() else ""
        self.manifest = QLineEdit(manifest or default)
        for title, field, slot in (("Checkpoint (.safetensors)", self.checkpoint, self.browse_checkpoint),
                                   ("Matching local resource manifest (.json)", self.manifest, self.browse_manifest)):
            caption = label(title, "fieldLabel"); caption.setBuddy(field)
            fields.addWidget(caption)
            row = QHBoxLayout(); field.setReadOnly(True); field.setAccessibleName(title)
            field.setPlaceholderText("Choose a local file…")
            row.addWidget(field, 1)
            button = QPushButton("Browse…"); button.setAccessibleName("Browse " + title)
            button.clicked.connect(slot); row.addWidget(button)
            fields.addLayout(row)
        self.selection_name = label("", "value", True)
        self.selection_name.setTextFormat(Qt.TextFormat.PlainText)
        fields.addWidget(self.selection_name)
        self.status = label("Select a checkpoint, then validate the local resources and runtime.", "muted", True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        fields.addWidget(self.status)
        actions = QHBoxLayout()
        self.validate_button = QPushButton("Validate model")
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setEnabled(False)
        self.validate_button.clicked.connect(self.validate_requested)
        self.cancel_button.clicked.connect(self.cancel_requested)
        actions.addWidget(self.validate_button); actions.addWidget(self.cancel_button); actions.addStretch()
        fields.addLayout(actions)
        column.addWidget(panel); column.addStretch(); scroll.setWidget(content); layout.addWidget(scroll)
        self.checkpoint.textChanged.connect(self._changed)
        self.manifest.textChanged.connect(self._changed)
        self._changed()

    def _changed(self) -> None:
        self.selection_name.setText(Path(self.checkpoint.text()).name if self.checkpoint.text() else "No model selected")
        self.selection_changed.emit()

    def browse_checkpoint(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select local SDXL checkpoint", self.checkpoint.text(), "Safetensors checkpoints (*.safetensors)")
        if path: self.checkpoint.setText(path)

    def browse_manifest(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select matching local SDXL manifest", self.manifest.text(), "Local resource manifests (*.json)")
        if path: self.manifest.setText(path)

    def selection(self) -> ModelSpec:
        checkpoint = Path(self.checkpoint.text())
        return ModelSpec(checkpoint.stem, checkpoint, resource_manifest=Path(self.manifest.text()))
