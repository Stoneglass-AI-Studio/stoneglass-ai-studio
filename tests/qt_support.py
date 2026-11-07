# SPDX-License-Identifier: GPL-3.0-or-later

import os
from collections.abc import Callable
from time import monotonic

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtTest import QTest

from stoneglass.app import create_application

# Retain the QApplication wrapper for the lifetime of all test modules.
APP = create_application(["stoneglass-tests"])
APP.setQuitOnLastWindowClosed(False)


def wait_until(condition: Callable[[], bool], timeout_ms: int = 3000) -> None:
    deadline = monotonic() + timeout_ms / 1000
    while not condition():
        if monotonic() >= deadline:
            raise AssertionError("Timed out waiting for Qt task")
        QTest.qWait(10)
    APP.processEvents()
