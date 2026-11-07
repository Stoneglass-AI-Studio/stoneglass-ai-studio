# SPDX-License-Identifier: GPL-3.0-or-later

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QSizePolicy, QVBoxLayout, QWidget


def label(text: str, style: str = "", wrap: bool = False) -> QLabel:
    widget = QLabel(text)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setObjectName(style)
    widget.setWordWrap(wrap)
    if wrap:
        widget.setMinimumWidth(0)
        widget.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    return widget


def selectable_value(text: str, name: str) -> QLabel:
    widget = label(text, "value", True)
    widget.setTextInteractionFlags(
        Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard
    )
    widget.setAccessibleName(name)
    widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    widget.setToolTip(text)
    return widget


def page_header(layout: QVBoxLayout, title: str, subtitle: str) -> None:
    layout.addWidget(label(title, "pageTitle"))
    layout.addWidget(label(subtitle, "subtitle", True))
    layout.addSpacing(16)


def card(parent: QWidget | None = None) -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame(parent)
    frame.setObjectName("card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(20, 20, 20, 20)
    layout.setSpacing(12)
    return frame, layout
