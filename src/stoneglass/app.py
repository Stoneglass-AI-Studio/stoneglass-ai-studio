# SPDX-License-Identifier: GPL-3.0-or-later

"""Composition root: creates storage, services, and the desktop shell."""

import logging
import sys
from importlib.resources import files
from types import TracebackType

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication, QMessageBox

from stoneglass import __version__
from stoneglass.services.application import ApplicationServices
from stoneglass.services.logging_setup import configure_logging
from stoneglass.services.paths import AppPaths
from stoneglass.ui.main_window import MainWindow

logger = logging.getLogger(__name__)


def create_application(argv: list[str] | None = None) -> QApplication:
    existing = QApplication.instance()
    if isinstance(existing, QApplication):
        return existing
    app = QApplication(sys.argv if argv is None else argv)
    app.setApplicationName("Stoneglass")
    app.setOrganizationName("Stoneglass")
    app.setApplicationVersion(__version__)
    app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI", 10))
    palette = QPalette()
    for role, color in (
        (QPalette.ColorRole.Window, "#17191f"),
        (QPalette.ColorRole.WindowText, "#e7e9f0"),
        (QPalette.ColorRole.Base, "#14171d"),
        (QPalette.ColorRole.AlternateBase, "#1e2129"),
        (QPalette.ColorRole.Text, "#e7e9f0"),
        (QPalette.ColorRole.Button, "#303743"),
        (QPalette.ColorRole.ButtonText, "#e7e9f0"),
        (QPalette.ColorRole.Highlight, "#3f7166"),
        (QPalette.ColorRole.HighlightedText, "#ffffff"),
    ):
        palette.setColor(role, QColor(color))
    app.setPalette(palette)
    app.setStyleSheet(files("stoneglass.ui").joinpath("theme.qss").read_text(encoding="utf-8"))
    return app


def build_window(
    paths: AppPaths | None = None, *, start_hardware_scan: bool = True,
) -> MainWindow:
    resolved_paths = paths or AppPaths.discover()
    resolved_paths.ensure()
    configure_logging(resolved_paths.log_dir)
    logger.info("Starting Stoneglass %s; inference is unavailable", __version__)
    return MainWindow(
        ApplicationServices.create(resolved_paths), start_hardware_scan=start_hardware_scan
    )


def install_exception_handler(window: MainWindow) -> None:
    def report(
        kind: type[BaseException], exception: BaseException, traceback: TracebackType | None,
    ) -> None:
        if issubclass(kind, KeyboardInterrupt):
            window.close()
            return
        logger.critical("Unhandled application error", exc_info=(kind, exception, traceback))
        dialog = QMessageBox(window)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.setIcon(QMessageBox.Icon.Critical)
        dialog.setWindowTitle("Stoneglass encountered an error")
        dialog.setText("An unexpected error occurred. Check the local log for details.")
        dialog.setInformativeText(str(window.services.paths.log_dir / "stoneglass.log"))
        dialog.open()

    sys.excepthook = report


def main() -> int:
    app = create_application()
    try:
        window = build_window()
    except Exception as exc:
        logger.exception("Application initialization failed")
        QMessageBox.critical(
            None, "Stoneglass could not start",
            f"Application initialization failed: {exc}\n"
            "Check that your local application data directory is writable. "
            "STONEGLASS_DATA_DIR can select a different directory.",
        )
        return 1
    install_exception_handler(window)
    window.show()
    return app.exec()
