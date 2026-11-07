# SPDX-License-Identifier: GPL-3.0-or-later

import json
import subprocess
import unittest
from unittest.mock import Mock

from stoneglass.domain.hardware import GpuVendor
from stoneglass.services.hardware import HardwareService, identify_vendor, parse_adapters


class HardwareTests(unittest.TestCase):
    def test_pci_ids_identify_amd_nvidia_and_intel_without_cuda(self) -> None:
        for device, vendor in (("1002", GpuVendor.AMD), ("10DE", GpuVendor.NVIDIA),
                               ("8086", GpuVendor.INTEL)):
            with self.subTest(vendor=vendor):
                self.assertEqual(identify_vendor("Generic adapter", "", f"PCI\\VEN_{device}"), vendor)

    def test_name_and_manufacturer_fallback(self) -> None:
        for name, manufacturer, expected in (
            ("AMD Radeon RX 9060 XT", "", GpuVendor.AMD),
            ("GeForce RTX 3090", "NVIDIA", GpuVendor.NVIDIA),
            ("Display adapter", "Advanced Micro Devices, Inc.", GpuVendor.AMD),
            ("Intel Arc", "", GpuVendor.INTEL),
            ("Microsoft Basic Display Adapter", "Microsoft", GpuVendor.UNKNOWN),
        ):
            with self.subTest(name=name):
                self.assertEqual(identify_vendor(name, manufacturer, ""), expected)

    def test_multiple_adapters(self) -> None:
        raw = json.dumps([
            {"Name": "AMD Radeon RX 9060 XT", "PNPDeviceID": "PCI\\VEN_1002", "DriverVersion": "1.2"},
            {"Name": "NVIDIA GeForce RTX 3090", "PNPDeviceID": "PCI\\VEN_10DE"},
        ])
        runner = Mock(return_value=subprocess.CompletedProcess([], 0, stdout=raw))
        report = HardwareService(runner, system="win32").detect()
        self.assertEqual([gpu.vendor for gpu in report.gpus], [GpuVendor.AMD, GpuVendor.NVIDIA])
        self.assertEqual(report.gpus[0].driver_version, "1.2")
        self.assertIsNone(report.warning)
        arguments = runner.call_args.kwargs
        self.assertEqual(arguments["timeout"], 15)
        self.assertNotIn("shell", arguments)

    def test_single_adapter_object_and_bom(self) -> None:
        adapters = parse_adapters('\ufeff{"Name":"Radeon Graphics"}')
        self.assertEqual(len(adapters), 1)
        self.assertEqual(adapters[0].vendor, GpuVendor.AMD)

    def test_empty_inventory_is_valid(self) -> None:
        for raw in ("", "null", "[]"):
            self.assertEqual(parse_adapters(raw), ())

    def test_invalid_inventory_is_reported(self) -> None:
        for raw in ("invalid", "[null]", "123"):
            runner = Mock(return_value=subprocess.CompletedProcess([], 0, stdout=raw))
            with self.assertLogs("stoneglass.services.hardware", level="ERROR"):
                report = HardwareService(runner, "win32").detect()
            self.assertIsNotNone(report.warning)
            self.assertEqual(report.gpus, ())

    def test_detection_failures_are_readable(self) -> None:
        for error in (FileNotFoundError(), subprocess.TimeoutExpired("powershell", 15),
                      subprocess.CalledProcessError(1, "powershell")):
            with self.subTest(error=type(error).__name__):
                with self.assertLogs("stoneglass.services.hardware", level="ERROR"):
                    report = HardwareService(Mock(side_effect=error), "win32").detect()
                self.assertIn("GPU detection failed", report.summary)

    def test_non_windows_does_not_run_powershell(self) -> None:
        runner = Mock()
        report = HardwareService(runner, "linux").detect()
        runner.assert_not_called()
        self.assertIn("Windows only", report.summary)
