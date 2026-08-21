"""Typed contracts for AI worker error codes, exceptions, and response schemas."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class WorkerErrorCode(StrEnum):
    UNAUTHORIZED = "unauthorized"
    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"
    MODEL_NOT_LOADED = "model_not_loaded"
    BAD_REQUEST = "bad_request"
    UPSTREAM_ERROR = "upstream_error"


_ERROR_DEFAULTS: dict[WorkerErrorCode, tuple[str, int, bool]] = {
    WorkerErrorCode.UNAUTHORIZED: ("Authentication required or invalid token", 401, False),
    WorkerErrorCode.TIMEOUT: ("Worker operation timed out", 504, True),
    WorkerErrorCode.UNAVAILABLE: ("AI worker is unavailable", 503, True),
    WorkerErrorCode.MODEL_NOT_LOADED: ("Requested model is not loaded", 503, True),
    WorkerErrorCode.BAD_REQUEST: ("Bad request payload or parameter", 400, False),
    WorkerErrorCode.UPSTREAM_ERROR: ("Upstream provider error", 502, True),
}


class WorkerError(Exception):
    """Exception representing an AI worker error matching the contract schema."""

    code: WorkerErrorCode
    retryable: bool

    def __init__(
        self,
        code: WorkerErrorCode,
        message: str = "",
        *,
        retryable: bool | None = None,
        status_code: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        default_message, default_status, default_retryable = _ERROR_DEFAULTS.get(
            code, ("Worker error", 500, False)
        )
        self.code = code
        self.message = message or default_message
        self.retryable = retryable if retryable is not None else default_retryable
        self.status_code = status_code if status_code is not None else default_status
        self.details = details or {}
        super().__init__(self.message)


class WorkerErrorBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    retryable: bool = False
    request_id: str
    details: dict[str, Any] = Field(default_factory=dict)


class WorkerErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    error: WorkerErrorBody
