# SPDX-License-Identifier: GPL-3.0-or-later

from PySide6.QtWidgets import QVBoxLayout, QWidget

from stoneglass.ui.components import card, label, page_header


class PlaceholderPage(QWidget):
    def __init__(self, title: str, subtitle: str, heading: str, detail: str) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 26, 30, 24)
        layout.setSpacing(12)
        page_header(layout, title, subtitle)
        frame, content = card()
        content.setSpacing(14)
        content.addWidget(label("PLANNED · UNAVAILABLE", "eyebrow"))
        content.addWidget(label(heading, "sectionTitle"))
        content.addWidget(label(detail, "muted", True))
        layout.addWidget(frame)
        layout.addStretch()
