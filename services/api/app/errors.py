"""The application error contract (`docs/08_API_AND_DATA_CONTRACTS.md` section 19).

Errors are structured codes, never string matching across layers, and never leak a
stack trace or a filesystem path to the client.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

# Upload validation codes are fixed by the contract.
UNSUPPORTED_MEDIA_TYPE = "unsupported_media_type"
FILE_TOO_LARGE = "file_too_large"
INVALID_PDF = "invalid_pdf"
ENCRYPTED_PDF = "encrypted_pdf"
STORAGE_FAILURE = "storage_failure"
NOT_FOUND = "not_found"
CONFLICT = "conflict"
FEEDBACK_FIELD_REQUIRED = "feedback_field_required"
FEEDBACK_FIELD_INVALID = "feedback_field_invalid"
PARSER_STRATEGY_UNDECIDED = "parser_strategy_undecided"
AI_WORKER_UNAVAILABLE = "ai_worker_unavailable"
DOCUMENT_NOT_INDEXED = "document_not_indexed"
ARCHIVE_NOT_INDEXED = "archive_not_indexed"
QA_SCOPE_VIOLATION = "qa_scope_violation"
INTERNAL_ERROR = "internal_error"


class ErrorBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    retryable: bool = False
    request_id: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    error: ErrorBody


class ApiError(Exception):
    """An error whose payload is part of the API contract."""

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 400,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.retryable = retryable
        self.details = details or {}

    def to_response(self, request_id: str) -> ErrorResponse:
        return ErrorResponse(
            error=ErrorBody(
                code=self.code,
                message=self.message,
                retryable=self.retryable,
                request_id=request_id,
                details=self.details,
            )
        )


async def api_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Render `ApiError` in the documented envelope."""
    assert isinstance(exc, ApiError)  # registered for ApiError only
    request_id = request.headers.get("x-request-id") or f"req_{uuid.uuid4().hex[:16]}"
    return JSONResponse(
        status_code=exc.status_code,
        content=exc.to_response(request_id).model_dump(mode="json"),
    )
