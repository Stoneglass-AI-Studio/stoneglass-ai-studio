# SPDX-License-Identifier: GPL-3.0-or-later

"""Small, theme-consistent navigation glyphs, independent of app branding."""

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap


def navigation_icon(name: str) -> QIcon:
    pixmap = QPixmap(40, 40)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(2, 2)
    painter.setPen(QPen(QColor("#b6c9d4"), 1.5, Qt.PenStyle.SolidLine,
                        Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    if name == "Generate":
        painter.drawRoundedRect(QRectF(3, 3, 14, 14), 2, 2)
        painter.drawLine(6, 10, 14, 10)
        painter.drawLine(10, 6, 10, 14)
    elif name == "Models":
        painter.drawRoundedRect(QRectF(3, 3, 14, 5), 1, 1)
        painter.drawRoundedRect(QRectF(3, 12, 14, 5), 1, 1)
    elif name == "Gallery":
        for x, y in ((3, 3), (12, 3), (3, 12), (12, 12)):
            painter.drawRoundedRect(QRectF(x, y, 5, 5), 1, 1)
    elif name == "Settings":
        for y, knob in ((5, 7), (10, 13), (15, 8)):
            painter.drawLine(3, y, 17, y)
            painter.fillRect(QRectF(knob - 1.5, y - 2, 3, 4), QColor("#111318"))
            painter.drawRoundedRect(QRectF(knob - 1.5, y - 2, 3, 4), 0.5, 0.5)
    painter.end()
    pixmap.setDevicePixelRatio(2)
    return QIcon(pixmap)
