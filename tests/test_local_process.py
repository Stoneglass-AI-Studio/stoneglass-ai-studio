# SPDX-License-Identifier: GPL-3.0-or-later
"""Model-free native lifetime/IPC tests. Never change Windows security settings."""

import ctypes
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from inference_support import Context
from stoneglass.inference.contracts import ProgressStage
from stoneglass.inference.errors import ErrorCode, InferenceError
from stoneglass.inference.local_process import LocalWorkerLauncher, _api, _spawn_owned
from stoneglass.inference.offline import offline_environment
from stoneglass.inference.worker import LaunchSpec, WorkerClient, WorkerSettings


@unittest.skipUnless(sys.platform == "win32", "Windows process ownership")
class LocalProcessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="stoneglass-process-test-")
        self.root = Path(self.temp.name)
        self.project = Path(__file__).resolve().parents[1]

    def tearDown(self):
        self.temp.cleanup()

    def fixture(self, code):
        path = self.root / "model-free-fixture.py"
        path.write_text(code, encoding="utf-8")
        return LaunchSpec((sys.executable, "-I", "-S", "-B", str(path)), dict(os.environ), self.root)

    def finish(self, process):
        process.kill_tree_and_wait(5)
        for stream in (process.stdin, process.stdout, process.stderr):
            stream.close()

    def test_production_worker_default_launcher_ready_unload_and_normal_close(self):
        interpreter = self.project / ".venv-rocm/Scripts/python.exe"
        if not interpreter.exists():
            interpreter = Path(sys.executable)
        settings = WorkerSettings(interpreter, self.root / "data", self.root / "output")
        client = WorkerClient(settings)
        try:
            self.assertEqual(client.call("unload", {}, Context(), timeout=10, stage=ProgressStage.UNLOADING), {})
            process = client._channel._process
        finally:
            client.close()
        self.assertEqual(process.poll(), 0)
        client.close()
        self.assertTrue((settings.data_directory / "tmp").is_dir())

    def test_unreviewed_entrypoint_is_rejected_before_spawning(self):
        spec = self.fixture("raise AssertionError('must not run')")
        with patch("stoneglass.inference.local_process._spawn_owned") as spawn:
            with self.assertRaises(InferenceError): LocalWorkerLauncher().start(spec)
            spawn.assert_not_called()

    def test_job_assignment_failure_does_not_resume_worker(self):
        marker = self.root / "must-not-exist"
        spec = self.fixture(f"from pathlib import Path; Path({str(marker)!r}).touch()")
        with patch.object(_api(), "AssignProcessToJobObject", return_value=0):
            with self.assertRaisesRegex(InferenceError, "job assignment"):
                _spawn_owned(spec)
        self.assertFalse(marker.exists())

    def test_cleanup_failure_retains_native_handles_and_retry_reaps(self):
        process = _spawn_owned(self.fixture("import time; time.sleep(60)"))
        try:
            with patch.object(_api(), "QueryInformationJobObject", return_value=0):
                with self.assertRaises(InferenceError) as caught: process.kill_tree_and_wait(2)
            self.assertEqual(caught.exception.info.code, ErrorCode.CLEANUP_FAILED)
            self.assertIsNotNone(process._process)
            process.kill_tree_and_wait(5)
            self.assertIsNone(process._process)
            process.kill_tree_and_wait(5)
        finally:
            self.finish(process)

    def child_handle(self, pid):
        from ctypes import wintypes
        function = _api().OpenProcess
        function.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        function.restype = wintypes.HANDLE
        handle = function(0x100000, False, pid)  # SYNCHRONIZE only, for our known live child.
        self.assertTrue(handle)
        return handle

    def test_owned_job_reaps_descendants_without_touching_unrelated_process(self):
        other = subprocess.Popen([sys.executable, "-I", "-S", "-c", "import time; time.sleep(60)"],
                                 creationflags=subprocess.CREATE_NO_WINDOW)
        spec = self.fixture("import subprocess,sys,time\n"
            "p=subprocess.Popen([sys.executable,'-I','-S','-c','import time; time.sleep(60)'],"
            "stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)\n"
            "print(p.pid,flush=True)\ntime.sleep(60)\n")
        process = _spawn_owned(spec)
        handle = None
        try:
            pid = int(process.stdout.readline())
            handle = self.child_handle(pid)
            process.kill_tree_and_wait(5)
            self.assertEqual(_api().WaitForSingleObject(handle, 5000), 0)
            self.assertIsNone(other.poll())
        finally:
            if handle: _api().CloseHandle(handle)
            self.finish(process)
            other.kill()
            other.wait(timeout=5)

    def test_job_kill_on_parent_exit(self):
        child_spec = self.fixture("import time; print('ready',flush=True); time.sleep(60)")
        helper = self.root / "parent-exit.py"
        helper.write_text(
            "import os,sys\nfrom pathlib import Path\n"
            f"sys.path.insert(0,{str(self.project / 'src')!r})\n"
            "from stoneglass.inference.worker import LaunchSpec\n"
            "from stoneglass.inference.local_process import _spawn_owned\n"
            f"p=_spawn_owned(LaunchSpec({child_spec.command!r},dict(os.environ),Path({str(self.root)!r})))\n"
            "assert p.stdout.readline().strip()==b'ready'\n"
            "print(p.pid,flush=True)\nsys.stdin.readline()\nos._exit(0)\n", encoding="utf-8")
        parent = subprocess.Popen([sys.executable, "-I", "-S", "-B", str(helper)], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW)
        handle = None
        try:
            handle = self.child_handle(int(parent.stdout.readline()))
            parent.communicate(b"exit\n", timeout=10)
            self.assertEqual(parent.returncode, 0)
            self.assertEqual(_api().WaitForSingleObject(handle, 5000), 0)
        finally:
            if parent.poll() is None: parent.kill(); parent.communicate(timeout=5)
            if handle: _api().CloseHandle(handle)
