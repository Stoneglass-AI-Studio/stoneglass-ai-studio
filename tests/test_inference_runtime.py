# SPDX-License-Identifier: GPL-3.0-or-later

import json
import subprocess
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

from inference_support import Context
from stoneglass.inference._torch_probe import probe
from stoneglass.inference.contracts import RuntimeKind, RuntimeRequest, TaskCancelled
from stoneglass.inference.errors import InferenceError
from stoneglass.inference.runtime import TorchRuntimeDetector, parse_capabilities, select_runtime


def mock_torch(*, hip: str | None = None, cuda: str | None = "test-cuda") -> MagicMock:
    torch = MagicMock()
    torch.__version__ = "unit-test-version"
    torch.version = SimpleNamespace(hip=hip, cuda=cuda)
    torch.cuda.is_available.return_value = True
    torch.cuda.device_count.return_value = 2
    torch.cuda.get_device_name.side_effect = lambda index: f"Mock device {index}"
    torch.tensor.return_value.__add__.return_value.item.return_value = 3.0
    return torch


class RuntimeProbeTests(unittest.TestCase):
    def test_missing_and_broken_torch_do_not_claim_cpu_or_gpu_support(self) -> None:
        for error,diagnostic in (
            (ModuleNotFoundError(name="torch"), "torch_missing"),
            (ModuleNotFoundError(name="some_torch_dependency"), "torch_import_failed"),
            (OSError("PRIVATE_PATH"), "torch_import_failed"),
        ):
            with self.subTest(diagnostic=diagnostic):
                report = probe(Mock(side_effect=error))
                self.assertEqual(report["devices"], [])
                self.assertEqual(report["diagnostics"], [diagnostic])
                self.assertNotIn("PRIVATE", json.dumps(report))

    def test_cuda_is_available_does_not_mislabel_hip_as_nvidia(self) -> None:
        torch = mock_torch(hip="test-hip", cuda=None)
        report = parse_capabilities(json.dumps(probe(Mock(return_value=torch))))
        self.assertEqual([d.kind for d in report.devices], [RuntimeKind.CPU, RuntimeKind.ROCM, RuntimeKind.ROCM])
        self.assertEqual(report.devices[1].torch_device, "cuda:0")
        self.assertEqual([c.kwargs["device"] for c in torch.tensor.call_args_list], ["cpu", "cuda:0", "cuda:1"])
        self.assertEqual(torch.cuda.synchronize.call_count, 2)

    def test_cuda_build_and_each_gpu_are_actually_validated(self) -> None:
        torch = mock_torch()
        tensor = torch.tensor.return_value
        def allocate(*args, **kwargs):
            if kwargs["device"] == "cuda:0":
                raise RuntimeError("Unsupported kernel PRIVATE_PATH")
            return tensor
        torch.tensor.side_effect = allocate
        raw = probe(Mock(return_value=torch))
        report = parse_capabilities(json.dumps(raw))
        self.assertEqual([(d.kind,d.index) for d in report.devices], [(RuntimeKind.CPU,None),(RuntimeKind.CUDA,1)])
        self.assertIn("gpu_validation_failed:0", report.diagnostics)
        self.assertNotIn("PRIVATE", json.dumps(raw))

    def test_cpu_only_and_unknown_gpu_build_remain_honest(self) -> None:
        torch = mock_torch(cuda=None)
        raw = probe(Mock(return_value=torch))
        self.assertEqual([d["kind"] for d in raw["devices"]], ["cpu"])
        self.assertIn("unknown_gpu_build", raw["diagnostics"])
        torch.cuda.is_available.return_value = False
        raw = probe(Mock(return_value=torch))
        self.assertIn("gpu_not_available", raw["diagnostics"])

    def test_runtime_selection_is_explicit_and_cpu_fallback_requires_backend_support(self) -> None:
        report = parse_capabilities(json.dumps(probe(Mock(return_value=mock_torch()))))
        supported = frozenset({RuntimeKind.CPU, RuntimeKind.CUDA})
        self.assertEqual(select_runtime(report, RuntimeRequest(), supported).kind, RuntimeKind.CUDA)
        self.assertEqual(select_runtime(report, RuntimeRequest(device_index=1), supported).index, 1)
        cpu_only = frozenset({RuntimeKind.CPU})
        with self.assertRaises(InferenceError):
            select_runtime(report, RuntimeRequest(), cpu_only)
        self.assertEqual(select_runtime(report, RuntimeRequest(allow_cpu_fallback=True), cpu_only).kind, RuntimeKind.CPU)
        self.assertEqual(select_runtime(report, RuntimeRequest(RuntimeKind.CPU), cpu_only).torch_device, "cpu")
        for request in (RuntimeRequest(RuntimeKind.ROCM, allow_cpu_fallback=True), RuntimeRequest(device_index=-1)):
            with self.assertRaises(InferenceError):
                select_runtime(report, request, supported)
        with self.assertRaises(InferenceError):
            select_runtime(report, RuntimeRequest(allow_cpu_fallback=True), frozenset())

    def test_unvalidated_devices_and_missing_build_metadata_are_rejected(self) -> None:
        raw = probe(Mock(return_value=mock_torch()))
        raw["devices"][1]["validated"] = False
        with self.assertRaises(ValueError):
            parse_capabilities(json.dumps(raw))
        raw["devices"][1]["validated"] = True
        raw["cuda_version"] = None
        with self.assertRaises(ValueError):
            parse_capabilities(json.dumps(raw))

    def test_core_import_needs_neither_qt_nor_inference_dependencies(self) -> None:
        code = (
            "import sys; from stoneglass.services.inference import InferenceService; "
            "InferenceService(); "
            "assert not any(n in sys.modules for n in ('PySide6', 'torch', 'diffusers'))"
        )
        subprocess.run([sys.executable, "-B", "-c", code], check=True, timeout=10)


class RuntimeProcessTests(unittest.TestCase):
    def process(self, stdout: str, *, returncode: int = 0) -> Mock:
        process = Mock()
        process.communicate.return_value = (stdout, "PRIVATE_PROCESS_STDERR")
        process.returncode = returncode
        process.poll.return_value = returncode
        return process

    def test_successful_subprocess_is_bounded_and_does_not_import_torch_in_parent(self) -> None:
        raw = json.dumps(probe(Mock(return_value=mock_torch())))
        process = self.process(raw)
        factory = Mock(return_value=process)
        report = TorchRuntimeDetector(factory).detect(Context())
        self.assertEqual(len(report.devices), 3)
        self.assertEqual(factory.call_args.args[0][0], sys.executable)
        self.assertIn("_torch_probe.py", factory.call_args.args[0][-1])
        self.assertLessEqual(process.communicate.call_args.kwargs["timeout"], 0.1)
        process.kill.assert_not_called()
        self.assertNotIn("torch", sys.modules)

    def test_cancelled_probe_kills_and_reaps_only_its_child(self) -> None:
        context = Context()
        process = self.process("")
        process.poll.return_value = None
        def communicate(*args, **kwargs):
            if kwargs["timeout"] == 2:
                return ("", "")
            context.cancel.set()
            raise subprocess.TimeoutExpired("unit-test-probe", 0.1)
        process.communicate.side_effect = communicate
        with self.assertRaises(TaskCancelled):
            TorchRuntimeDetector(Mock(return_value=process)).detect(context)
        process.kill.assert_called_once()
        self.assertEqual(process.communicate.call_args.kwargs["timeout"], 2)

    def test_hung_probe_times_out_and_is_reaped(self) -> None:
        process = self.process("")
        process.poll.return_value = None
        report = TorchRuntimeDetector(Mock(return_value=process), timeout=1, clock=Mock(side_effect=[0,2])).detect(Context())
        self.assertEqual(report.devices, ())
        self.assertEqual(report.diagnostics, ("probe_timeout",))
        process.kill.assert_called_once()

    def test_crashed_malformed_or_unstartable_probes_fail_closed(self) -> None:
        for factory in (
            Mock(return_value=self.process("not-json")),
            Mock(return_value=self.process("{}", returncode=1)),
            Mock(side_effect=OSError("PRIVATE_EXECUTABLE_PATH")),
        ):
            report = TorchRuntimeDetector(factory).detect(Context())
            self.assertEqual(report.devices, ())
            self.assertEqual(report.diagnostics, ("probe_failed",))
            self.assertNotIn("PRIVATE", repr(report))
