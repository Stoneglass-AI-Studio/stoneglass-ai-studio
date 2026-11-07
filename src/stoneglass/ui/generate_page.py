# SPDX-License-Identifier: GPL-3.0-or-later

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDoubleSpinBox, QGridLayout, QPlainTextEdit,
    QPushButton, QScrollArea, QSpinBox, QSplitter, QVBoxLayout, QWidget, QHBoxLayout, QProgressBar,
)

from stoneglass.domain.settings import GenerationSettings
from stoneglass.inference.contracts import GenerationRequest, InferenceStatus
from stoneglass.ui.components import card, label, page_header
from stoneglass.ui.dimension_controls import DimensionControls
from stoneglass.ui.image_preview import ImagePreview


class GeneratePage(QWidget):
    preferences_changed = Signal()
    select_model_requested = Signal()

    def __init__(self, settings: GenerationSettings) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 26, 30, 24)
        layout.setSpacing(10)
        page_header(layout, "Generate", "A private space to turn ideas into images.")
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(360)
        self.controls_scroll = scroll
        panel = QWidget()
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(0, 0, 12, 0)
        panel_layout.setSpacing(12)
        controls = QWidget()
        column = QVBoxLayout(controls)
        column.setContentsMargins(0, 0, 6, 0)
        column.setSpacing(16)
        prompt_card, prompts = card()
        prompts.addWidget(label("Describe your image", "sectionTitle", True))
        self.positive_prompt = self._prompt(
            prompts, "Positive prompt", "Describe the subject, setting, lighting, and style…", 104
        )
        self.negative_prompt = self._prompt(
            prompts, "Negative prompt", "Describe what you want to exclude…", 68
        )
        column.addWidget(prompt_card)
        settings_card, settings_layout = card()
        settings_layout.addWidget(label("Generation settings", "sectionTitle", True))
        settings_layout.addWidget(label(
            "Saved locally · SDXL profile: batch 1, up to 1,048,576 pixels.", "muted", True
        ))
        form = QGridLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(6)
        self.dimensions = DimensionControls(settings.width, settings.height)
        self.width = self.dimensions.width
        self.height = self.dimensions.height
        self.dimensions.preferences_changed.connect(self.preferences_changed)
        settings_layout.addWidget(self.dimensions)
        settings_layout.addWidget(label("256–2048 px · 64 px increments", "muted", True))
        self.steps = self._spin(1, 150, settings.steps)
        self.guidance = QDoubleSpinBox()
        self.guidance.setRange(0, 30)
        self.guidance.setDecimals(1)
        self.guidance.setSingleStep(0.5)
        self.guidance.setValue(settings.guidance)
        self.guidance.setKeyboardTracking(False)
        self.seed = self._spin(-1, 2_147_483_647, settings.seed)
        self.seed.setSpecialValueText("Random (−1)")
        for index, (title, control) in enumerate((
            ("Steps", self.steps), ("Guidance", self.guidance), ("Seed", self.seed),
        )):
            row, col = divmod(index, 2)
            caption = label(title, "fieldLabel")
            caption.setBuddy(control)
            control.setAccessibleName(title)
            span = 2 if title == "Seed" else 1
            form.addWidget(caption, row * 2, col, 1, span)
            form.addWidget(control, row * 2 + 1, col, 1, span)
            control.valueChanged.connect(self.preferences_changed)
        settings_layout.addLayout(form)
        column.addWidget(settings_card)
        column.addStretch()
        scroll.setWidget(controls)
        panel_layout.addWidget(scroll, 1)
        self.model_status = label("Select and validate a local model in Models.", "muted", True)
        panel_layout.addWidget(self.model_status)
        self.select_model_button = QPushButton("Select model…")
        self.select_model_button.clicked.connect(self.select_model_requested)
        panel_layout.addWidget(self.select_model_button)
        self.generate_button = QPushButton("Generate")
        self.generate_button.setObjectName("primary")
        self.generate_button.setMinimumHeight(46)
        self.generate_button.setEnabled(False)
        self.generate_button.setShortcut("Ctrl+Return")
        self.generate_button.setToolTip("Select and validate a supported local model first.")
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setEnabled(False)
        actions = QHBoxLayout()
        actions.addWidget(self.generate_button, 1); actions.addWidget(self.cancel_button)
        panel_layout.addLayout(actions)
        self.progress_bar = QProgressBar()
        self.progress_bar.setAccessibleName("Generation progress")
        self.progress_bar.hide()
        panel_layout.addWidget(self.progress_bar)
        self.inference_status = label("", "muted", True)
        self.inference_status.setTextFormat(Qt.TextFormat.PlainText)
        self.model_status.setTextFormat(Qt.TextFormat.PlainText)
        panel_layout.addWidget(self.inference_status)
        self.set_inference_status(InferenceStatus())
        splitter.addWidget(panel)

        self.preview = ImagePreview()
        splitter.addWidget(self.preview)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 5)
        splitter.setSizes([400, 560])
        layout.addWidget(splitter, 1)

    @staticmethod
    def _prompt(layout: QVBoxLayout, title: str, placeholder: str, height: int) -> QPlainTextEdit:
        caption = label(title, "fieldLabel")
        layout.addWidget(caption)
        editor = QPlainTextEdit()
        editor.setPlaceholderText(placeholder)
        editor.setFixedHeight(height)
        editor.setAccessibleName(title)
        caption.setBuddy(editor)
        layout.addWidget(editor)
        return editor

    @staticmethod
    def _spin(minimum: int, maximum: int, value: int, step: int = 1) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(minimum, maximum)
        spin.setSingleStep(step)
        spin.setValue(value)
        spin.setKeyboardTracking(False)
        return spin

    def preferences(self) -> GenerationSettings:
        # Typing arbitrary dimensions is allowed; normalize to multiples of 64.
        return GenerationSettings.from_dict({
            "width": self.width.value(), "height": self.height.value(),
            "steps": self.steps.value(), "guidance": self.guidance.value(),
            "seed": self.seed.value(),
        })

    def generation_request(self, model_id: str | None = None) -> GenerationRequest:
        """Snapshot session-only prompts for the controller; never persist them."""
        return GenerationRequest(
            self.positive_prompt.toPlainText(), self.negative_prompt.toPlainText(),
            self.preferences(), model_id,
        )

    def set_inference_status(self, status: InferenceStatus) -> None:
        # Engine status alone never authorizes generation. The controller also
        # requires a matching validated selection, request and idle task state.
        if status.error:
            self.inference_status.setText(status.error.message)
        elif not self.inference_status.text():
            self.inference_status.setText("Ready for local model selection.")
