# SPDX-License-Identifier: GPL-3.0-or-later

"""Isolated, optional PyTorch smoke test. No models, downloads or UI imports."""

import importlib
import json
import sys
from collections.abc import Callable
from typing import Any


def probe(loader: Callable[[str], Any] = importlib.import_module) -> dict[str, Any]:
    report: dict[str, Any] = {
        "schema": 1, "platform": sys.platform, "torch_version": None,
        "hip_version": None, "cuda_version": None, "devices": [], "diagnostics": [],
    }
    try:
        torch = loader("torch")
    except ModuleNotFoundError as exc:
        report["diagnostics"].append("torch_missing" if exc.name == "torch" else "torch_import_failed")
        return report
    except Exception:
        report["diagnostics"].append("torch_import_failed")
        return report

    report.update(torch_version=str(torch.__version__), hip_version=torch.version.hip,
                  cuda_version=torch.version.cuda)

    def validate(device: str) -> None:
        value = torch.tensor([1.0], dtype=torch.float32, device=device)
        if (value + 2).item() != 3.0:
            raise ValueError("Tensor arithmetic check failed.")

    try:
        validate("cpu")
        report["devices"].append({"kind": "cpu", "index": None, "name": "CPU", "validated": True})
    except Exception:
        report["diagnostics"].append("cpu_validation_failed")

    try:
        if not torch.cuda.is_available():
            report["diagnostics"].append("gpu_not_available")
            return report
        kind = "rocm" if torch.version.hip else "cuda" if torch.version.cuda else None
        if kind is None:
            report["diagnostics"].append("unknown_gpu_build")
            return report
        count = torch.cuda.device_count()
        if type(count) is not int or not 0 < count <= 64:
            raise ValueError("Invalid device count.")
        for index in range(count):
            try:
                validate(f"cuda:{index}")
                torch.cuda.synchronize(index)
                name = str(torch.cuda.get_device_name(index))
                getter = getattr(torch.cuda, "get_device_properties", None)
                architecture = getattr(getter(index), "gcnArchName", None) if kind == "rocm" and callable(getter) else None
                report["devices"].append({
                    "kind": kind, "index": index, "name": name, "validated": True,
                    "gcn_arch": architecture if isinstance(architecture, str) else None,
                })
            except Exception:
                report["diagnostics"].append(f"gpu_validation_failed:{index}")
    except Exception:
        report["diagnostics"].append("gpu_query_failed")
    return report


if __name__ == "__main__":
    # Never serialize framework exception text, environment variables or paths.
    print(json.dumps(probe()))
