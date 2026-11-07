# SPDX-License-Identifier: GPL-3.0-or-later
"""Ordinary-user -I -S worker; library policy is checked before dependencies."""

import struct
import sys
from pathlib import Path

# -S avoids editable/.pth/sitecustomize hooks. Import only
# Stoneglass's dependency-free policy modules from this checked source tree.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from stoneglass.inference.errors import ErrorCode, InferenceError
from stoneglass.inference.offline import assert_library_policy
from stoneglass.inference.protocol import encode
from stoneglass.inference.resources import strict_local


def main() -> int:
    try:
        assert_library_policy()
        if sys.version_info[:3] != (3, 13, 12) or struct.calcsize("P") != 8:
            raise InferenceError(ErrorCode.RUNTIME_UNAVAILABLE, "The worker requires Python 3.13.12 x64.")
        environment = Path(sys.executable).parent.parent
        config = strict_local(environment / "pyvenv.cfg")
        if "include-system-site-packages = false" not in config.read_text(encoding="utf-8").lower():
            raise InferenceError(ErrorCode.RUNTIME_UNAVAILABLE, "Use an isolated local inference virtual environment.")
        packages = strict_local(environment / "Lib/site-packages", directory=True)
    except InferenceError as exc:
        sys.stdout.buffer.write(encode({"schema": 1, "id": 0, "kind": "error", "code": exc.info.code.value,
                                       "message": exc.info.message, "inference_imported": any(
                                           name in sys.modules for name in ("torch", "diffusers", "transformers"))}))
        sys.stdout.buffer.flush()
        return 2
    # Never call site.addsitedir: it would execute arbitrary .pth hooks.
    # Python 3.13 -S omits venv prefix setup. SDK scripts/DLL discovery must use
    # this environment, not the base interpreter's unrelated Scripts directory.
    sys.prefix = sys.exec_prefix = str(environment)
    sys.path.append(str(packages))
    from stoneglass.inference.worker_server import WorkerEngine, run_protocol
    from stoneglass.inference.pipe_input import WorkerPipeInput
    # Polling avoids a long blocking input call during native-library imports
    # and CPython's standard-buffer lock during interpreter finalization.
    source = WorkerPipeInput()
    run_protocol(source, sys.stdout.buffer, WorkerEngine(), redirect=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
