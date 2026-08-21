"""Tests for AI worker authentication, error schema, timeout, and stack trace suppression."""

from __future__ import annotations

import asyncio
import importlib
import importlib.util
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any

import pytest
from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient

from mamagift_contracts.errors import (
    WorkerError,
    WorkerErrorCode,
    WorkerErrorResponse,
)

# Dynamically load ai-worker's modules so they do not collide with services/api's app package
_worker_root = Path(__file__).resolve().parent.parent
_app_dir = _worker_root / "app"
if "ai_worker_app" not in sys.modules:
    _pkg_spec = importlib.util.spec_from_file_location("ai_worker_app", _app_dir / "__init__.py")
    assert _pkg_spec and _pkg_spec.loader
    _pkg_mod = importlib.util.module_from_spec(_pkg_spec)
    sys.modules["ai_worker_app"] = _pkg_mod
    _pkg_mod.__path__ = [str(_app_dir)]
    _pkg_spec.loader.exec_module(_pkg_mod)

_auth_mod = importlib.import_module("ai_worker_app.auth")
_settings_mod = importlib.import_module("ai_worker_app.settings")
_main_mod = importlib.import_module("ai_worker_app.main")

WorkerSettings: Any = _settings_mod.WorkerSettings
create_app: Callable[..., FastAPI] = _main_mod.create_app
verify_bearer_token: Any = _auth_mod.verify_bearer_token


def test_missing_auth_header_rejected() -> None:
    app = create_app()
    client = TestClient(app)

    response = client.get("/internal/v1/health")
    assert response.status_code == 401

    payload = response.json()
    err_resp = WorkerErrorResponse.model_validate(payload)
    assert err_resp.error.code == WorkerErrorCode.UNAUTHORIZED.value
    assert err_resp.error.retryable is False
    assert "Missing Authorization header" in err_resp.error.message
    assert err_resp.error.request_id.startswith("req_")


def test_wrong_token_rejected() -> None:
    app = create_app()
    client = TestClient(app)

    response = client.get(
        "/internal/v1/health",
        headers={"Authorization": "Bearer completely-wrong-token"},
    )
    assert response.status_code == 401

    payload = response.json()
    err_resp = WorkerErrorResponse.model_validate(payload)
    assert err_resp.error.code == WorkerErrorCode.UNAUTHORIZED.value
    assert err_resp.error.retryable is False
    assert "Invalid authentication token" in err_resp.error.message


@pytest.mark.parametrize(
    "malformed_header",
    [
        "Basic dXNlcjpwYXNz",
        "Bearer",
        "Bearer   ",
        "Bearer token extra_part",
        "Token xyz",
        "bearer",
    ],
)
def test_malformed_auth_headers_rejected(malformed_header: str) -> None:
    app = create_app()
    client = TestClient(app)

    response = client.get(
        "/internal/v1/health",
        headers={"Authorization": malformed_header},
    )
    assert response.status_code == 401

    payload = response.json()
    err_resp = WorkerErrorResponse.model_validate(payload)
    assert err_resp.error.code == WorkerErrorCode.UNAUTHORIZED.value
    assert err_resp.error.retryable is False


def test_valid_token_accepted() -> None:
    app = create_app()
    client = TestClient(app)

    response = client.get(
        "/internal/v1/health",
        headers={"Authorization": "Bearer local-fake-worker-token"},
    )
    assert response.status_code == 200


def test_timeout_handling() -> None:
    settings = WorkerSettings(timeout_seconds=0.05)
    app = create_app(settings)

    test_router = APIRouter(prefix="/internal/v1")

    @test_router.get("/slow-operation")
    async def slow_op(_auth: Annotated[str, Depends(verify_bearer_token)]) -> dict[str, str]:
        await asyncio.sleep(0.2)
        return {"status": "completed"}

    app.include_router(test_router)
    client = TestClient(app)

    response = client.get(
        "/internal/v1/slow-operation",
        headers={"Authorization": "Bearer local-fake-worker-token"},
    )
    assert response.status_code == 504
    payload = response.json()
    err_resp = WorkerErrorResponse.model_validate(payload)
    assert err_resp.error.code == WorkerErrorCode.TIMEOUT.value
    assert err_resp.error.retryable is True
    assert "timed out" in err_resp.error.message.lower()


def test_structured_error_does_not_leak_stack_trace() -> None:
    app = create_app()

    test_router = APIRouter(prefix="/internal/v1")

    @test_router.get("/fail-operation")
    async def fail_op(_auth: Annotated[str, Depends(verify_bearer_token)]) -> dict[str, str]:
        raise RuntimeError("Secret leaked: /root/.ssh/id_rsa should never be visible")

    app.include_router(test_router)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.get(
        "/internal/v1/fail-operation",
        headers={"Authorization": "Bearer local-fake-worker-token"},
    )
    assert response.status_code == 500
    payload = response.json()
    err_resp = WorkerErrorResponse.model_validate(payload)
    assert err_resp.error.code == "internal_error"
    assert err_resp.error.retryable is False
    assert "Traceback" not in response.text
    assert "/root/.ssh/id_rsa" not in response.text


def test_worker_error_defaults_and_status_codes() -> None:
    err_unauth = WorkerError(WorkerErrorCode.UNAUTHORIZED)
    assert err_unauth.status_code == 401
    assert err_unauth.retryable is False

    err_timeout = WorkerError(WorkerErrorCode.TIMEOUT)
    assert err_timeout.status_code == 504
    assert err_timeout.retryable is True

    err_unavail = WorkerError(WorkerErrorCode.UNAVAILABLE)
    assert err_unavail.status_code == 503
    assert err_unavail.retryable is True

    err_model = WorkerError(WorkerErrorCode.MODEL_NOT_LOADED)
    assert err_model.status_code == 503
    assert err_model.retryable is True

    err_bad_req = WorkerError(WorkerErrorCode.BAD_REQUEST)
    assert err_bad_req.status_code == 400
    assert err_bad_req.retryable is False

    err_upstream = WorkerError(WorkerErrorCode.UPSTREAM_ERROR)
    assert err_upstream.status_code == 502
    assert err_upstream.retryable is True
