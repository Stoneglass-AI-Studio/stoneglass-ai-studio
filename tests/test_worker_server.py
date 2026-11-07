# SPDX-License-Identifier: GPL-3.0-or-later
"""In-memory worker protocol tests with mocked operations, not model execution."""

import io
import os
import json
import unittest
from queue import Queue
from threading import Event, Thread
from unittest.mock import Mock, patch

from stoneglass.inference.protocol import encode
from stoneglass.inference.worker_server import WorkerEngine, run_protocol


class Source:
    def __init__(self): self.queue = Queue()
    def readline(self, limit): return self.queue.get(timeout=3)
    def put(self, value): self.queue.put(encode(value))
    def close(self): self.queue.put(b"")


class Target:
    def __init__(self): self.queue = Queue()
    def write(self, value): self.queue.put(json.loads(value))
    def flush(self): pass
    def next(self): return self.queue.get(timeout=3)


class WorkerServerTests(unittest.TestCase):
    def setUp(self):
        self.source, self.target, self.engine = Source(), Target(), Mock()
        self.errors = []
        def serve():
            try: run_protocol(self.source, self.target, self.engine, redirect=io.StringIO())
            except Exception as exc: self.errors.append(type(exc).__name__)
        self.thread = Thread(target=serve, daemon=True)
        self.thread.start()
        self.assertEqual(self.target.next()["kind"], "ready")

    def tearDown(self):
        self.source.close()
        self.thread.join(3)
        self.assertFalse(self.thread.is_alive())

    def send(self, number, operation):
        self.source.put({"schema": 1, "id": number, "operation": operation, "payload": {}})

    def test_success_and_close_use_owned_engine_cleanup(self):
        self.engine.dispatch.return_value = {"unit": "metadata"}
        self.send(1, "load")
        self.assertEqual(self.target.next()["payload"], {"unit": "metadata"})
        self.send(2, "close")
        self.assertEqual(self.target.next()["kind"], "result")
        self.thread.join(2)
        self.engine.close.assert_called()
        self.assertEqual(self.errors, [])

    def test_arbitrary_dependency_error_is_redacted_and_cleans(self):
        self.engine.dispatch.side_effect = RuntimeError("PRIVATE_PROMPT_OR_TOKEN")
        self.send(1, "load")
        response = self.target.next()
        self.assertEqual(response["kind"], "error")
        self.assertNotIn("PRIVATE", json.dumps(response))
        self.thread.join(2)
        self.engine.close.assert_called()

    def test_control_reader_cancels_operation_without_waiting_for_dispatch(self):
        started = Event()
        def dispatch(operation, payload, context):
            started.set()
            while True:
                context.check_cancelled()
                Event().wait(0.005)
        self.engine.dispatch.side_effect = dispatch
        self.send(1, "load")
        self.assertTrue(started.wait(2))
        self.send(1, "cancel")
        self.assertEqual(self.target.next()["kind"], "cancelled")
        self.engine.close.assert_called()

    def test_unknown_engine_operation_has_no_download_implementation(self):
        engine = WorkerEngine()
        from stoneglass.inference.offline import OFFLINE_FLAGS
        with patch.dict(os.environ, OFFLINE_FLAGS), self.assertRaises(ValueError):
            engine.dispatch("download", {}, Mock())
