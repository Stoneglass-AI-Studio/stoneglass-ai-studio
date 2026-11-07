# SPDX-License-Identifier: GPL-3.0-or-later
"""Model-free runtime admission and pinned offline-library checks."""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from inference_support import Context
from stoneglass.inference.contracts import TaskCancelled
from stoneglass.inference.errors import ErrorCode, InferenceError
from stoneglass.inference.offline import OFFLINE_FLAGS, offline_environment
from stoneglass.inference.runtime_validation import validate_runtime
from stoneglass.inference.worker_server import WorkerEngine


class RuntimeValidationTests(unittest.TestCase):
    def test_missing_policy_and_cancellation_prevent_all_library_imports(self):
        with patch.dict(os.environ, {}, clear=True), patch("stoneglass.inference.runtime_validation.importlib.import_module") as load:
            with self.assertRaises(InferenceError) as caught: validate_runtime(Context())
            self.assertEqual(caught.exception.info.code, ErrorCode.OFFLINE_POLICY)
            load.assert_not_called()
        context = Context(); context.cancel.set()
        with patch.dict(os.environ, OFFLINE_FLAGS), patch("stoneglass.inference.runtime_validation.importlib.import_module") as load:
            with self.assertRaises(TaskCancelled): validate_runtime(context)
            load.assert_not_called()

    def test_unreviewed_runtime_never_executes_gpu_operations(self):
        torch = SimpleNamespace(__version__="unreviewed", cuda=Mock())
        with patch.dict(os.environ, OFFLINE_FLAGS), \
             patch("stoneglass.inference.runtime_validation.importlib.import_module", return_value=torch):
            with self.assertRaises(InferenceError) as caught: validate_runtime(Context())
        self.assertEqual(caught.exception.info.code, ErrorCode.RUNTIME_UNAVAILABLE)
        torch.cuda.is_available.assert_not_called()

    def test_validation_operation_requires_empty_payload_and_no_loaded_adapter(self):
        with patch.dict(os.environ, OFFLINE_FLAGS), patch("stoneglass.inference.runtime_validation.validate_runtime") as validate:
            engine = WorkerEngine()
            with self.assertRaises(ValueError): engine.dispatch("validate_runtime", {"path": "not allowed"}, Context())
            engine._adapter = Mock()
            with self.assertRaises(ValueError): engine.dispatch("validate_runtime", {}, Context())
            validate.assert_not_called()

    def test_pinned_hub_offline_request_fails_before_any_http_transport(self):
        project = Path(__file__).resolve().parents[1]
        python = project / ".venv-rocm/Scripts/python.exe"
        if not python.exists(): self.skipTest("Optional reviewed ROCm environment is not installed")
        code = '''import sys
from pathlib import Path
sys.path.append(str(Path(sys.executable).parent.parent / "Lib/site-packages"))
from unittest.mock import patch
import httpx
from huggingface_hub import get_session, hf_hub_download
from huggingface_hub.errors import OfflineModeIsEnabled, LocalEntryNotFoundError
with patch.object(httpx.HTTPTransport, "handle_request", side_effect=AssertionError("HTTP transport used")) as transport:
    try: get_session().get("https://stoneglass-offline-test.invalid/never-connect")
    except OfflineModeIsEnabled: pass
    else: raise AssertionError("Hub did not enforce offline policy")
    try: hf_hub_download("stoneglass-offline-test/missing", "missing.json", local_files_only=True, token=False)
    except LocalEntryNotFoundError: pass
    else: raise AssertionError("Missing local file did not fail")
    transport.assert_not_called()
print("offline rejection passed; transport calls=0")
'''
        with tempfile.TemporaryDirectory() as temporary:
            result = subprocess.run([str(python), "-I", "-S", "-B", "-c", code],
                                    env=offline_environment(Path(temporary)), capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
        self.assertIn(b"transport calls=0", result.stdout)
