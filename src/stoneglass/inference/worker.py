# SPDX-License-Identifier: GPL-3.0-or-later
"""Qt-free ordinary-user process client and bounded anonymous-pipe transport."""

import time
from dataclasses import dataclass
from pathlib import Path
from queue import Empty, Full, Queue
from threading import Event, Lock, Thread
from typing import Any, BinaryIO, Protocol

from stoneglass.inference.contracts import InferenceContext, ProgressEvent, ProgressStage, TaskCancelled
from stoneglass.inference.errors import ErrorCode, InferenceError
from stoneglass.inference.offline import offline_environment
from stoneglass.inference.protocol import encode, read_frame
from stoneglass.inference.resources import strict_local


@dataclass(frozen=True)
class WorkerSettings:
    interpreter: Path
    data_directory: Path
    output_directory: Path
    startup_timeout: float = 30
    runtime_timeout: float = 180
    load_timeout: float = 900
    generation_timeout: float = 900
    cancel_grace: float = 3

    def __post_init__(self) -> None:
        for value in (self.startup_timeout, self.runtime_timeout, self.load_timeout, self.generation_timeout, self.cancel_grace):
            if not 0 < value <= 3600:
                raise ValueError("Worker deadlines must be positive and at most one hour.")

    @classmethod
    def for_project(cls, project: Path, data: Path) -> "WorkerSettings":
        return cls(project / ".venv-rocm/Scripts/python.exe", data / "inference-worker", data / "generated")


@dataclass(frozen=True)
class LaunchSpec:
    command: tuple[str, ...]
    environment: dict[str, str]
    output_directory: Path


class WorkerChannel(Protocol):
    def send(self, message: dict[str, Any]) -> None: ...
    def receive(self, timeout: float) -> dict[str, Any] | None: ...
    def close(self) -> None:
        """Boundedly terminate/reap the owned job tree and close all pipe handles, or raise."""
        ...


class WorkerLauncher(Protocol):
    def start(self, spec: LaunchSpec) -> WorkerChannel:
        """Start an owned worker with controlled pipes and process-tree cleanup."""
        ...


class OwnedProcess(Protocol):
    stdin: BinaryIO
    stdout: BinaryIO
    stderr: BinaryIO

    def wait_for_exit(self, timeout: float) -> bool: ...
    def kill_tree_and_wait(self, timeout: float) -> None: ...


class PipeChannel:
    """Transport for an owned process, independent of its launcher.

    Readers/writer keep the service thread cancellable even if pipe I/O stalls.
    stderr is discarded, never logged: framework text can contain private input.
    """

    def __init__(self, process: OwnedProcess) -> None:
        self._process = process
        self._closed = Event()
        self._incoming: Queue[dict[str, Any] | BaseException] = Queue(64)
        self._outgoing: Queue[bytes | None] = Queue(4)
        self._threads = [Thread(target=target, daemon=True) for target in (self._read, self._write, self._discard)]
        for thread in self._threads:
            thread.start()

    def _put(self, value: dict[str, Any] | BaseException) -> None:
        while not self._closed.is_set():
            try:
                self._incoming.put(value, timeout=0.1)
                return
            except Full:
                pass

    def _read(self) -> None:
        try:
            while not self._closed.is_set():
                message = read_frame(self._process.stdout)
                if message is None:
                    raise EOFError()
                self._put(message)
        except BaseException:
            self._put(InferenceError(ErrorCode.WORKER_FAILED, "The inference worker stopped or sent an invalid message."))

    def _write(self) -> None:
        try:
            while not self._closed.is_set():
                try:
                    data = self._outgoing.get(timeout=0.1)
                except Empty:
                    continue
                if data is None:
                    return
                remaining = memoryview(data)
                while remaining:
                    written = self._process.stdin.write(remaining)
                    if not written:
                        raise OSError("Worker pipe write stopped.")
                    remaining = remaining[written:]
                self._process.stdin.flush()
        except BaseException:
            self._put(InferenceError(ErrorCode.WORKER_FAILED, "The inference-worker pipe could not be written."))

    def _discard(self) -> None:
        try:
            while self._process.stderr.read(65536):
                if self._closed.is_set():
                    break
        except (OSError, ValueError):
            pass

    def send(self, message: dict[str, Any]) -> None:
        if self._closed.is_set():
            raise InferenceError(ErrorCode.WORKER_FAILED, "The inference-worker channel is closed.")
        try:
            self._outgoing.put_nowait(encode(message))
        except Full:
            raise InferenceError(ErrorCode.WORKER_FAILED, "The inference-worker command queue is full.") from None

    def receive(self, timeout: float) -> dict[str, Any] | None:
        try:
            item = self._incoming.get(timeout=timeout)
        except Empty:
            return None
        if isinstance(item, BaseException):
            raise item
        return item

    def finish_input(self) -> None:
        """After a close reply, allow bounded normal native-runtime shutdown."""
        self._process.stdin.close()
        self._process.wait_for_exit(5)

    def close(self) -> None:
        # Retain process ownership if termination fails, so unload can retry.
        self._process.kill_tree_and_wait(5)
        self._closed.set()
        for stream in (self._process.stdin, self._process.stdout, self._process.stderr):
            stream.close()
        for thread in self._threads:
            thread.join(1)
        if any(t.is_alive() for t in self._threads):
            raise InferenceError(ErrorCode.CLEANUP_FAILED, "Worker pipe cleanup has not finished; retry unloading.")


class WorkerClient:
    def __init__(self, settings: WorkerSettings, launcher: WorkerLauncher | None = None) -> None:
        self.settings = settings
        if launcher is None:
            from stoneglass.inference.local_process import LocalWorkerLauncher
            launcher = LocalWorkerLauncher()
        self._launcher = launcher
        self._channel: WorkerChannel | None = None
        self._lock = Lock()
        self._number = 0

    def _start(self, context: InferenceContext) -> None:
        if self._channel is not None:
            return
        context.check_cancelled()
        interpreter = strict_local(self.settings.interpreter)
        entry = strict_local(Path(__file__).with_name("_offline_worker.py"))
        from stoneglass.inference.local_process import prepare_directory
        environment = offline_environment(self.settings.data_directory)
        for directory in (self.settings.data_directory, self.settings.output_directory,
                          *(Path(environment[key]) for key in ("HF_HOME", "HF_HUB_CACHE", "XDG_CACHE_HOME", "TEMP"))):
            prepare_directory(directory)
        spec = LaunchSpec((str(interpreter), "-I", "-S", "-B", "-X", "utf8", str(entry)),
                          environment, self.settings.output_directory)
        self._channel = self._launcher.start(spec)
        deadline = time.monotonic() + self.settings.startup_timeout
        while time.monotonic() < deadline:
            context.check_cancelled()
            message = self._channel.receive(0.1)
            if message is None:
                continue
            if message == {"schema": 1, "kind": "ready", "id": 0}:
                return
            if message.get("schema") != 1 or message.get("id") != 0:
                raise InferenceError(ErrorCode.WORKER_FAILED, "Invalid worker startup response.")
            self._raise_remote(message)
        raise InferenceError(ErrorCode.OPERATION_TIMEOUT, "The local worker did not start within its deadline.")

    @staticmethod
    def _raise_remote(message: dict[str, Any]) -> None:
        if message.get("kind") == "error":
            try:
                code = ErrorCode(message["code"])
                text = message["message"]
                if not isinstance(text, str) or len(text) > 512 or "\n" in text:
                    raise ValueError()
                raise InferenceError(code, text)
            except (KeyError, TypeError, ValueError):
                pass
        raise InferenceError(ErrorCode.WORKER_FAILED, "The local worker sent an invalid response.")

    def call(self, operation: str, payload: dict[str, Any], context: InferenceContext,
             *, timeout: float, stage: ProgressStage) -> dict[str, Any]:
        if operation not in {"load", "detect", "validate_runtime", "validate_components", "diagnostics", "generate", "unload", "close"}:
            raise InferenceError(ErrorCode.INVALID_REQUEST, "Unsupported inference-worker operation.")
        if not self._lock.acquire(blocking=False):
            raise InferenceError(ErrorCode.BUSY, "An inference-worker operation is already running.")
        try:
            self._start(context)
            assert self._channel is not None
            self._number += 1
            number = self._number
            self._channel.send({"schema": 1, "id": number, "operation": operation, "payload": payload})
            deadline = time.monotonic() + timeout
            cancel_deadline: float | None = None
            heartbeat = time.monotonic() + 10
            last_percent = 0
            while time.monotonic() < deadline:
                try:
                    context.check_cancelled()
                except TaskCancelled:
                    if cancel_deadline is None:
                        self._channel.send({"schema": 1, "id": number, "operation": "cancel", "payload": {}})
                        cancel_deadline = time.monotonic() + self.settings.cancel_grace
                if cancel_deadline is not None and time.monotonic() >= cancel_deadline:
                    raise TaskCancelled()
                message = self._channel.receive(0.1)
                if message is None:
                    if cancel_deadline is None and time.monotonic() >= heartbeat:
                        context.report_event(ProgressEvent(stage, last_percent, "Waiting for local runtime work; native initialization may be slow"))
                        heartbeat = time.monotonic() + 10
                    continue
                if message.get("schema") != 1 or message.get("id") != number:
                    raise InferenceError(ErrorCode.WORKER_FAILED, "The worker response does not match the current operation.")
                if cancel_deadline is not None:
                    if message.get("kind") in ("result", "error", "cancelled"):
                        raise TaskCancelled()
                    continue
                if message.get("kind") == "progress":
                    try:
                        event = ProgressEvent(ProgressStage(message["stage"]), message["percent"], message["message"])
                        if not isinstance(event.message, str) or len(event.message) > 256:
                            raise ValueError()
                        context.report_event(event)
                        last_percent = event.percent
                    except (KeyError, ValueError, TypeError):
                        raise InferenceError(ErrorCode.WORKER_FAILED, "The worker sent invalid progress.") from None
                elif message.get("kind") == "result" and isinstance(message.get("payload"), dict):
                    context.check_cancelled()
                    return message["payload"]
                elif message.get("kind") == "cancelled":
                    raise TaskCancelled()
                else:
                    self._raise_remote(message)
            if cancel_deadline is not None:
                raise TaskCancelled()
            raise InferenceError(ErrorCode.OPERATION_TIMEOUT, "Local inference exceeded its deadline. The owned worker will be stopped.")
        except BaseException:
            self.close()
            raise
        finally:
            self._lock.release()

    def close(self) -> None:
        if self._channel is not None:
            # Cooperate only when no call is outstanding. Errors/cancellation
            # retain the fast owned-job termination path and never recurse.
            if not self._lock.locked():
                try:
                    self._number += 1
                    self._channel.send({"schema": 1, "id": self._number, "operation": "close", "payload": {}})
                    deadline = time.monotonic() + 2
                    while time.monotonic() < deadline:
                        message = self._channel.receive(0.1)
                        if message and message.get("id") == self._number and message.get("kind") in ("result", "error"):
                            if isinstance(self._channel, PipeChannel):
                                self._channel.finish_input()
                            break
                except Exception:
                    pass
            self._channel.close()
            self._channel = None
