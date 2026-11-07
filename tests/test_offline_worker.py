# SPDX-License-Identifier: GPL-3.0-or-later

import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from collections import deque
from dataclasses import replace
from pathlib import Path
from threading import Event
from unittest.mock import Mock, patch

from inference_support import Context, make_rig
from stoneglass.inference.contracts import GenerationRequest, GenerationResult, ProgressStage, RuntimeRequest, TaskCancelled
from stoneglass.inference.errors import ErrorCode, InferenceError
from stoneglass.inference.offline import OFFLINE_FLAGS, assert_library_policy, assert_offline_policy, offline_environment
from stoneglass.inference.process_backend import SDXLProcessBackend, SDXLProcessProvider, create_sdxl_service
from stoneglass.inference.protocol import MAX_FRAME, encode, read_frame
from stoneglass.inference.worker import WorkerLauncher, PipeChannel, WorkerClient, WorkerSettings


class Channel:
    """Protocol fixture only; no model, GPU, image or subprocess implementation."""
    def __init__(self, responses=()):
        self.responses = deque([{"schema": 1, "kind": "ready", "id": 0}, *responses])
        self.sent = []
        self.closed = 0
        self.on_send = lambda message: None

    def send(self, message):
        self.sent.append(message)
        self.on_send(message)

    def receive(self, timeout):
        if self.responses: return self.responses.popleft()
        time.sleep(min(timeout, 0.002))
        return None

    def close(self): self.closed += 1


class OfflineWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.settings = WorkerSettings(Path(sys.executable), self.root / "data", self.root / "output",
                                       startup_timeout=0.1, runtime_timeout=0.1, load_timeout=0.1,
                                       generation_timeout=0.1, cancel_grace=0.02)
        self.context = Context()

    def tearDown(self): self.temp.cleanup()

    def client(self, channel):
        launcher = Mock(spec=WorkerLauncher)
        launcher.start.return_value = channel
        return WorkerClient(self.settings, launcher), launcher

    def call(self, client):
        return client.call("load", {}, self.context, timeout=0.1, stage=ProgressStage.LOADING)

    def test_environment_drops_credentials_proxies_and_experimental_flags(self):
        with patch.dict(os.environ, {"HF_TOKEN": "PRIVATE", "HTTPS_PROXY": "PRIVATE", "PYTHONPATH": "PRIVATE",
                                     "TORCH_ROCM_AOTRITON_ENABLE_EXPERIMENTAL": "1"}):
            env = offline_environment(self.root)
        for key in ("HF_TOKEN", "HTTPS_PROXY", "PYTHONPATH", "TORCH_ROCM_AOTRITON_ENABLE_EXPERIMENTAL"):
            self.assertNotIn(key, env)
        self.assertTrue(all(env[k] == v for k, v in OFFLINE_FLAGS.items()))
        self.assertIn(str(self.root), env["HF_HOME"])

    def test_library_policy_requires_flags_before_imports(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(InferenceError): assert_library_policy()
        with patch.dict(os.environ, OFFLINE_FLAGS), patch.dict(sys.modules, {"torch": Mock()}):
            with self.assertRaises(InferenceError): assert_library_policy()

    def test_missing_interpreter_fails_without_spawning_or_creating_directories(self):
        with patch("subprocess.Popen") as spawn:
            settings = replace(self.settings, interpreter=self.root / "missing-python.exe")
            with self.assertRaises(InferenceError) as caught: self.call(WorkerClient(settings))
        self.assertEqual(caught.exception.info.code, ErrorCode.INVALID_RESOURCES)
        spawn.assert_not_called()
        self.assertFalse(self.settings.data_directory.exists())

    def test_actual_rocm_interpreter_entry_ready_and_close_without_models(self):
        project = Path(__file__).resolve().parents[1]
        candidate = project / ".venv-rocm/Scripts/python.exe"
        interpreter = candidate if candidate.exists() else Path(sys.executable)
        entry = project / "src/stoneglass/inference/_offline_worker.py"
        result = subprocess.run([str(interpreter), "-I", "-S", "-B", "-X", "utf8", str(entry)],
                                input=encode({"schema": 1, "id": 1, "operation": "close", "payload": {}}),
                                env=offline_environment(self.root), capture_output=True, timeout=15, check=False)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
        frames = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual([f["kind"] for f in frames], ["ready", "result"])

    def test_policy_can_be_rechecked_after_library_imports(self):
        with patch.dict(os.environ, OFFLINE_FLAGS), patch.dict(sys.modules, {"torch": Mock()}):
            assert_offline_policy()
            with self.assertRaises(InferenceError): assert_library_policy()

    def test_bounded_protocol_rejects_bad_frames_duplicate_keys_and_nan(self):
        for data in (b"{}", b'{"x":1,"x":2}\n', b'[]\n', b'x' * (MAX_FRAME + 1)):
            with self.subTest(prefix=data[:30]), self.assertRaises(InferenceError):
                read_frame(io.BytesIO(data))
        with self.assertRaises(ValueError): encode({"x": float("nan")})

    def test_typed_progress_result_and_launch_arguments_exclude_prompts(self):
        channel = Channel([{"schema": 1, "id": 1, "kind": "progress", "stage": "loading", "percent": 15, "message": "Local load"},
                           {"schema": 1, "id": 1, "kind": "result", "payload": {"ok": True}}])
        client, launcher = self.client(channel)
        self.assertEqual(self.call(client), {"ok": True})
        self.assertEqual(self.context.events[0].percent, 15)
        spec = launcher.start.call_args.args[0]
        self.assertIn("-S", spec.command)
        self.assertIn("-I", spec.command)
        self.assertEqual(Path(spec.command[0]), Path(sys.executable))
        self.assertNotIn("prompt", " ".join(spec.command))
        client.close(); client.close()
        self.assertEqual(channel.closed, 1)

    def test_remote_error_is_actionable_and_process_is_reaped(self):
        channel = Channel([{"schema": 1, "id": 1, "kind": "error", "code": "invalid_resources",
                            "message": "Missing local SDXL resource: tokenizer_2/merges.txt."}])
        client, _ = self.client(channel)
        with self.assertRaisesRegex(InferenceError, "tokenizer_2/merges.txt"): self.call(client)
        self.assertEqual(channel.closed, 1)

    def test_invalid_response_identity_and_progress_close_worker(self):
        for frame in ({"schema": 1, "id": 2, "kind": "result", "payload": {}},
                      {"schema": 1, "id": 1, "kind": "progress", "stage": "loading", "percent": 999, "message": "bad"}):
            channel = Channel([frame]); client, _ = self.client(channel)
            with self.assertRaises(InferenceError): self.call(client)
            self.assertEqual(channel.closed, 1)

    def test_cancellation_sends_control_then_stops_unresponsive_owned_worker(self):
        channel = Channel(); client, _ = self.client(channel)
        channel.on_send = lambda message: self.context.cancel.set() if message["operation"] == "load" else None
        start = time.monotonic()
        with self.assertRaises(TaskCancelled): self.call(client)
        self.assertLess(time.monotonic() - start, 1)
        self.assertEqual([m["operation"] for m in channel.sent], ["load", "cancel"])
        self.assertEqual(channel.closed, 1)

    def test_timeout_reaps_worker_and_startup_cancellation_does_not_launch(self):
        channel = Channel(); client, launcher = self.client(channel)
        with self.assertRaises(InferenceError) as caught: self.call(client)
        self.assertEqual(caught.exception.info.code, ErrorCode.OPERATION_TIMEOUT)
        self.assertEqual(channel.closed, 1)
        self.context.cancel.set()
        fresh, launcher = self.client(Channel())
        with self.assertRaises(TaskCancelled): self.call(fresh)
        launcher.start.assert_not_called()

    def test_cleanup_failure_retains_ownership_for_retry(self):
        channel = Channel(); client, _ = self.client(channel)
        client._channel = channel
        close = Mock(side_effect=[InferenceError(ErrorCode.CLEANUP_FAILED, "Retry cleanup."), None])
        channel.close = close
        with self.assertRaises(InferenceError): client.close()
        self.assertIs(client._channel, channel)
        client.close()
        self.assertIsNone(client._channel)

    def test_no_download_protocol_and_no_automatic_ui_provider(self):
        client, launcher = self.client(Channel())
        with self.assertRaises(InferenceError):
            client.call("download", {}, self.context, timeout=1, stage=ProgressStage.LOADING)
        launcher.start.assert_not_called()
        provider = SDXLProcessProvider(self.settings)
        self.assertFalse(provider.capabilities.generation_available)
        service = create_sdxl_service(Path(__file__).resolve().parents[1], self.root)
        self.assertFalse(service.status.can_generate)
        self.assertFalse(service._providers[0].capabilities.generation_available)

    def test_parent_output_commit_and_cancelled_output_cleanup_are_owned(self):
        backend = SDXLProcessBackend(self.settings)
        backend._run.mkdir(parents=True)
        pending = backend._run / "stoneglass-unit.tmp"
        pending.write_text("unit cleanup fixture, not an image")
        private = self.root / "unrelated.txt"; private.write_text("preserve")
        backend.unload()
        self.assertFalse(pending.exists())
        self.assertTrue(private.exists())
        backend._run.mkdir()
        source = backend._run / "stoneglass-unit.png"
        from PySide6.QtGui import QImage, QColor
        fixture = QImage(512, 512, QImage.Format.Format_RGB32)
        fixture.fill(QColor("#336699"))
        self.assertTrue(fixture.save(str(source), "PNG"))  # Static encoding fixture, not inference.
        result = GenerationResult(self.settings.output_directory / source.name, 1, 512, 512, "test")
        backend._pending = source, result
        backend.commit_result(result)
        backend.unload()
        self.assertTrue(result.image_path.exists())

    def test_output_path_escape_and_unknown_files_are_preserved_for_review(self):
        backend = SDXLProcessBackend(self.settings)
        backend._client = Mock()
        backend._client.call.return_value = {"image_path": "../outside.png", "seed": 1, "width": 512, "height": 512, "model_id": "test"}
        from stoneglass.domain.settings import GenerationSettings
        with self.assertRaises(InferenceError):
            backend.generate(GenerationRequest("private", "", GenerationSettings()), self.context)
        backend._run.mkdir(parents=True)
        unknown = backend._run / "unrecognized.txt"; unknown.write_text("preserve")
        with self.assertRaises(InferenceError): backend.unload()
        self.assertTrue(unknown.exists())

    def test_service_preserves_typed_preflight_error_and_commits_after_final_cancel_check(self):
        rig = make_rig(self.root)
        rig.backend.load_model.side_effect = InferenceError(ErrorCode.INVALID_RESOURCES, "Missing reviewed tokenizer data.")
        with self.assertLogs("stoneglass.services.inference", level="ERROR"):
            with self.assertRaises(InferenceError) as caught:
                rig.service.load_model(rig.model, RuntimeRequest(), rig.context)
        self.assertEqual(caught.exception.info.code, ErrorCode.INVALID_RESOURCES)
        self.assertEqual(str(caught.exception), "Missing reviewed tokenizer data.")
        rig.backend.load_model.side_effect = None
        rig.service.load_model(rig.model, RuntimeRequest(), rig.context)
        from stoneglass.domain.settings import GenerationSettings
        request = GenerationRequest("PRIVATE", "", GenerationSettings(seed=1))
        result = GenerationResult(self.root / "nonexistent-unit-result.png", 1, 1024, 1024, "test-model")
        rig.backend.generate.return_value = result
        rig.backend.commit_result = Mock()
        self.assertEqual(rig.service.generate(request, rig.context), result)
        rig.backend.commit_result.assert_called_once_with(result)
        rig.backend.commit_result.reset_mock()
        def progress(event):
            if event.stage is ProgressStage.GENERATING and event.percent == 100: rig.context.cancel.set()
        rig.context.report_event = progress
        with self.assertRaises(TaskCancelled): rig.service.generate(request, rig.context)
        rig.backend.commit_result.assert_not_called()
        rig.backend.unload.assert_called()

    def test_pipe_threads_close_and_do_not_log_private_stderr(self):
        process = Mock()
        process.stdin, process.stdout, process.stderr = io.BytesIO(), io.BytesIO(encode({"kind": "unit"})), io.BytesIO(b"PRIVATE_ERROR")
        channel = PipeChannel(process)
        self.assertEqual(channel.receive(1), {"kind": "unit"})
        channel.close()
        process.kill_tree_and_wait.assert_called_once()
        self.assertFalse(any(t.is_alive() for t in channel._threads))

    def test_pipe_writer_preserves_complete_frames_after_short_writes(self):
        from threading import Event
        message = {"schema": 1, "id": 1, "operation": "close", "payload": {}}
        expected, completed = encode(message), Event()
        class ShortWriter(io.BytesIO):
            def write(self, data):
                count = super().write(data[:3])
                if self.getvalue() == expected: completed.set()
                return count
        process = Mock()
        process.stdin, process.stdout, process.stderr = ShortWriter(), io.BytesIO(), io.BytesIO()
        channel = PipeChannel(process)
        try:
            channel.send(message)
            self.assertTrue(completed.wait(2))
            self.assertEqual(process.stdin.getvalue(), expected)
        finally:
            channel.close()

    def test_resource_preflight_failure_preserves_loaded_model_before_runtime_selection(self):
        rig = make_rig(self.root)
        rig.service.load_model(rig.model, RuntimeRequest(), rig.context)
        original = rig.service.status
        rig.detector.detect.reset_mock()
        rig.provider.validate_resources = Mock(side_effect=InferenceError(ErrorCode.INVALID_RESOURCES, "Missing local bundle."))
        with self.assertRaises(InferenceError):
            rig.service.load_model(replace(rig.model, model_id="replacement"), RuntimeRequest(), rig.context)
        self.assertEqual(rig.service.status, original)
        rig.detector.detect.assert_not_called()
        rig.backend.unload.assert_not_called()
