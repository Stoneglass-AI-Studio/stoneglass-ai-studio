# SPDX-License-Identifier: GPL-3.0-or-later
"""Local worker memory counters. No monitoring service or telemetry."""

import ctypes
from ctypes import wintypes
from typing import Any


def host_memory() -> dict[str, int]:
    """Current working/private bytes and lifetime peaks from this worker process."""
    class Counters(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("faults", wintypes.DWORD),
                    *((name, ctypes.c_size_t) for name in (
                        "peak_working", "working", "peak_paged", "paged", "peak_nonpaged",
                        "nonpaged", "pagefile", "peak_pagefile", "private"))]
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    function = ctypes.WinDLL("psapi", use_last_error=True).GetProcessMemoryInfo
    function.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
    function.restype = wintypes.BOOL
    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    if not function(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
        raise OSError("Worker memory counters are unavailable.")
    return {"working_set_bytes": counters.working, "private_bytes": counters.private,
            "lifetime_peak_working_set_bytes": counters.peak_working,
            "lifetime_peak_commit_bytes": counters.peak_pagefile}


def runtime_memory(torch: Any, index: int) -> dict[str, Any]:
    return {"gpu_allocated_bytes": torch.cuda.memory_allocated(index),
            "gpu_reserved_bytes": torch.cuda.memory_reserved(index),
            "gpu_peak_allocated_bytes": torch.cuda.max_memory_allocated(index),
            "gpu_peak_reserved_bytes": torch.cuda.max_memory_reserved(index),
            "host": host_memory()}
