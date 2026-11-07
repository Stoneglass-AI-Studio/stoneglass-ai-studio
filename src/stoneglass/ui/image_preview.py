# SPDX-License-Identifier: GPL-3.0-or-later

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QSizePolicy, QStackedWidget, QToolBar, QVBoxLayout, QWidget,
)

from stoneglass.ui.components import label


class ImagePreview(QWidget):
    """Empty preview shell; no image loading or generation is implemented.

    A future canvas/editor can be added to viewport. Real zoom/fit/save/edit
    actions belong in toolbar, shown only when those features are implemented.
    status can then report image dimensions and zoom without changing this view.
    """

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
            ("PHASE 1 · PREVIEW", "eyebrow"),
            ("No image to preview", "previewTitle"),
            ("Your generated image will appear here.\nImage generation is unavailable in this phase.", "muted"),
        ):
            message = label(text, style, True)
            message.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.addWidget(message)
        empty.addStretch()
        self.viewport.addWidget(self.empty_state)
        frame_layout.addWidget(self.viewport)
        layout.addWidget(frame, 1)
        self.status = label("No model loaded · No image generated", "muted", True)
        layout.addWidget(self.status)
