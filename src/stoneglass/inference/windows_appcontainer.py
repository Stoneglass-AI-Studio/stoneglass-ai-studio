# SPDX-License-Identifier: GPL-3.0-or-later
"""Explicit development AppContainer primitive; never auto-provisions or enables inference.

Only new staged resources may receive grants from the separate provisioning tool.
This module changes no firewall policy, filesystem ACL or capability assignment.
"""

import ctypes as c
from ctypes import wintypes as w
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, BinaryIO

from stoneglass.inference.errors import ErrorCode, InferenceError

PREFIX = "Stoneglass.OfflineInference.Dev."


class SecurityAttributes(c.Structure):
    _fields_ = [("length", w.DWORD), ("descriptor", c.c_void_p), ("inherit", w.BOOL)]


class SecurityCapabilities(c.Structure):
    _fields_ = [("sid", c.c_void_p), ("capabilities", c.c_void_p), ("count", w.DWORD), ("reserved", w.DWORD)]


class SidAttributes(c.Structure):
    _fields_ = [("sid", c.c_void_p), ("attributes", w.DWORD)]


class StartupInfo(c.Structure):
    _fields_ = [("cb", w.DWORD), ("reserved", w.LPWSTR), ("desktop", w.LPWSTR), ("title", w.LPWSTR),
                *((name, w.DWORD) for name in ("x", "y", "xsize", "ysize", "xchars", "ychars", "fill", "flags")),
                ("show", w.WORD), ("reserved_size", w.WORD), ("reserved_bytes", c.c_void_p),
                ("stdin", w.HANDLE), ("stdout", w.HANDLE), ("stderr", w.HANDLE)]


class StartupInfoEx(c.Structure):
    _fields_ = [("info", StartupInfo), ("attributes", c.c_void_p)]


class ProcessInfo(c.Structure):
    _fields_ = [("process", w.HANDLE), ("thread", w.HANDLE), ("pid", w.DWORD), ("tid", w.DWORD)]


class BasicJobLimits(c.Structure):
    _fields_ = [("process_time", c.c_int64), ("job_time", c.c_int64), ("flags", w.DWORD),
                ("min_working_set", c.c_size_t), ("max_working_set", c.c_size_t),
                ("active_processes", w.DWORD), ("affinity", c.c_size_t),
                ("priority", w.DWORD), ("scheduling", w.DWORD)]


class ExtendedJobLimits(c.Structure):
    _fields_ = [("basic", BasicJobLimits), ("io", c.c_uint64 * 6),
                ("process_memory", c.c_size_t), ("job_memory", c.c_size_t),
                ("peak_process_memory", c.c_size_t), ("peak_job_memory", c.c_size_t)]


def unavailable(message: str) -> InferenceError:
    return InferenceError(ErrorCode.ISOLATION_UNAVAILABLE, message)


@lru_cache(maxsize=1)
def api() -> Any:
    if sys.platform != "win32":
        raise unavailable("The AppContainer prototype requires Windows.")
    from types import SimpleNamespace
    libraries = {key: c.WinDLL(name, use_last_error=True) for key, name in
                 (("kernel", "kernel32"), ("advapi", "advapi32"), ("userenv", "userenv"), ("firewall", "FirewallAPI"))}
    result = SimpleNamespace(**libraries)
    def bind(dll: str, name: str, args: list[Any], restype: Any) -> None:
        function = getattr(libraries[dll], name)
        function.argtypes, function.restype = args, restype
    P, D, H, B, S = c.c_void_p, w.DWORD, w.HANDLE, w.BOOL, c.c_size_t
    definitions = [
        ("kernel", "GetCurrentProcess", [], H), ("kernel", "CloseHandle", [H], B),
        ("kernel", "LocalFree", [P], P), ("kernel", "GetProcessHeap", [], H),
        ("kernel", "HeapFree", [H,D,P], B),
        ("kernel", "CreatePipe", [c.POINTER(H),c.POINTER(H),P,D], B),
        ("kernel", "SetHandleInformation", [H,D,D], B),
        ("kernel", "InitializeProcThreadAttributeList", [P,D,D,c.POINTER(S)], B),
        ("kernel", "UpdateProcThreadAttribute", [P,D,S,P,S,P,P], B),
        ("kernel", "DeleteProcThreadAttributeList", [P], None),
        ("kernel", "CreateProcessW", [w.LPCWSTR,w.LPWSTR,P,P,B,D,P,w.LPCWSTR,P,P], B),
        ("kernel", "CreateJobObjectW", [P,w.LPCWSTR], H),
        ("kernel", "SetInformationJobObject", [H,c.c_int,P,D], B),
        ("kernel", "AssignProcessToJobObject", [H,H], B),
        ("kernel", "IsProcessInJob", [H,H,c.POINTER(B)], B),
        ("kernel", "TerminateJobObject", [H,w.UINT], B),
        ("kernel", "TerminateProcess", [H,w.UINT], B),
        ("kernel", "WaitForSingleObject", [H,D], D),
        ("kernel", "GetExitCodeProcess", [H,c.POINTER(D)], B),
        ("kernel", "ResumeThread", [H], D),
        ("kernel", "QueryFullProcessImageNameW", [H,D,w.LPWSTR,c.POINTER(D)], B),
        ("kernel", "GetProcessMitigationPolicy", [H,c.c_int,P,S], B),
        ("advapi", "OpenProcessToken", [H,D,c.POINTER(H)], B),
        ("advapi", "GetTokenInformation", [H,c.c_int,P,D,c.POINTER(D)], B),
        ("advapi", "ConvertSidToStringSidW", [P,c.POINTER(w.LPWSTR)], B),
        ("advapi", "ConvertStringSidToSidW", [w.LPCWSTR,c.POINTER(P)], B),
        ("advapi", "OpenSCManagerW", [w.LPCWSTR,w.LPCWSTR,D], H),
        ("advapi", "OpenServiceW", [H,w.LPCWSTR,D], H),
        ("advapi", "QueryServiceStatusEx", [H,c.c_int,P,D,c.POINTER(D)], B),
        ("advapi", "CloseServiceHandle", [H], B),
        ("userenv", "CreateAppContainerProfile", [w.LPCWSTR,w.LPCWSTR,w.LPCWSTR,P,D,c.POINTER(P)], c.c_long),
        ("userenv", "DeriveAppContainerSidFromAppContainerName", [w.LPCWSTR,c.POINTER(P)], c.c_long),
        ("advapi", "FreeSid", [P], P),
        ("firewall", "NetworkIsolationGetAppContainerConfig", [c.POINTER(D),c.POINTER(c.POINTER(SidAttributes))], D),
    ]
    for dll, name, args, returns in definitions:
        bind(dll, name, args, returns)
    return result


def checked(value: Any, operation: str) -> Any:
    if not value:
        raise unavailable(f"Windows isolation operation failed: {operation} (error {c.get_last_error()}).")
    return value


def sid_text(pointer: Any) -> str:
    result = w.LPWSTR()
    checked(api().advapi.ConvertSidToStringSidW(pointer, c.byref(result)), "read SID")
    try:
        return result.value or ""
    finally:
        api().kernel.LocalFree(c.cast(result, c.c_void_p))


@dataclass(frozen=True)
class DevelopmentProfile:
    name: str
    sid: str

    def __post_init__(self) -> None:
        if not self.name.startswith(PREFIX) or not re.fullmatch(r"[-_. A-Za-z0-9]{1,64}", self.name):
            raise ValueError("Use a unique Stoneglass development profile name.")
        if not re.fullmatch(r"S-1-15-2-(?:\d+-){6}\d+", self.sid):
            raise ValueError("Use an AppContainer package SID.")


def create_development_profile(name: str) -> DevelopmentProfile:
    # Explicit operation: never invoked by application initialization or tests.
    if not name.startswith(PREFIX) or not re.fullmatch(r"[-_. A-Za-z0-9]{1,64}", name):
        raise ValueError("Invalid development profile name.")
    pointer = c.c_void_p()
    status = api().userenv.CreateAppContainerProfile(name, "Stoneglass offline development prototype",
             "Local model-free isolation compatibility assessment", None, 0, c.byref(pointer))
    if status != 0:
        raise unavailable(f"Unique AppContainer profile creation failed (HRESULT {status & 0xffffffff:08x}); existing profiles were not reused.")
    try:
        return DevelopmentProfile(name, sid_text(pointer))
    finally:
        api().advapi.FreeSid(pointer)


def loopback_exemptions() -> set[str]:
    count, entries = w.DWORD(), c.POINTER(SidAttributes)()
    status = api().firewall.NetworkIsolationGetAppContainerConfig(c.byref(count), c.byref(entries))
    if status:
        raise unavailable(f"Cannot verify AppContainer loopback exemptions (error {status}).")
    try:
        return {sid_text(entries[i].sid) for i in range(count.value)}
    finally:
        heap = api().kernel.GetProcessHeap()
        for i in range(count.value):
            api().kernel.HeapFree(heap, 0, entries[i].sid)
        if entries:
            api().kernel.HeapFree(heap, 0, entries)


def require_filtering_services() -> None:
    manager = checked(api().advapi.OpenSCManagerW(None, None, 1), "inspect service manager")
    try:
        for name in ("BFE", "MpsSvc"):
            service = checked(api().advapi.OpenServiceW(manager, name, 4), "inspect filtering service")
            try:
                status, needed = (w.DWORD * 9)(), w.DWORD()
                checked(api().advapi.QueryServiceStatusEx(service, 0, status, c.sizeof(status), c.byref(needed)), "read filtering service state")
                if status[1] != 4:
                    raise unavailable("Required Windows filtering services are not running; no settings were changed.")
            finally:
                api().advapi.CloseServiceHandle(service)
    finally:
        api().advapi.CloseServiceHandle(manager)


def token_details(process: Any = None) -> dict[str, Any]:
    handle = process if process is not None else api().kernel.GetCurrentProcess()
    token = w.HANDLE()
    checked(api().advapi.OpenProcessToken(handle, 8, c.byref(token)), "inspect process token")
    try:
        def info(kind: int) -> Any:
            needed = w.DWORD()
            api().advapi.GetTokenInformation(token, kind, None, 0, c.byref(needed))
            if not needed.value:
                raise unavailable("Cannot query the worker security token.")
            buffer = c.create_string_buffer(needed.value)
            checked(api().advapi.GetTokenInformation(token, kind, buffer, needed, c.byref(needed)), "query token")
            return buffer
        appcontainer = bool(c.cast(info(29), c.POINTER(w.DWORD))[0])
        capabilities = int(c.cast(info(30), c.POINTER(w.DWORD))[0])
        sid_buffer = info(31)
        sid_pointer = c.cast(sid_buffer, c.POINTER(c.c_void_p))[0]
        package = sid_text(sid_pointer) if sid_pointer else None
        mitigation = w.DWORD()
        checked(api().kernel.GetProcessMitigationPolicy(handle, 13, c.byref(mitigation), c.sizeof(mitigation)), "inspect child policy")
        return {"appcontainer":appcontainer, "capability_count":capabilities,
                "package_sid":package, "no_child_process_creation":bool(mitigation.value & 1)}
    finally:
        api().kernel.CloseHandle(token)


def validate_token(details: dict[str, Any], profile: DevelopmentProfile) -> None:
    if (details.get("appcontainer") is not True or type(details.get("capability_count")) is not int or details.get("capability_count") != 0
            or details.get("package_sid") != profile.sid or details.get("no_child_process_creation") is not True):
        raise unavailable("The worker token, zero-capability or child restriction check failed.")


def validate_staged_paths(root: Path, executable: Path, script: Path) -> tuple[Path, Path, Path]:
    from stoneglass.inference.resources import strict_local
    root = strict_local(root, directory=True)
    if (root.parent.name != "offline-sandbox" or root.parent.parent.name != ".local-data"
            or not re.fullmatch(r"[a-f0-9]{32}", root.name)):
        raise unavailable("Use a uniquely named directory under .local-data/offline-sandbox.")
    executable, script = strict_local(executable), strict_local(script)
    if (executable.parent != root / "runtime" or executable.name not in ("python.exe", "pythonw.exe")
            or not script.is_relative_to(root / "code")):
        raise unavailable("Prototype execution must use only newly staged Python and code.")
    return root, executable, script


def network_denial_checks(results: dict[str, dict[str, Any]], before: dict[str, int],
                          after: dict[str, int]) -> dict[str, bool]:
    """Conservative prototype evidence gate, not production authorization.

    Socket acceptance, quiet responders, timeouts and zero capabilities alone
    never establish explicit OS denial. Unknown/missing diagnostics fail closed.
    WFP drop-event evidence is not available to this prototype's execution token.
    """
    checks = {name: results.get(name, {}).get("ok") is False
              and results[name].get("error") == 10013
              for name in ("ipv4_tcp", "ipv6_tcp", "ipv4_udp", "ipv6_udp", "native_winsock")}
    checks["native_winhttp"] = results.get("native_winhttp", {}).get("ok") is False and results["native_winhttp"].get("error") in (5, 10013)
    checks["native_dns"] = results.get("native_dns", {}).get("status") in (5, 10013)
    checks["zero_controlled_endpoint_arrivals"] = bool(before) and before == after
    return checks


class NativeProcess:
    """Owns precisely one kill-on-close job, process and three parent pipe ends."""
    def __init__(self, process: Any, job: Any, pid: int, stdin: BinaryIO, stdout: BinaryIO, stderr: BinaryIO,
                 evidence: dict[str, Any]) -> None:
        self._process, self._job = process, job
        self.pid, self.stdin, self.stdout, self.stderr = pid, stdin, stdout, stderr
        self.evidence = evidence
        self._closed = False

    def poll(self) -> int | None:
        if self._closed:
            return self.evidence.get("exit_code")
        result = api().kernel.WaitForSingleObject(self._process, 0)
        if result == 258:
            return None
        if result != 0:
            raise unavailable("Cannot inspect owned worker completion.")
        code = w.DWORD()
        checked(api().kernel.GetExitCodeProcess(self._process, c.byref(code)), "read worker exit")
        self.evidence["exit_code"] = code.value
        return code.value

    def kill_tree_and_wait(self, timeout: float) -> None:
        if self._closed:
            return
        if self.poll() is None:
            checked(api().kernel.TerminateJobObject(self._job, 1223), "terminate owned worker job")
        if api().kernel.WaitForSingleObject(self._process, int(timeout * 1000)) != 0:
            raise InferenceError(ErrorCode.CLEANUP_FAILED, "Owned AppContainer job has not terminated; retry cleanup.")
        self.poll()
        api().kernel.CloseHandle(self._process)
        api().kernel.CloseHandle(self._job)
        self._closed = True


def launch_prototype(profile: DevelopmentProfile, root: Path, executable: Path, script: Path,
                     arguments: tuple[str, ...], environment: dict[str, str]) -> NativeProcess:
    """Launch staged code suspended; verify its actual OS properties before resuming.

    Deliberately separate from the production inference launcher registration.
    Native network tests must pass before the caller can run model-free GPU probes.
    """
    root, executable, script = validate_staged_paths(root, executable, script)
    if profile.sid in loopback_exemptions():
        raise unavailable("The development AppContainer has a loopback exemption; refusing execution.")
    require_filtering_services()
    import msvcrt
    import os
    handles: list[Any] = []
    sid = c.c_void_p()
    attributes = None
    initialized = False
    process_info = ProcessInfo()
    job = None
    try:
        checked(api().advapi.ConvertStringSidToSidW(profile.sid, c.byref(sid)), "decode profile SID")
        security = SecurityAttributes(c.sizeof(SecurityAttributes), None, True)
        pipes = []
        for _ in range(3):
            reader, writer = w.HANDLE(), w.HANDLE()
            checked(api().kernel.CreatePipe(c.byref(reader), c.byref(writer), c.byref(security), 0), "create worker pipe")
            handles.extend((reader.value, writer.value)); pipes.append((reader.value, writer.value))
        child_handles = (w.HANDLE * 3)(pipes[0][0], pipes[1][1], pipes[2][1])
        parents = [pipes[0][1], pipes[1][0], pipes[2][0]]
        for handle in parents:
            checked(api().kernel.SetHandleInformation(handle, 1, 0), "restrict parent pipe inheritance")
        needed = c.c_size_t()
        api().kernel.InitializeProcThreadAttributeList(None, 3, 0, c.byref(needed))
        attributes = c.create_string_buffer(needed.value)
        checked(api().kernel.InitializeProcThreadAttributeList(attributes, 3, 0, c.byref(needed)), "initialize process attributes")
        initialized = True
        capabilities, child_policy = SecurityCapabilities(sid, None, 0, 0), w.DWORD(1)
        for key, value in ((0x20009, capabilities), (0x20002, child_handles), (0x2000e, child_policy)):
            checked(api().kernel.UpdateProcThreadAttribute(attributes, 0, key, c.byref(value), c.sizeof(value), None, None), "apply restricted process attributes")
        job = checked(api().kernel.CreateJobObjectW(None, None), "create owned job")
        limits = ExtendedJobLimits()
        limits.basic.flags, limits.basic.active_processes = 0x2000 | 8, 1
        checked(api().kernel.SetInformationJobObject(job, 9, c.byref(limits), c.sizeof(limits)), "restrict owned job")
        startup = StartupInfoEx()
        startup.info.cb, startup.info.flags = c.sizeof(startup), 0x100
        startup.info.stdin, startup.info.stdout, startup.info.stderr = child_handles
        startup.attributes = c.cast(attributes, c.c_void_p)
        command = c.create_unicode_buffer(subprocess.list2cmdline([str(executable), "-I", "-S", "-B", "-X", "utf8", str(script), *arguments]))
        if any("\0" in key or "=" in key or "\0" in value for key,value in environment.items()):
            raise ValueError("Invalid child environment")
        block = c.create_unicode_buffer("\0".join(f"{key}={value}" for key,value in sorted(environment.items())) + "\0\0")
        checked(api().kernel.CreateProcessW(str(executable), command, None, None, True,
                    0x80000 | 0x400 | 0x08000000 | 4, block, str(root), c.byref(startup), c.byref(process_info)), "create suspended AppContainer")
        checked(api().kernel.AssignProcessToJobObject(job, process_info.process), "assign owned job")
        member = w.BOOL()
        checked(api().kernel.IsProcessInJob(process_info.process, job, c.byref(member)), "verify owned job")
        if not member.value:
            raise unavailable("Worker is not in the required owned job.")
        size = w.DWORD(32768); image = c.create_unicode_buffer(size.value)
        checked(api().kernel.QueryFullProcessImageNameW(process_info.process, 0, image, c.byref(size)), "verify process image")
        if Path(image.value) != executable:
            raise unavailable("Actual worker executable differs from the staged interpreter.")
        details = token_details(process_info.process)
        validate_token(details, profile)
        evidence = {"pid":process_info.pid, "actual_image":image.value, "token":details,
                    "verified_before_resume":True, "job_active_process_limit":1, "job_kill_on_close":True,
                    "inherited_ipc_handle_count":3, "loopback_exempt":False}
        if api().kernel.ResumeThread(process_info.thread) == 0xffffffff:
            raise unavailable("Cannot resume the verified AppContainer process.")
        api().kernel.CloseHandle(process_info.thread); process_info.thread = None
        for handle in child_handles:
            api().kernel.CloseHandle(handle); handles.remove(handle)
        streams = []
        for index, handle in enumerate(parents):
            descriptor = msvcrt.open_osfhandle(handle, os.O_BINARY | (os.O_WRONLY if index == 0 else os.O_RDONLY))
            streams.append(os.fdopen(descriptor, "wb" if index == 0 else "rb", buffering=0))
            handles.remove(handle)
        result = NativeProcess(process_info.process, job, process_info.pid, *streams, evidence)
        process_info.process, job = None, None
        return result
    finally:
        if process_info.process:
            api().kernel.TerminateProcess(process_info.process, 1223)
            api().kernel.WaitForSingleObject(process_info.process, 5000)
            api().kernel.CloseHandle(process_info.process)
        if process_info.thread: api().kernel.CloseHandle(process_info.thread)
        if job: api().kernel.CloseHandle(job)
        for handle in handles: api().kernel.CloseHandle(handle)
        if initialized: api().kernel.DeleteProcThreadAttributeList(attributes)
        if sid: api().kernel.LocalFree(sid)
