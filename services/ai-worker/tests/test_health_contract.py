"""Contract tests for AI worker health, DTO schemas, and OpenAI response adapter."""

from __future__ import annotations

import importlib
import importlib.util
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from mamagift_contracts.embedding import EmbeddingResult
from mamagift_contracts.llm import (
    ChatMessage,
    CompletionRequest,
    CompletionResult,
    TokenUsage,
)
from mamagift_contracts.rerank import (
    RerankItem,
    RerankRequest,
    RerankResult,
)
from mamagift_contracts.worker import (
    WorkerHealth,
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

_settings_mod = importlib.import_module("ai_worker_app.settings")
_main_mod = importlib.import_module("ai_worker_app.main")

WorkerSettings: Any = _settings_mod.WorkerSettings
create_app: Callable[..., FastAPI] = _main_mod.create_app

AUTH_HEADER = {"Authorization": "Bearer local-fake-worker-token"}


def test_health_contract_online() -> None:
    settings = WorkerSettings(
        worker_version="0.4.0",
        status="online",
        capability_parse=True,
        capability_embed=True,
        capability_rerank=False,
        capability_llm=True,
        model_llm="qwen2.5-7b-instruct",
        model_embedding="bge-m3",
        model_ocr="pp-structure-v3",
    )
    app = create_app(settings)
    client = TestClient(app)

    response = client.get("/internal/v1/health", headers=AUTH_HEADER)
    assert response.status_code == 200
    payload = response.json()

    # Validate against frozen contract
    health = WorkerHealth.model_validate(payload)
    assert health.status == "online"
    assert health.worker_version == "0.4.0"
    assert health.capabilities.parse is True
    assert health.capabilities.embed is True
    assert health.capabilities.rerank is False
    assert health.capabilities.llm is True
    assert health.models == {
        "llm": "qwen2.5-7b-instruct",
        "embedding": "bge-m3",
        "ocr": "pp-structure-v3",
    }


def test_health_contract_offline() -> None:
    settings = WorkerSettings(status="offline")
    app = create_app(settings)
    client = TestClient(app)

    response = client.get("/internal/v1/health", headers=AUTH_HEADER)
    assert response.status_code == 200
    health = WorkerHealth.model_validate(response.json())
    assert health.status == "offline"


def test_health_contract_degraded() -> None:
    settings = WorkerSettings(status="degraded")
    app = create_app(settings)
    client = TestClient(app)

    response = client.get("/internal/v1/health", headers=AUTH_HEADER)
    assert response.status_code == 200
    health = WorkerHealth.model_validate(response.json())
    assert health.status == "degraded"


def test_health_contract_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError):
        WorkerHealth.model_validate(
            {
                "status": "online",
                "worker_version": "0.4.0",
                "capabilities": {
                    "parse": True,
                    "embed": True,
                    "rerank": False,
                    "llm": True,
                    "extra_cap": True,
                },
                "models": {},
            }
        )

    with pytest.raises(ValidationError):
        WorkerHealth.model_validate(
            {
                "status": "online",
                "worker_version": "0.4.0",
                "capabilities": {
                    "parse": True,
                    "embed": True,
                    "rerank": False,
                    "llm": True,
                },
                "models": {},
                "unexpected_field": "disallowed",
            }
        )


def test_embedding_result_contract_and_docstring() -> None:
    doc = EmbeddingResult.__doc__ or ""
    assert "embedding_version" in doc
    assert "reindex" in doc

    result = EmbeddingResult(
        vectors=[[0.1, 0.2, 0.3]],
        model="bge-m3",
        dimension=3,
        embedding_version="bge-m3-v1",
    )
    assert result.vectors == [[0.1, 0.2, 0.3]]
    assert result.model == "bge-m3"
    assert result.dimension == 3
    assert result.embedding_version == "bge-m3-v1"

    with pytest.raises(ValidationError):
        EmbeddingResult.model_validate(
            {
                "vectors": [[0.1]],
                "model": "bge-m3",
                "dimension": 1,
                "embedding_version": "v1",
                "unknown": 123,
            }
        )


def test_llm_contract_schemas() -> None:
    msg = ChatMessage(role="user", content="Tóm tắt tài liệu")
    assert msg.role == "user"
    assert msg.content == "Tóm tắt tài liệu"

    with pytest.raises(ValidationError):
        ChatMessage.model_validate({"role": "invalid_role", "content": "hello"})

    req = CompletionRequest(
        messages=[msg],
        max_output_tokens=256,
        temperature=0.7,
        stop=["\n\n"],
        response_format="json_object",
    )
    assert req.max_output_tokens == 256
    assert req.temperature == 0.7
    assert req.stop == ["\n\n"]
    assert req.response_format == "json_object"

    res = CompletionResult(
        text="Kết quả",
        model="qwen2.5-7b-instruct",
        provider="local-openai-compatible",
        finish_reason="stop",
        usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
    )
    assert res.text == "Kết quả"
    assert res.finish_reason == "stop"
    assert res.usage.prompt_tokens == 10
    assert res.usage.completion_tokens == 5
    assert res.usage.total_tokens == 15


def test_rerank_contract_schemas() -> None:
    item = RerankItem(index=0, score=0.95, text="Đoạn văn 1")
    assert item.index == 0
    assert item.score == 0.95

    req = RerankRequest(
        query="Nhiệm vụ chủ trì",
        documents=["Đoạn văn 1", "Đoạn văn 2"],
        top_k=5,
        model="bge-reranker-large",
    )
    assert req.query == "Nhiệm vụ chủ trì"
    assert len(req.documents) == 2
    assert req.top_k == 5

    res = RerankResult(
        results=[item],
        model="bge-reranker-large",
        reranker_version="v1",
    )
    assert len(res.results) == 1
    assert res.results[0].score == 0.95


def adapt_openai_chat_response(
    raw: dict[str, Any], provider: str = "local-openai-compatible"
) -> CompletionResult:
    """Helper adapter converting OpenAI chat completion JSON payload to CompletionResult."""
    choice = raw["choices"][0]
    message_content = choice["message"]["content"]
    finish_reason = choice.get("finish_reason", "stop")
    model = raw.get("model", "unknown")
    raw_usage = raw.get("usage", {})
    usage = TokenUsage(
        prompt_tokens=raw_usage.get("prompt_tokens", 0),
        completion_tokens=raw_usage.get("completion_tokens", 0),
        total_tokens=raw_usage.get("total_tokens", 0),
    )
    return CompletionResult(
        text=message_content,
        model=model,
        provider=provider,
        finish_reason=finish_reason,
        usage=usage,
    )


def test_openai_compatible_response_adapter_shape() -> None:
    raw_openai_payload = {
        "id": "chatcmpl-abc123xyz",
        "object": "chat.completion",
        "created": 1724284800,
        "model": "qwen2.5-7b-instruct",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "Căn cứ Quyết định số 12/QĐ-UBND...",
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 142,
            "completion_tokens": 58,
            "total_tokens": 200,
        },
    }

    adapted = adapt_openai_chat_response(raw_openai_payload)
    assert adapted.text == "Căn cứ Quyết định số 12/QĐ-UBND..."
    assert adapted.model == "qwen2.5-7b-instruct"
    assert adapted.provider == "local-openai-compatible"
    assert adapted.finish_reason == "stop"
    assert adapted.usage.prompt_tokens == 142
    assert adapted.usage.completion_tokens == 58
    assert adapted.usage.total_tokens == 200


def test_retry_safe_idempotent_request() -> None:
    app = create_app()
    client = TestClient(app)

    request_id = "req_custom_idempotent_12345"
    headers = {**AUTH_HEADER, "x-request-id": request_id}

    response_1 = client.get("/internal/v1/health", headers=headers)
    assert response_1.status_code == 200

    response_2 = client.get("/internal/v1/health", headers=headers)
    assert response_2.status_code == 200

    assert response_1.json() == response_2.json()
