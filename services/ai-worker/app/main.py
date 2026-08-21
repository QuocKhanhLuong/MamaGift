"""FastAPI application for the MamaGift AI Worker service."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from mamagift_contracts.errors import (
    WorkerError,
    WorkerErrorBody,
    WorkerErrorCode,
    WorkerErrorResponse,
)

from .health import router as health_router
from .settings import WorkerSettings, get_worker_settings


def create_app(settings: WorkerSettings | None = None) -> FastAPI:
    worker_settings = settings or get_worker_settings()

    app = FastAPI(
        title="MamaGift AI Worker",
        version=worker_settings.worker_version,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    if settings is not None:
        app.dependency_overrides[get_worker_settings] = lambda: worker_settings

    @app.middleware("http")
    async def timeout_and_request_id_middleware(
        request: Request,
        call_next: Any,
    ) -> Any:
        request_id = request.headers.get("x-request-id") or f"req_{uuid.uuid4().hex[:16]}"
        request.state.request_id = request_id

        timeout = worker_settings.timeout_seconds
        try:
            return await asyncio.wait_for(call_next(request), timeout=timeout)
        except TimeoutError:
            err_resp = WorkerErrorResponse(
                error=WorkerErrorBody(
                    code=WorkerErrorCode.TIMEOUT.value,
                    message=f"Request timed out after {timeout} seconds",
                    retryable=True,
                    request_id=request_id,
                    details={"timeout_seconds": timeout},
                )
            )
            return JSONResponse(
                status_code=504,
                content=err_resp.model_dump(mode="json"),
            )

    @app.exception_handler(WorkerError)
    async def worker_error_handler(request: Request, exc: WorkerError) -> JSONResponse:
        request_id = (
            getattr(request.state, "request_id", None)
            or request.headers.get("x-request-id")
            or f"req_{uuid.uuid4().hex[:16]}"
        )
        err_resp = WorkerErrorResponse(
            error=WorkerErrorBody(
                code=exc.code.value,
                message=exc.message,
                retryable=exc.retryable,
                request_id=request_id,
                details=exc.details,
            )
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=err_resp.model_dump(mode="json"),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        request_id = (
            getattr(request.state, "request_id", None)
            or request.headers.get("x-request-id")
            or f"req_{uuid.uuid4().hex[:16]}"
        )
        err_resp = WorkerErrorResponse(
            error=WorkerErrorBody(
                code=WorkerErrorCode.BAD_REQUEST.value,
                message="Invalid request payload or parameters",
                retryable=False,
                request_id=request_id,
                details={"errors": exc.errors()},
            )
        )
        return JSONResponse(
            status_code=400,
            content=err_resp.model_dump(mode="json"),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        request_id = (
            getattr(request.state, "request_id", None)
            or request.headers.get("x-request-id")
            or f"req_{uuid.uuid4().hex[:16]}"
        )
        code = (
            WorkerErrorCode.UNAUTHORIZED if exc.status_code == 401 else WorkerErrorCode.BAD_REQUEST
        )
        err_resp = WorkerErrorResponse(
            error=WorkerErrorBody(
                code=code.value,
                message=str(exc.detail),
                retryable=False,
                request_id=request_id,
                details={},
            )
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=err_resp.model_dump(mode="json"),
        )

    @app.exception_handler(Exception)
    async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        request_id = (
            getattr(request.state, "request_id", None)
            or request.headers.get("x-request-id")
            or f"req_{uuid.uuid4().hex[:16]}"
        )
        err_resp = WorkerErrorResponse(
            error=WorkerErrorBody(
                code="internal_error",
                message="An internal worker error occurred",
                retryable=False,
                request_id=request_id,
                details={},
            )
        )
        return JSONResponse(
            status_code=500,
            content=err_resp.model_dump(mode="json"),
        )

    app.include_router(health_router)
    return app


app = create_app()
