# SPDX-License-Identifier: GPL-3.0-or-later
"""Local-only library policy; legacy isolation helpers are experimental only.

These settings are not an OS sandbox. Normal inference never invokes the retained
AppContainer inspection/authorization helpers below.
"""

import ctypes
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from stoneglass.inference.errors import ErrorCode, InferenceError

OFFLINE_FLAGS = {
    "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
    "HF_HUB_DISABLE_TELEMETRY": "1", "DO_NOT_TRACK": "1",
    "HF_HUB_DISABLE_IMPLICIT_TOKEN": "1", "HF_HUB_DISABLE_XET": "1",
}
ISOLATION_MESSAGE = (
    "The OS-enforced offline worker is not provisioned and verified. "
    "Approve the scoped Windows isolation setup and its network tests before loading models. "
    "No inference dependencies were imported and nothing was downloaded."
)


def offline_environment(root: Path) -> dict[str, str]:
    """Fresh child environment; do not inherit tokens, proxies, PYTHONPATH or experimental flags."""
    result = {key: os.environ[key] for key in ("SystemRoot", "WINDIR", "SYSTEMDRIVE") if key in os.environ}
    result.update(OFFLINE_FLAGS)
    result.update({
        "PATH": str(Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32"),
        "HF_HOME": str(root / "huggingface"), "HF_HUB_CACHE": str(root / "huggingface/hub"),
        "XDG_CACHE_HOME": str(root / "cache"), "TEMP": str(root / "tmp"), "TMP": str(root / "tmp"),
        "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1",
        "TOKENIZERS_PARALLELISM": "false",
    })
    return result


def assert_offline_policy() -> None:
    """Recheck library flags at operation boundaries, including after imports."""
    if any(os.environ.get(key) != value for key, value in OFFLINE_FLAGS.items()):
        raise InferenceError(ErrorCode.OFFLINE_POLICY,
                             "Required offline library settings are missing. Restart the local worker.")


def assert_library_policy() -> None:
    """Startup-only check: policy must precede all inference-library imports."""
    assert_offline_policy()
    if any(
        name in sys.modules for name in ("torch", "diffusers", "transformers", "huggingface_hub")
    ):
        raise InferenceError(ErrorCode.OFFLINE_POLICY,
                             "Offline policy must be established before inference-library imports.")


@dataclass(frozen=True)
class IsolationInspection:
    windows: bool
    appcontainer: bool
    verified: bool = False
    reason: str = "Scoped AppContainer provisioning and network verification require approval."


def inspect_isolation() -> IsolationInspection:
    """Read the current token only. Never interpret AppContainer membership as full attestation."""
    if sys.platform != "win32":
        return IsolationInspection(False, False, reason="No verified offline launcher for this operating system.")
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    advapi.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    advapi.OpenProcessToken.restype = wintypes.BOOL
    advapi.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                          wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    advapi.GetTokenInformation.restype = wintypes.BOOL
    token = wintypes.HANDLE()
    if not advapi.OpenProcessToken(kernel.GetCurrentProcess(), 0x0008, ctypes.byref(token)):
        return IsolationInspection(True, False, reason="Process token inspection failed.")
    try:
        value, length = wintypes.DWORD(), wintypes.DWORD()
        if not advapi.GetTokenInformation(token, 29, ctypes.byref(value), ctypes.sizeof(value), ctypes.byref(length)):
            return IsolationInspection(True, False, reason="AppContainer token inspection failed.")
        return IsolationInspection(True, bool(value.value))
    finally:
        kernel.CloseHandle(token)


def require_verified_isolation() -> None:
    # No unreviewed AppContainer token, environment variable, CLI option or
    # socket patch can bypass this gate. There is intentionally no permissive
    # subprocess fallback. Replace only after native provisioning/verification.
    raise InferenceError(ErrorCode.ISOLATION_UNAVAILABLE, ISOLATION_MESSAGE)
