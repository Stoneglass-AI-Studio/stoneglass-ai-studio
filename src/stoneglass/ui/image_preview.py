# SPDX-License-Identifier: GPL-3.0-or-later

from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtGui import QImage, QPixmap, QResizeEvent
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QSizePolicy, QStackedWidget, QToolBar, QVBoxLayout, QWidget, QLabel,
)

from stoneglass.ui.components import label
from stoneglass.services.generation import GenerationOutcome
from stoneglass.services.images import ImageInfo


class ImageCanvas(QLabel):
    def __init__(self) -> None:
        super().__init__()
        self.original = QPixmap()
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.setMinimumSize(1, 1)
    def sizeHint(self) -> QSize: return QSize(320, 320)
    def fit(self) -> None:
        if not self.original.isNull():
            self.setPixmap(self.original.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event); self.fit()


class ImagePreview(QWidget):
    """Fit-to-window display; the full-resolution PNG remains untouched on disk."""
    export_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumWidth(250)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 0, 0, 0)
        layout.setSpacing(14)
        header = QHBoxLayout()
        header.addWidget(label("Image preview", "sectionTitle"))
        header.addStretch()
        header.addWidget(label("LOCAL ONLY", "badge"))
        layout.addLayout(header)
        self.toolbar = QToolBar("Preview actions", self)
        self.toolbar.setMovable(False)
        self.toolbar.hide()
        self.save_action = self.toolbar.addAction("Save PNG…")
        self.save_action.setEnabled(False)
        self.save_action.triggered.connect(self.export_requested)
        layout.addWidget(self.toolbar)
        frame = QFrame()
        frame.setObjectName("preview")
        frame_layout = QVBoxLayout(frame)
        frame_layout.setContentsMargins(0, 0, 0, 0)
        self.viewport = QStackedWidget()
        self.viewport.setObjectName("previewViewport")
        self.viewport.setAccessibleName("Image preview viewport")
        self.empty_state = QWidget()
        self.empty_state.setObjectName("previewEmpty")
        empty = QVBoxLayout(self.empty_state)
        empty.setContentsMargins(24, 24, 24, 24)
        empty.setSpacing(12)
        empty.addStretch()
        for text, style in (
            ("LOCAL IMAGE PREVIEW", "eyebrow"),
            ("No image to preview", "previewTitle"),
            ("Select a supported local model to begin.\nYour validated image will appear here.", "muted"),
        ):
            message = label(text, style, True)
            message.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.addWidget(message)
        empty.addStretch()
        self.viewport.addWidget(self.empty_state)
        self.canvas = ImageCanvas()
        self.canvas.setAccessibleName("Generated image, fitted to preview")
        self.viewport.addWidget(self.canvas)
        frame_layout.addWidget(self.viewport)
        layout.addWidget(frame, 1)
        self.status = label("No model loaded · No image generated", "muted", True)
        layout.addWidget(self.status)
        self.image_info: ImageInfo | None = None

    def show_outcome(self, outcome: GenerationOutcome) -> None:
        image = QImage(str(outcome.image.path))
        if image.isNull() or (image.width(), image.height()) != (outcome.image.width, outcome.image.height):
            raise ValueError("The saved PNG cannot be decoded for preview. Its original file was preserved.")
        self.canvas.original = QPixmap.fromImage(image)
        self.image_info = outcome.image
        self.viewport.setCurrentWidget(self.canvas)
        self.canvas.fit()
        self.toolbar.show(); self.save_action.setEnabled(True)
        self.status.setText(f"{image.width()} × {image.height()} · Seed {outcome.result.seed} · PNG saved locally")
        self.status.setToolTip(str(outcome.image.path))
