# SPDX-License-Identifier: GPL-3.0-or-later
"""Ordinary Windows process ownership. No sandbox, security-policy or ACL changes."""

import ctypes as c
import os
import subprocess
import sys
import time
from ctypes import wintypes as w
from functools import lru_cache
from pathlib import Path
from typing import Any, BinaryIO, TYPE_CHECKING

from stoneglass.inference.errors import ErrorCode, InferenceError
from stoneglass.inference.resources import strict_local

if TYPE_CHECKING:
    from stoneglass.inference.worker import LaunchSpec, WorkerChannel


def prepare_directory(path: Path) -> None:
    """Create only missing local directories, rejecting redirects at each level."""
    missing = []
    ancestor = path
    while not ancestor.exists():
        missing.append(ancestor)
        if ancestor == ancestor.parent:
            break
        ancestor = ancestor.parent
    strict_local(ancestor, directory=True)
    for item in reversed(missing):
        try:
            item.mkdir(exist_ok=True)
        except OSError:
            raise InferenceError(ErrorCode.WORKER_FAILED, "Cannot create the local worker data directory.") from None
        strict_local(item, directory=True)
    strict_local(path, directory=True)


class SecurityAttributes(c.Structure):
    _fields_ = [("size", w.DWORD), ("descriptor", c.c_void_p), ("inherit", w.BOOL)]


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
                ("minimum", c.c_size_t), ("maximum", c.c_size_t), ("active", w.DWORD),
                ("affinity", c.c_size_t), ("priority", w.DWORD), ("scheduling", w.DWORD)]


class ExtendedJobLimits(c.Structure):
    _fields_ = [("basic", BasicJobLimits), ("io", c.c_uint64 * 6),
                ("process_memory", c.c_size_t), ("job_memory", c.c_size_t),
                ("peak_process", c.c_size_t), ("peak_job", c.c_size_t)]


class JobAccounting(c.Structure):
    _fields_ = [("user", c.c_int64), ("kernel", c.c_int64), ("period_user", c.c_int64),
                ("period_kernel", c.c_int64), ("faults", w.DWORD), ("total", w.DWORD),
                ("active", w.DWORD), ("terminated", w.DWORD)]


@lru_cache(maxsize=1)
def _api() -> Any:
    if sys.platform != "win32":
        raise InferenceError(ErrorCode.RUNTIME_UNAVAILABLE, "The local ROCm launcher requires Windows.")
    kernel = c.WinDLL("kernel32", use_last_error=True)
    P, H, D, S, B = c.c_void_p, w.HANDLE, w.DWORD, c.c_size_t, w.BOOL
    for name, args, result in (
        ("CloseHandle", [H], B), ("CreatePipe", [c.POINTER(H), c.POINTER(H), P, D], B),
        ("SetHandleInformation", [H, D, D], B),
        ("InitializeProcThreadAttributeList", [P, D, D, c.POINTER(S)], B),
        ("UpdateProcThreadAttribute", [P, D, S, P, S, P, P], B),
        ("DeleteProcThreadAttributeList", [P], None),
        ("CreateProcessW", [w.LPCWSTR, w.LPWSTR, P, P, B, D, P, w.LPCWSTR, P, P], B),
        ("CreateJobObjectW", [P, w.LPCWSTR], H),
        ("SetInformationJobObject", [H, c.c_int, P, D], B),
        ("QueryInformationJobObject", [H, c.c_int, P, D, P], B),
        ("AssignProcessToJobObject", [H, H], B), ("TerminateJobObject", [H, w.UINT], B),
        ("TerminateProcess", [H, w.UINT], B), ("WaitForSingleObject", [H, D], D),
        ("GetExitCodeProcess", [H, c.POINTER(D)], B), ("ResumeThread", [H], D),
    ):
        function = getattr(kernel, name)
        function.argtypes, function.restype = args, result
    return kernel


def _check(value: Any, operation: str, code: ErrorCode = ErrorCode.WORKER_FAILED) -> Any:
    if not value:
        raise InferenceError(code, f"Local worker {operation} failed (Windows error {c.get_last_error()}).")
    return value


class LocalProcess:
    """Handles, not PIDs, determine ownership. Cleanup is bounded and retryable."""
    def __init__(self, process: Any, job: Any, pid: int, streams: list[BinaryIO]) -> None:
        self._process, self._job = process, job
        self.pid = pid
        self.stdin, self.stdout, self.stderr = streams
        self.exit_code: int | None = None

    def poll(self) -> int | None:
        if self._process is None:
            return self.exit_code
        state = _api().WaitForSingleObject(self._process, 0)
        if state == 258:
            return None
        if state != 0:
            raise InferenceError(ErrorCode.CLEANUP_FAILED, "Cannot inspect owned worker completion.")
        code = w.DWORD()
        _check(_api().GetExitCodeProcess(self._process, c.byref(code)), "exit-code read", ErrorCode.CLEANUP_FAILED)
        self.exit_code = code.value
        return code.value

    def wait_for_exit(self, timeout: float) -> bool:
        if self._process is None:
            return True
        state = _api().WaitForSingleObject(self._process, int(timeout * 1000))
        if state == 258:
            return False
        if state != 0:
            raise InferenceError(ErrorCode.CLEANUP_FAILED, "Cannot wait for owned worker completion.")
        return self.poll() is not None

    def kill_tree_and_wait(self, timeout: float) -> None:
        if self._process is None:
            return
        # A close reply can precede normal interpreter exit by a few milliseconds.
        _api().WaitForSingleObject(self._process, min(1000, int(timeout * 1000)))
        # Terminate the job even if the root already exited: descendants may remain.
        _check(_api().TerminateJobObject(self._job, 1223), "owned job termination", ErrorCode.CLEANUP_FAILED)
        deadline = time.monotonic() + timeout
        accounting = JobAccounting()
        while True:
            _check(_api().QueryInformationJobObject(self._job, 1, c.byref(accounting), c.sizeof(accounting), None),
                   "owned job accounting", ErrorCode.CLEANUP_FAILED)
            if self.poll() is not None and accounting.active == 0:
                break
            if time.monotonic() >= deadline:
                raise InferenceError(ErrorCode.CLEANUP_FAILED, "Owned worker processes have not stopped; retry unloading.")
            time.sleep(0.01)
        _api().CloseHandle(self._process)
        _api().CloseHandle(self._job)
        self._process, self._job = None, None


def _spawn_owned(spec: "LaunchSpec") -> LocalProcess:
    """Start suspended, assign lifetime job, then resume. No token attributes."""
    import msvcrt
    kernel = _api()
    handles: list[int] = []
    streams: list[BinaryIO] = []
    info, job, initialized = ProcessInfo(), None, False
    attributes = None
    try:
        security = SecurityAttributes(c.sizeof(SecurityAttributes), None, True)
        pipes = []
        for _ in range(3):
            reader, writer = w.HANDLE(), w.HANDLE()
            _check(kernel.CreatePipe(c.byref(reader), c.byref(writer), c.byref(security), 0), "pipe creation")
            handles.extend((reader.value, writer.value))
            pipes.append((reader.value, writer.value))
        children = (w.HANDLE * 3)(pipes[0][0], pipes[1][1], pipes[2][1])
        parents = [pipes[0][1], pipes[1][0], pipes[2][0]]
        for handle in parents:
            _check(kernel.SetHandleInformation(handle, 1, 0), "pipe inheritance setup")
        size = c.c_size_t()
        kernel.InitializeProcThreadAttributeList(None, 1, 0, c.byref(size))
        attributes = c.create_string_buffer(size.value)
        _check(kernel.InitializeProcThreadAttributeList(attributes, 1, 0, c.byref(size)), "handle-list setup")
        initialized = True
        _check(kernel.UpdateProcThreadAttribute(attributes, 0, 0x20002, c.byref(children), c.sizeof(children), None, None),
               "pipe handle-list setup")
        job = _check(kernel.CreateJobObjectW(None, None), "job creation")
        limits = ExtendedJobLimits()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE; lifetime only.
        _check(kernel.SetInformationJobObject(job, 9, c.byref(limits), c.sizeof(limits)), "job lifetime setup")
        startup = StartupInfoEx()
        startup.info.cb, startup.info.flags = c.sizeof(startup), 0x100
        startup.info.stdin, startup.info.stdout, startup.info.stderr = children
        startup.attributes = c.cast(attributes, c.c_void_p)
        command = c.create_unicode_buffer(subprocess.list2cmdline(spec.command))
        if any(not key or "=" in key or "\0" in key or "\0" in value for key, value in spec.environment.items()):
            raise InferenceError(ErrorCode.INVALID_REQUEST, "Invalid local worker environment.")
        environment = c.create_unicode_buffer("\0".join(f"{key}={value}" for key, value in
                                                       sorted(spec.environment.items(), key=lambda item: item[0].upper())) + "\0\0")
        _check(kernel.CreateProcessW(spec.command[0], command, None, None, True,
                    0x80000 | 0x400 | 0x08000000 | 4, environment, str(spec.output_directory),
                    c.byref(startup), c.byref(info)), "suspended process creation")
        _check(kernel.AssignProcessToJobObject(job, info.process), "job assignment")
        for index, handle in enumerate(parents):
            descriptor = msvcrt.open_osfhandle(handle, os.O_BINARY | (os.O_WRONLY if index == 0 else os.O_RDONLY))
            handles.remove(handle)  # Descriptor now owns the handle, including fdopen failure.
            try:
                stream = os.fdopen(descriptor, "wb" if index == 0 else "rb", buffering=0)
            except BaseException:
                os.close(descriptor)
                raise
            streams.append(stream)
        if kernel.ResumeThread(info.thread) == 0xffffffff:
            raise InferenceError(ErrorCode.WORKER_FAILED, "Cannot resume the owned local worker.")
        result = LocalProcess(info.process, job, info.pid, streams)
        info.process, job, streams = None, None, []
        return result
    finally:
        if info.process:
            if job:
                kernel.TerminateJobObject(job, 1223)
            kernel.TerminateProcess(info.process, 1223)
            kernel.WaitForSingleObject(info.process, 5000)
            kernel.CloseHandle(info.process)
        if info.thread:
            kernel.CloseHandle(info.thread)
        if job:
            kernel.CloseHandle(job)
        for stream in streams:
            stream.close()
        for handle in handles:
            kernel.CloseHandle(handle)
        if initialized:
            kernel.DeleteProcThreadAttributeList(attributes)


class LocalWorkerLauncher:
    def start(self, spec: "LaunchSpec") -> "WorkerChannel":
        from stoneglass.inference.worker import PipeChannel
        _api()  # Platform check before any process creation.
        if (len(spec.command) != 7 or spec.command[1:6] != ("-I", "-S", "-B", "-X", "utf8")
                or strict_local(Path(spec.command[-1])) != Path(__file__).with_name("_offline_worker.py")):
            raise InferenceError(ErrorCode.INVALID_REQUEST, "Use the reviewed local inference-worker entrypoint.")
        strict_local(Path(spec.command[0]))
        strict_local(spec.output_directory, directory=True)
        process = _spawn_owned(spec)
        try:
            return PipeChannel(process)
        except BaseException:
            process.kill_tree_and_wait(5)
            for stream in (process.stdin, process.stdout, process.stderr):
                stream.close()
            raise
