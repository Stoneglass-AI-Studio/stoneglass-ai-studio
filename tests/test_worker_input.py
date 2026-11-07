# SPDX-License-Identifier: GPL-3.0-or-later
"""Bounded polling tests independent of native libraries and GPU hardware."""

import ctypes
import unittest
from threading import Event, Thread
from types import SimpleNamespace
from unittest.mock import Mock

from stoneglass.inference.pipe_input import WorkerPipeInput


class WorkerInputTests(unittest.TestCase):
    def make_input(self, data):
        pipe = WorkerPipeInput.__new__(WorkerPipeInput)
        pipe._pending, pipe._eof, pipe._stopped, pipe._handle = bytearray(), False, Event(), 123
        remaining = bytearray(data)
        def peek(handle, buffer, size, read, available, left):
            available._obj.value = len(remaining)
            return True
        def read(handle, buffer, size, count, overlap):
            self.assertGreater(size, 0)
            self.assertLessEqual(size, len(remaining))  # Never issue an idle blocking read.
            chunk = bytes(remaining[:size]); del remaining[:size]
            ctypes.memmove(buffer, chunk, len(chunk)); count._obj.value = len(chunk)
            return True
        pipe._kernel = SimpleNamespace(PeekNamedPipe=Mock(side_effect=peek), ReadFile=Mock(side_effect=read))
        return pipe

    def test_frames_and_partial_lines_preserve_bytes_with_bounded_reads(self):
        pipe = self.make_input(b"first\nsecond\n")
        self.assertEqual(pipe.readline(100), b"first\n")
        self.assertEqual(pipe.readline(3), b"sec")
        self.assertEqual(pipe.readline(100), b"ond\n")
        self.assertEqual(pipe._kernel.ReadFile.call_count, 1)

    def test_oversized_line_returns_at_bound_for_protocol_rejection(self):
        pipe = self.make_input(b"x" * 100 + b"\n")
        self.assertEqual(pipe.readline(10), b"x" * 10)
        self.assertLessEqual(len(pipe._pending), 10)

    def test_idle_close_releases_reader_without_reading_or_closing_os_handle(self):
        pipe = self.make_input(b"")
        entered, result = Event(), []
        original = pipe._kernel.PeekNamedPipe.side_effect
        def peek(*args): entered.set(); return original(*args)
        pipe._kernel.PeekNamedPipe.side_effect = peek
        thread = Thread(target=lambda: result.append(pipe.readline(100)), daemon=True)
        thread.start()
        self.assertTrue(entered.wait(2))
        pipe.close(); thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(result, [b""])
        pipe._kernel.ReadFile.assert_not_called()

    def test_unbounded_reads_are_rejected(self):
        pipe = self.make_input(b"input\n")
        for bound in (-1, 0):
            with self.assertRaises(ValueError): pipe.readline(bound)
        pipe._kernel.ReadFile.assert_not_called()
