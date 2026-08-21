"""Bearer-token authentication for the internal AI worker."""

from __future__ import annotations

import hmac
from typing import Annotated

from fastapi import Depends, Header

from mamagift_contracts.errors import WorkerError, WorkerErrorCode

from .settings import WorkerSettings, get_worker_settings


async def verify_bearer_token(
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    settings: Annotated[WorkerSettings, Depends(get_worker_settings)] = None,  # type: ignore[assignment]
) -> str:
    """Validate bearer token from the Authorization header.

    Rejects missing, malformed, or invalid tokens with structured WorkerError (HTTP 401).
    """
    if authorization is None or not authorization.strip():
        raise WorkerError(
            code=WorkerErrorCode.UNAUTHORIZED,
            message="Missing Authorization header",
            status_code=401,
            retryable=False,
        )

    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise WorkerError(
            code=WorkerErrorCode.UNAUTHORIZED,
            message="Malformed Authorization header; expected 'Bearer <token>'",
            status_code=401,
            retryable=False,
        )

    token = parts[1].strip()
    if not token:
        raise WorkerError(
            code=WorkerErrorCode.UNAUTHORIZED,
            message="Empty bearer token",
            status_code=401,
            retryable=False,
        )

    if not hmac.compare_digest(token.encode("utf-8"), settings.auth_token.encode("utf-8")):
        raise WorkerError(
            code=WorkerErrorCode.UNAUTHORIZED,
            message="Invalid authentication token",
            status_code=401,
            retryable=False,
        )

    return token
