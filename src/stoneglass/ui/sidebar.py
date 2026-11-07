# SPDX-License-Identifier: GPL-3.0-or-later

"""Compact navigation with project-supplied branding and a text fallback."""

from importlib.resources import files
from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal, Slot
from PySide6.QtGui import QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QListWidget, QListWidgetItem, QSizePolicy,
    QToolButton, QVBoxLayout, QWidget,
)

from stoneglass import __version__
from stoneglass.ui.components import label
from stoneglass.ui.navigation_icons import navigation_icon


class Sidebar(QFrame):
    collapsed_changed = Signal(bool)
    EXPANDED_WIDTH = 192
    COLLAPSED_WIDTH = 68

    def __init__(self, collapsed: bool = False, *, logo_path: Path | None = None) -> None:
        super().__init__()
        self.setObjectName("sidebar")
        self._collapsed = collapsed
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 20, 10, 16)
        layout.setSpacing(14)

        brand = QWidget()
        brand.setObjectName("sidebarBrand")
        brand_row = QHBoxLayout(brand)
        brand_row.setContentsMargins(2, 0, 2, 0)
        brand_row.setSpacing(8)
        self.logomark = label("", "logomark")
        self.logomark.setFixedSize(34, 36)
        self.logomark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.logomark.setAccessibleName("Stoneglass logomark")
        self.logomark.setToolTip("Stoneglass")
        pixmap = QPixmap()
        try:
            data = (logo_path.read_bytes() if logo_path is not None else
                    files("stoneglass.ui").joinpath("assets/stoneglass-logomark.jpg").read_bytes())
            pixmap.loadFromData(data)
        except OSError:
            pass  # A missing optional asset uses clean text branding.
        self.has_logomark = not pixmap.isNull()
        if self.has_logomark:
            scaled = pixmap.scaled(
                68, 72, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
            )
            scaled.setDevicePixelRatio(2)
            self.logomark.setPixmap(scaled)
        else:
            self.logomark.setText("SG")
            self.logomark.setAccessibleName("Stoneglass text placeholder")
        brand_row.addWidget(self.logomark)
        self.brand_name = label("Stoneglass", "brand")
        self.brand_name.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        brand_row.addWidget(self.brand_name)
        brand_row.addStretch()
        layout.addWidget(brand)

        self.toggle_button = QToolButton()
        self.toggle_button.setObjectName("sidebarToggle")
        self.toggle_button.setCheckable(True)
        self.toggle_button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.toggle_button.setMinimumHeight(34)
        self.toggle_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout.addWidget(self.toggle_button)

        self.navigation = QListWidget()
        self.navigation.setObjectName("navigation")
        self.navigation.setAccessibleName("Main navigation")
        self.navigation.setAccessibleDescription("Use the arrow keys to choose a workspace.")
        self.navigation.setIconSize(QSize(20, 20))
        self.navigation.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        for name in ("Generate", "Models", "Gallery", "Settings"):
            item = QListWidgetItem(navigation_icon(name), name)
            item.setData(Qt.ItemDataRole.UserRole, name)
            item.setData(Qt.ItemDataRole.AccessibleTextRole, name)
            item.setToolTip(name)
            self.navigation.addItem(item)
        layout.addWidget(self.navigation, 1)
        self.footer = label(f"PHASE 1\nv{__version__} · Local & private", "sidebarFooter", True)
        layout.addWidget(self.footer)
        self.toggle_button.toggled.connect(self.set_collapsed)
        self.shortcut = QShortcut(QKeySequence("Ctrl+B"), self)
        self.shortcut.activated.connect(self.toggle_button.toggle)
        self.set_collapsed(collapsed, notify=False)

    @property
    def collapsed(self) -> bool:
        return self._collapsed

    @Slot(bool)
    def set_collapsed(self, collapsed: bool, *, notify: bool = True) -> None:
        changed = self._collapsed != collapsed
        self._collapsed = collapsed
        self.setFixedWidth(self.COLLAPSED_WIDTH if collapsed else self.EXPANDED_WIDTH)
        self.brand_name.setVisible(not collapsed)
        self.logomark.setVisible(self.has_logomark or collapsed)
        self.footer.setVisible(not collapsed)
        self.toggle_button.setChecked(collapsed)
        action = "Expand navigation" if collapsed else "Collapse navigation"
        self.toggle_button.setText("›" if collapsed else "‹  Collapse")
        self.toggle_button.setAccessibleName(action)
        self.toggle_button.setToolTip(f"{action} (Ctrl+B)")
        for row in range(self.navigation.count()):
            item = self.navigation.item(row)
            item.setText("" if collapsed else item.data(Qt.ItemDataRole.UserRole))
        if changed and notify:
            self.collapsed_changed.emit(collapsed)
