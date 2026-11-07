# SPDX-License-Identifier: GPL-3.0-or-later
"""Bounded, cancellable Windows pipe input that never blocks waiting for bytes."""

import ctypes
from ctypes import wintypes
from threading import Event


class WorkerPipeInput:
    """The process owns stdin. This view never closes or duplicates its handle.

    Blocking background input reproduced a native-extension startup stall in the
    reviewed Windows stack. Poll before short reads; idle waits own no I/O lock.
    """
    def __init__(self) -> None:
        self._kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self._kernel.GetStdHandle.argtypes = [wintypes.DWORD]
        self._kernel.GetStdHandle.restype = wintypes.HANDLE
        self._kernel.ReadFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
                                         ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
        self._kernel.ReadFile.restype = wintypes.BOOL
        self._kernel.PeekNamedPipe.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
                                               ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
        self._kernel.PeekNamedPipe.restype = wintypes.BOOL
        self._handle = self._kernel.GetStdHandle(wintypes.DWORD(-10))
        self._pending = bytearray()
        self._eof = False
        self._stopped = Event()

    def close(self) -> None:
        """Stop this view, leaving the process-owned standard handle alone."""
        self._stopped.set()

    def readline(self, limit: int) -> bytes:
        if limit <= 0:
            raise ValueError("Pipe reads require a positive bound.")
        while True:
            newline = self._pending.find(b"\n", 0, limit)
            if newline >= 0 or len(self._pending) >= limit or self._eof or self._stopped.is_set():
                length = newline + 1 if newline >= 0 else min(len(self._pending), limit)
                value = bytes(self._pending[:length])
                del self._pending[:length]
                return value
            available = wintypes.DWORD()
            if not self._kernel.PeekNamedPipe(self._handle, None, 0, None, ctypes.byref(available), None):
                if ctypes.get_last_error() not in (109, 232):
                    raise OSError("Worker input pipe inspection failed.")
                self._eof = True
                continue
            if not available.value:
                self._stopped.wait(0.02)
                continue
            buffer = ctypes.create_string_buffer(min(available.value, 65536, limit - len(self._pending)))
            read = wintypes.DWORD()
            if not self._kernel.ReadFile(self._handle, buffer, len(buffer), ctypes.byref(read), None):
                if ctypes.get_last_error() not in (109, 232):  # Broken/closed owned pipe.
                    raise OSError("Worker input pipe read failed.")
                self._eof = True
            elif read.value == 0:
                self._eof = True
            else:
                self._pending.extend(buffer.raw[:read.value])
