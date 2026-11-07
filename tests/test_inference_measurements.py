# SPDX-License-Identifier: GPL-3.0-or-later
"""Local counters only; no GPU, model, or external monitoring dependency."""

import json
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from stoneglass.inference.measurements import host_memory, runtime_memory


@unittest.skipUnless(sys.platform == "win32", "Windows process memory counters")
class InferenceMeasurementTests(unittest.TestCase):
    def test_current_process_counters_are_consistent_and_serializable(self):
        counters = host_memory()
        self.assertGreater(counters["working_set_bytes"], 0)
        self.assertGreaterEqual(counters["lifetime_peak_working_set_bytes"], counters["working_set_bytes"])
        self.assertGreaterEqual(counters["private_bytes"], 0)
        json.dumps(counters)

    def test_gpu_counter_sample_uses_selected_device_without_tensor_operations(self):
        cuda = Mock()
        cuda.memory_allocated.return_value = 10
        cuda.memory_reserved.return_value = 20
        cuda.max_memory_allocated.return_value = 30
        cuda.max_memory_reserved.return_value = 40
        counters = runtime_memory(SimpleNamespace(cuda=cuda), 2)
        self.assertEqual(counters["gpu_peak_allocated_bytes"], 30)
        for function in (cuda.memory_allocated, cuda.memory_reserved, cuda.max_memory_allocated, cuda.max_memory_reserved):
            function.assert_called_once_with(2)
        json.dumps(counters)
