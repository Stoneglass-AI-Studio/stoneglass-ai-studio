# SPDX-License-Identifier: GPL-3.0-or-later

import tempfile
import unittest
from pathlib import Path
from hashlib import sha256
from importlib.resources import files

from PySide6.QtGui import QImage

from qt_support import APP
from stoneglass.ui.sidebar import Sidebar


class SidebarBrandingTests(unittest.TestCase):
    def test_packaged_project_mark_is_available(self) -> None:
        sidebar = Sidebar()
        self.addCleanup(sidebar.deleteLater)
        self.assertTrue(sidebar.has_logomark)
        self.assertFalse(sidebar.logomark.pixmap().isNull())
        self.assertEqual(sidebar.brand_name.text(), "Stoneglass")

    def test_missing_asset_has_text_fallback_in_both_states(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            sidebar = Sidebar(logo_path=Path(temporary) / "missing.jpg")
            sidebar.show()
            self.addCleanup(sidebar.deleteLater)
            self.assertFalse(sidebar.has_logomark)
            self.assertTrue(sidebar.brand_name.isVisible())
            self.assertFalse(sidebar.logomark.isVisible())
            sidebar.set_collapsed(True)
            self.assertFalse(sidebar.brand_name.isVisible())
            self.assertTrue(sidebar.logomark.isVisible())
            self.assertEqual(sidebar.logomark.text(), "SG")
            sidebar.close()
            APP.processEvents()

    def test_approved_logomark_integrity_and_aspect_at_sidebar_size(self) -> None:
        data = files("stoneglass.ui").joinpath("assets/stoneglass-logomark.jpg").read_bytes()
        self.assertEqual(sha256(data).hexdigest(),
                         "58bd470aadbbd755d01038e9e8dc26d1672ea69ce8f6a69a74309fdbf738898e")
        original = QImage.fromData(data)
        sidebar = Sidebar()
        self.addCleanup(sidebar.deleteLater)
        for collapsed in (False, True):
            sidebar.set_collapsed(collapsed)
            rendered = sidebar.logomark.pixmap()
            # QLabel exposes the current screen's rendering of its 2x source.
            self.assertGreaterEqual(rendered.devicePixelRatio(), sidebar.devicePixelRatioF())
            self.assertLessEqual(rendered.width() / rendered.devicePixelRatio(), sidebar.logomark.width())
            self.assertLessEqual(rendered.height() / rendered.devicePixelRatio(), sidebar.logomark.height())
            # Allow at most one pixel of rounding when fitting the raster.
            self.assertLessEqual(abs(rendered.width() * original.height()
                                     - rendered.height() * original.width()),
                                 max(original.width(), original.height()))

    def test_reference_png_integrity_and_dimensions(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        references = {
            "Stoneglass_Banner.png": (
                "a50dd686c07c875938ccaed2d2d872b3fe316051ea770140609b34b5c1f958e5",
                (2170, 725),
            ),
            "Stoneglass_Logo.png": (
                "5aceaf3b42edf4443c3b847ad500965d48e750f1749627a0deb0b10501d41585",
                (2172, 724),
            ),
        }
        for name, (expected_hash, dimensions) in references.items():
            with self.subTest(asset=name):
                data = (project_root / name).read_bytes()
                self.assertEqual(sha256(data).hexdigest(), expected_hash)
                image = QImage.fromData(data, "PNG")
                self.assertFalse(image.isNull())
                self.assertEqual((image.width(), image.height()), dimensions)
