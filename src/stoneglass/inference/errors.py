# SPDX-License-Identifier: GPL-3.0-or-later

"""Stable, prompt-safe errors crossing the inference/application boundary."""

from dataclasses import dataclass
from enum import Enum


class ErrorCode(str, Enum):
    BACKEND_UNAVAILABLE = "backend_unavailable"
    RUNTIME_UNAVAILABLE = "runtime_unavailable"
    INVALID_MODEL = "invalid_model"
    INVALID_REQUEST = "invalid_request"
    BUSY = "busy"
    NOT_READY = "not_ready"
    CLOSED = "closed"
    LOAD_FAILED = "load_failed"
    GENERATION_FAILED = "generation_failed"
    CLEANUP_FAILED = "cleanup_failed"
    INVALID_RESOURCES = "invalid_resources"
    ISOLATION_UNAVAILABLE = "isolation_unavailable"
    OFFLINE_POLICY = "offline_policy"
    WORKER_FAILED = "worker_failed"
    OPERATION_TIMEOUT = "operation_timeout"


@dataclass(frozen=True)
class ErrorInfo:
    code: ErrorCode
    message: str


class InferenceError(Exception):
    """Messages must be safe to display and log; never include prompts."""

    def __init__(self, code: ErrorCode, message: str) -> None:
        self.info = ErrorInfo(code, message)
        super().__init__(message)
