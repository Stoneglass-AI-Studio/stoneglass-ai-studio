# SPDX-License-Identifier: GPL-3.0-or-later
"""Bounded JSON pipe messages, without pickle, prompts in argv, files or sockets."""

import json
from typing import Any, BinaryIO

from stoneglass.inference.errors import ErrorCode, InferenceError
from stoneglass.inference.resources import json_object

MAX_FRAME = 1024 * 1024


def encode(message: dict[str, Any]) -> bytes:
    data = json.dumps(message, allow_nan=False, ensure_ascii=True, separators=(",", ":")).encode("ascii") + b"\n"
    if len(data) > MAX_FRAME:
        raise InferenceError(ErrorCode.INVALID_REQUEST, "The worker request exceeds the supported size.")
    return data


def read_frame(stream: BinaryIO) -> dict[str, Any] | None:
    line = stream.readline(MAX_FRAME + 1)
    if not line:
        return None
    if len(line) > MAX_FRAME or not line.endswith(b"\n"):
        raise InferenceError(ErrorCode.WORKER_FAILED, "Invalid or oversized inference-worker message.")
    try:
        return json_object(line)
    except InferenceError:
        raise InferenceError(ErrorCode.WORKER_FAILED, "Malformed inference-worker message.") from None
