"""Common structured error schema shared by every parser adapter."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ParserErrorCode(StrEnum):
    """Stable error codes every adapter must map its provider failures onto."""

    PROVIDER_UNAVAILABLE = "provider_unavailable"
    ENCRYPTED_PDF = "encrypted_pdf"
    INVALID_PDF = "invalid_pdf"
    UNSUPPORTED_INPUT = "unsupported_input"
    PARSE_TIMEOUT = "parse_timeout"
    PROVIDER_FAILURE = "provider_failure"
    NORMALIZATION_FAILURE = "normalization_failure"
    RECORDING_MISSING = "recording_missing"
    PARSER_STRATEGY_UNDECIDED = "parser_strategy_undecided"


RETRYABLE_CODES = frozenset(
    {
        ParserErrorCode.PARSE_TIMEOUT,
        ParserErrorCode.PROVIDER_FAILURE,
    }
)


class ParserErrorModel(BaseModel):
    """Serializable error payload recorded in benchmark artifacts."""

    model_config = ConfigDict(extra="forbid")

    code: ParserErrorCode
    message: str = Field(min_length=1)
    retryable: bool
    parser_name: str = Field(min_length=1)
    details: dict[str, Any] = Field(default_factory=dict)


class ParserError(Exception):
    """Raised by adapters; always carries a structured, serializable payload."""

    def __init__(
        self,
        code: ParserErrorCode,
        message: str,
        parser_name: str,
        details: dict[str, Any] | None = None,
        retryable: bool | None = None,
    ) -> None:
        super().__init__(message)
        self.model = ParserErrorModel(
            code=code,
            message=message,
            retryable=code in RETRYABLE_CODES if retryable is None else retryable,
            parser_name=parser_name,
            details=details or {},
        )

    @property
    def code(self) -> ParserErrorCode:
        return self.model.code

    @property
    def retryable(self) -> bool:
        return self.model.retryable

    def to_dict(self) -> dict[str, Any]:
        return self.model.model_dump(mode="json")
