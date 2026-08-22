"""Contract tests for AI worker health, settings, and DTO schemas."""

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


def test_default_contract_worker_reports_offline_and_no_capabilities() -> None:
    """Default contract worker without backing models reports offline and no capabilities."""
    app = create_app()
    client = TestClient(app)

    response = client.get("/internal/v1/health", headers=AUTH_HEADER)
    assert response.status_code == 200
    payload = response.json()

    health = WorkerHealth.model_validate(payload)
    assert health.status == "offline"
    assert health.worker_version == "0.4.0"
    assert health.capabilities.parse is False
    assert health.capabilities.embed is False
    assert health.capabilities.rerank is False
    assert health.capabilities.llm is False
    assert health.models == {}


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
    assert health.capabilities.parse is False
    assert health.capabilities.embed is False
    assert health.capabilities.rerank is False
    assert health.capabilities.llm is False
    assert health.models == {}


def test_health_contract_degraded() -> None:
    settings = WorkerSettings(
        status="degraded",
        capability_parse=True,
        capability_embed=True,
        capability_rerank=False,
        capability_llm=False,
        model_embedding="bge-m3",
        model_ocr="pp-structure-v3",
    )
    app = create_app(settings)
    client = TestClient(app)

    response = client.get("/internal/v1/health", headers=AUTH_HEADER)
    assert response.status_code == 200
    health = WorkerHealth.model_validate(response.json())
    assert health.status == "degraded"
    assert health.capabilities.parse is True
    assert health.capabilities.embed is True
    assert health.capabilities.rerank is False
    assert health.capabilities.llm is False
    assert health.models == {
        "embedding": "bge-m3",
        "ocr": "pp-structure-v3",
    }


def test_worker_settings_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError):
        WorkerSettings(unknown_setting_key="disallowed")


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

    with pytest.raises(ValidationError):
        ChatMessage.model_validate({"role": "user", "content": "hello", "extra_key": "bad"})

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

    with pytest.raises(ValidationError):
        CompletionRequest.model_validate(
            {
                "messages": [{"role": "user", "content": "hi"}],
                "max_output_tokens": 256,
                "unknown_param": 42,
            }
        )

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

    with pytest.raises(ValidationError):
        CompletionResult.model_validate(
            {
                "text": "hi",
                "model": "m",
                "provider": "p",
                "finish_reason": "invalid_reason",
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            }
        )

    with pytest.raises(ValidationError):
        CompletionResult.model_validate(
            {
                "text": "hi",
                "model": "m",
                "provider": "p",
                "finish_reason": "stop",
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                "extra": "bad",
            }
        )

    with pytest.raises(ValidationError):
        TokenUsage.model_validate(
            {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2, "extra": "bad"}
        )


def test_rerank_contract_schemas() -> None:
    item = RerankItem(index=0, score=0.95, text="Đoạn văn 1")
    assert item.index == 0
    assert item.score == 0.95

    with pytest.raises(ValidationError):
        RerankItem.model_validate({"index": -1, "score": 0.95, "text": "Đoạn văn 1"})

    with pytest.raises(ValidationError):
        RerankItem.model_validate({"index": 0, "score": 0.95, "text": "t", "extra": "bad"})

    req = RerankRequest(
        query="Nhiệm vụ chủ trì",
        documents=["Đoạn văn 1", "Đoạn văn 2"],
        top_k=5,
        model="bge-reranker-large",
    )
    assert req.query == "Nhiệm vụ chủ trì"
    assert len(req.documents) == 2
    assert req.top_k == 5

    with pytest.raises(ValidationError):
        RerankRequest.model_validate(
            {
                "query": "q",
                "documents": ["d1"],
                "top_k": 1,
                "model": "m",
                "extra": "bad",
            }
        )

    res = RerankResult(
        results=[item],
        model="bge-reranker-large",
        reranker_version="v1",
    )
    assert len(res.results) == 1
    assert res.results[0].score == 0.95

    with pytest.raises(ValidationError):
        RerankResult.model_validate(
            {
                "results": [{"index": 0, "score": 0.95, "text": "t"}],
                "model": "m",
                "reranker_version": "v1",
                "extra": "bad",
            }
        )
