# SPDX-License-Identifier: GPL-3.0-or-later

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDoubleSpinBox, QGridLayout, QPlainTextEdit,
    QPushButton, QScrollArea, QSpinBox, QSplitter, QVBoxLayout, QWidget,
)

from stoneglass.domain.settings import GenerationSettings
from stoneglass.ui.components import card, label, page_header
from stoneglass.ui.dimension_controls import DimensionControls
from stoneglass.ui.image_preview import ImagePreview


class GeneratePage(QWidget):
    preferences_changed = Signal()

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
            "Saved locally for a future inference backend.", "muted", True
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
        self.generate_button = QPushButton("Generate · unavailable")
        self.generate_button.setObjectName("primary")
        self.generate_button.setMinimumHeight(46)
        self.generate_button.setEnabled(False)
        self.generate_button.setToolTip("Inference is not implemented in Phase 1.")
        panel_layout.addWidget(self.generate_button)
        panel_layout.addWidget(label(
            "Phase 1 · Model loading and image generation are not available yet.", "muted", True
        ))
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
