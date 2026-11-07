# SPDX-License-Identifier: GPL-3.0-or-later
"""Hold Windows read handles that deny concurrent writes/replacement during loading."""

import ctypes
import os
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any

from stoneglass.inference.errors import ErrorCode, InferenceError
from stoneglass.inference.resources import CONFIG_FILES, SDXLManifest, strict_local


class ResourceLease(AbstractContextManager["ResourceLease"]):
    def __init__(self, manifest: SDXLManifest) -> None:
        self._paths = (manifest.checkpoint, *(manifest.config_directory / name for name in CONFIG_FILES))
        self._handles: list[Any] = []

    def __enter__(self) -> "ResourceLease":
        if os.name != "nt":
            raise InferenceError(ErrorCode.INVALID_RESOURCES, "The initial adapter requires Windows resource read leases.")
        from ctypes import wintypes
        self._kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self._kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                            ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        self._kernel.CreateFileW.restype = wintypes.HANDLE
        self._kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        try:
            for path in self._paths:
                strict_local(path)
                handle = self._kernel.CreateFileW(str(path), 0x80000000, 1, None, 3, 0x80, None)
                if handle == ctypes.c_void_p(-1).value:
                    raise InferenceError(ErrorCode.INVALID_RESOURCES,
                                         "A local SDXL resource is being modified or cannot be opened read-only. Close its editor and retry.")
                self._handles.append(handle)
        except BaseException:
            self.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, *args: Any) -> None:
        while self._handles:
            self._kernel.CloseHandle(self._handles.pop())
