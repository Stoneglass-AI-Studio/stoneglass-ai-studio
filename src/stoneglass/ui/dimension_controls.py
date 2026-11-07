# SPDX-License-Identifier: GPL-3.0-or-later

from PySide6.QtCore import QSignalBlocker, QSize, Signal, Slot
from PySide6.QtWidgets import QComboBox, QGridLayout, QSizePolicy, QSpinBox, QWidget

from stoneglass.domain.dimensions import (
    ASPECT_RATIOS, DIMENSION_STEP, MAX_DIMENSION, MIN_DIMENSION,
    RESOLUTION_PRESETS, dimensions_for_aspect, matching_aspect,
)
from stoneglass.ui.components import label


class DimensionControls(QWidget):
    preferences_changed = Signal()

    def __init__(self, width: int, height: int) -> None:
        super().__init__()
        self.setObjectName("form")
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(12)
        layout.setVerticalSpacing(6)
        self.resolution_preset = self._combo("Resolution preset")
        for size in RESOLUTION_PRESETS:
            self.resolution_preset.addItem(f"{size[0]} × {size[1]}", QSize(*size))
        self.aspect_ratio = self._combo("Aspect ratio")
        for ratio in ASPECT_RATIOS:
            self.aspect_ratio.addItem(f"{ratio[0]}:{ratio[1]}", QSize(*ratio))
        self.aspect_ratio.setToolTip(
            "Choose an exact ratio on the 64 px grid, keeping pixel count as close as possible, "
            "up to 1,048,576 pixels (1024 × 1024 area). Manual sizes may be larger."
        )
        self.width = self._dimension(width)
        self.height = self._dimension(height)
        for row, controls in enumerate((
            (("Resolution preset", self.resolution_preset), ("Aspect ratio", self.aspect_ratio)),
            (("Width (px)", self.width), ("Height (px)", self.height)),
        )):
            for column, (name, control) in enumerate(controls):
                caption = label(name, "fieldLabel", True)
                caption.setBuddy(control)
                control.setAccessibleName(name)
                layout.addWidget(caption, row * 2, column)
                layout.addWidget(control, row * 2 + 1, column)
        self.resolution_preset.currentIndexChanged.connect(self._apply_resolution)
        self.aspect_ratio.currentIndexChanged.connect(self._apply_aspect)
        # Activation also covers choosing the currently displayed ratio after
        # manually setting a larger matching size. Handlers ignore no-op repeats.
        self.resolution_preset.activated.connect(self._apply_resolution)
        self.aspect_ratio.activated.connect(self._apply_aspect)
        self.width.valueChanged.connect(self._manual_changed)
        self.height.valueChanged.connect(self._manual_changed)
        self._sync_presets()

    @staticmethod
    def _combo(name: str) -> QComboBox:
        combo = QComboBox()
        combo.setAccessibleName(name)
        combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        combo.setMinimumContentsLength(6)
        combo.setMinimumWidth(0)
        combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        combo.addItem("Custom", None)
        # Custom is a derived state; manual editing selects it automatically.
        combo.model().item(0).setEnabled(False)
        return combo

    @staticmethod
    def _dimension(value: int) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(MIN_DIMENSION, MAX_DIMENSION)
        spin.setSingleStep(DIMENSION_STEP)
        spin.setValue(value)
        spin.setKeyboardTracking(False)
        spin.setToolTip("256–2048 pixels, in increments of 64. Manual values round down to the grid.")
        return spin

    def _set_dimensions(self, width: int, height: int) -> None:
        with QSignalBlocker(self.width), QSignalBlocker(self.height):
            self.width.setValue(width // DIMENSION_STEP * DIMENSION_STEP)
            self.height.setValue(height // DIMENSION_STEP * DIMENSION_STEP)
        self._sync_presets()
        self.preferences_changed.emit()

    @Slot(int)
    def _apply_resolution(self, index: int) -> None:
        size = self.resolution_preset.itemData(index)
        if size is not None and (size.width(), size.height()) != (self.width.value(), self.height.value()):
            self._set_dimensions(size.width(), size.height())

    @Slot(int)
    def _apply_aspect(self, index: int) -> None:
        ratio = self.aspect_ratio.itemData(index)
        if ratio is not None:
            size = dimensions_for_aspect(
                self.width.value(), self.height.value(), (ratio.width(), ratio.height())
            )
            if size != (self.width.value(), self.height.value()):
                self._set_dimensions(*size)

    @Slot(int)
    def _manual_changed(self, value: int) -> None:
        self._set_dimensions(self.width.value(), self.height.value())

    def _sync_presets(self) -> None:
        size = (self.width.value(), self.height.value())
        with QSignalBlocker(self.resolution_preset), QSignalBlocker(self.aspect_ratio):
            self.resolution_preset.setCurrentIndex(max(0, self.resolution_preset.findData(QSize(*size))))
            ratio = matching_aspect(*size)
            self.aspect_ratio.setCurrentIndex(self.aspect_ratio.findData(QSize(*ratio)) if ratio else 0)
