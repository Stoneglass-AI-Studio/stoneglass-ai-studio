# SPDX-License-Identifier: GPL-3.0-or-later
"""Worker-side protocol dispatcher; entrypoint establishes library policy first."""

import contextlib
from dataclasses import asdict
from pathlib import Path
from queue import Queue
from threading import Event, Lock, Thread
from typing import Any, BinaryIO

from stoneglass.domain.settings import GenerationSettings
from stoneglass.inference.contracts import (
    GenerationRequest, ModelSpec, ModelVariant, ProgressEvent, ProgressStage, RuntimeDevice, RuntimeKind, TaskCancelled,
)
from stoneglass.inference.errors import ErrorCode, InferenceError
from stoneglass.inference.protocol import encode, read_frame
from stoneglass.inference.resources import strict_local


def model_payload(model: ModelSpec) -> dict[str, Any]:
    return {"model_id": model.model_id, "path": str(model.path), "architecture": model.architecture,
            "variant": model.variant.value, "adapters": [str(p) for p in model.adapters],
            "resource_manifest": str(model.resource_manifest) if model.resource_manifest else None}


def decode_model(data: dict[str, Any]) -> ModelSpec:
    if set(data) != {"model_id", "path", "architecture", "variant", "adapters", "resource_manifest"}:
        raise ValueError()
    if not all(isinstance(data[k], str) for k in ("model_id", "path", "architecture", "variant")) or data["adapters"] != []:
        raise ValueError()
    if not isinstance(data["resource_manifest"], str):
        raise ValueError()
    return ModelSpec(data["model_id"], Path(data["path"]), data["architecture"], ModelVariant(data["variant"]),
                     (), Path(data["resource_manifest"]))


class WorkerEngine:
    def __init__(self) -> None:
        self._adapter: Any = None

    def dispatch(self, operation: str, payload: dict[str, Any], context: Any) -> dict[str, Any]:
        from stoneglass.inference.offline import assert_offline_policy
        assert_offline_policy()
        if operation == "validate_components":
            if self._adapter is not None or set(payload) != {"model"}:
                raise ValueError()
            model = decode_model(payload["model"])
            from stoneglass.inference.process_backend import preflight
            from stoneglass.inference.resources import read_manifest, validate_sdxl
            from stoneglass.inference.resource_lease import ResourceLease
            from stoneglass.inference.sdxl import _dependencies, validate_component_shapes, ComponentValidationError
            preflight(model, context)
            manifest = read_manifest(model.resource_manifest)
            with ResourceLease(manifest):
                bundle = validate_sdxl(manifest, context)
                context.check_cancelled()
                context.report_event(ProgressEvent(ProgressStage.VALIDATING, 0, "Converting all SDXL component metadata on the meta device"))
                try:
                    result = validate_component_shapes(bundle, _dependencies())
                except ComponentValidationError as exc:
                    return {"passed": False, "components": exc.report, "model_weights_loaded": False}
                context.check_cancelled()
                return {"passed": True, "components": result, "model_weights_loaded": False}
        if operation == "diagnostics":
            if payload or self._adapter is None:
                raise ValueError()
            return self._adapter.diagnostics()
        if operation == "validate_runtime":
            if payload or self._adapter is not None:
                raise ValueError()
            from stoneglass.inference.runtime_validation import validate_runtime
            return validate_runtime(context)
        if operation == "detect":
            if payload:
                raise ValueError()
            from stoneglass.inference._torch_probe import probe
            return probe()
        if operation == "load":
            if self._adapter is not None or set(payload) != {"model", "runtime", "output_directory"}:
                raise ValueError()
            model = decode_model(payload["model"])
            device = payload["runtime"]
            if set(device) != {"kind", "index", "name"} or not isinstance(device["name"], str):
                raise ValueError()
            runtime = RuntimeDevice(RuntimeKind(device["kind"]), device["index"], device["name"])
            from stoneglass.inference.sdxl import SDXLAdapter
            self._adapter = SDXLAdapter(strict_local(Path(payload["output_directory"]), directory=True))
            self._adapter.load_model(model, runtime, context)
            return {}
        if operation == "generate":
            if self._adapter is None:
                raise InferenceError(ErrorCode.NOT_READY, "No local model is loaded in the worker.")
            if set(payload) != {"positive_prompt", "negative_prompt", "settings", "model_id"}:
                raise ValueError()
            request = GenerationRequest(payload["positive_prompt"], payload["negative_prompt"],
                                        GenerationSettings(**payload["settings"]), payload["model_id"])
            result = self._adapter.generate(request, context)
            return {**asdict(result), "image_path": result.image_path.name}
        if operation in ("unload", "close") and not payload:
            if self._adapter is not None and operation == "unload":
                self._adapter.unload()
                report = self._adapter.diagnostics()
                self._adapter = None
                return report
            self.close()
            return {}
        raise ValueError()

    def close(self) -> None:
        if self._adapter is not None:
            self._adapter.unload()
            self._adapter = None


def run_protocol(source: BinaryIO, target: BinaryIO, engine: Any, *, redirect: Any) -> None:
    """Pure protocol loop, injectable for unit tests; never establishes isolation."""
    messages: Queue[dict[str, Any] | None] = Queue(4)
    cancellation = Event()
    state_lock, write_lock = Lock(), Lock()
    current_id = [0]

    def send(message: dict[str, Any]) -> None:
        with write_lock:
            target.write(encode(message))
            target.flush()

    def reader() -> None:
        try:
            while message := read_frame(source):
                if message.get("operation") == "cancel":
                    with state_lock:
                        if message.get("schema") == 1 and message.get("id") == current_id[0]:
                            cancellation.set()
                    continue
                # Only one outstanding request is allowed; set its identity before
                # queueing so cancellation during queued startup isn't lost.
                with state_lock:
                    if current_id[0] != 0:
                        raise ValueError()
                    current_id[0] = message.get("id")
                    cancellation.clear()
                messages.put(message)
        except Exception:
            pass
        finally:
            cancellation.set()
            messages.put(None)

    class Context:
        def check_cancelled(self) -> None:
            if cancellation.is_set():
                raise TaskCancelled()

        def report_progress(self, percent: int, message: str) -> None:
            self.check_cancelled()

        def report_event(self, event: ProgressEvent) -> None:
            self.check_cancelled()
            send({"schema": 1, "id": current_id[0], "kind": "progress",
                  "stage": event.stage.value, "percent": event.percent, "message": event.message})

    context = Context()
    send({"schema": 1, "kind": "ready", "id": 0})
    thread = Thread(target=reader, daemon=True)
    thread.start()
    try:
        last_id = 0
        while (message := messages.get()) is not None:
            number = message.get("id")
            operation = message.get("operation")
            if (set(message) != {"schema", "id", "operation", "payload"} or message.get("schema") != 1
                    or type(number) is not int or number <= last_id or not isinstance(operation, str)
                    or not isinstance(message.get("payload"), dict)):
                raise ValueError()
            last_id = number
            try:
                if operation not in ("unload", "close"):
                    context.check_cancelled()
                with contextlib.redirect_stdout(redirect), contextlib.redirect_stderr(redirect):
                    result = engine.dispatch(operation, message["payload"], context)
                if operation not in ("unload", "close"):
                    context.check_cancelled()
                response = {"schema": 1, "id": number, "kind": "result", "payload": result}
            except TaskCancelled:
                engine.close()
                response = {"schema": 1, "id": number, "kind": "cancelled"}
            except Exception as exc:
                engine.close()
                # Only project boundary errors are display-safe. Never serialize
                # a dependency exception, traceback, model object or prompt.
                info = exc.info if isinstance(exc, InferenceError) else None
                response = {"schema": 1, "id": number, "kind": "error",
                            "code": info.code.value if info else ErrorCode.WORKER_FAILED.value,
                            "message": info.message if info else "The local inference operation failed. Check local resources and runtime compatibility."}
            with state_lock:
                current_id[0] = 0
                cancellation.clear()
            send(response)
            if operation == "close" or response["kind"] in ("error", "cancelled"):
                break
    finally:
        engine.close()
        from stoneglass.inference.pipe_input import WorkerPipeInput
        if isinstance(source, WorkerPipeInput):
            source.close()
        # The parent closes input after the close reply. EOF releases the reader
        # before normal interpreter exit; crash/cancel still has owned-job cleanup.
        thread.join(0.5)
        # The process exits immediately after this loop. Native launcher owns
        # final pipe/thread/job cleanup if the input reader is still blocked.
