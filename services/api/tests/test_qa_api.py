"""Contract tests for the single-document Q&A endpoint."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app
from app.models import Document, DocumentChunk, ParseRun
from app.routers.qa import get_document_index, get_qa_service
from app.settings import Settings
from mamagift_contracts.errors import WorkerError, WorkerErrorCode
from mamagift_rag import ModelRef, QaAnswer, QaService, RetrievalRef
from mamagift_retrieval.index import IndexStats, SqlDocumentIndex
from mamagift_retrieval.providers import FakeChatProvider, FakeEmbeddingProvider
from mamagift_retrieval.rerank import FakeReranker
from mamagift_retrieval.scope import EvidenceScope


def _create_current_document(session: Session, *, indexed: bool = True) -> Document:
    now = datetime.now(UTC)
    document = Document(
        id="doc_qa",
        filename="qa.pdf",
        content_type="application/pdf",
        byte_size=10,
        checksum_sha256="a" * 64,
        storage_uri="local://aa/qa.bin",
        status="READY",
        current_parse_run_id="run_qa",
    )
    parse_run = ParseRun(
        id="run_qa",
        document_id=document.id,
        version=1,
        is_current=True,
        parser_name="baseline",
        parser_version="1",
        configuration_hash="b" * 64,
        strategy_decided=False,
        degraded=False,
        route="baseline",
        schema_version="1",
        canonical={"document_id": document.id, "extracted_fields": []},
        inspection={},
        quality_report={},
        started_at=now,
        finished_at=now,
    )
    session.add_all([document, parse_run])
    if indexed:
        session.add(
            DocumentChunk(
                id="chunk_qa",
                document_id=document.id,
                parse_run_id=parse_run.id,
                document_version=parse_run.version,
                chunk_index=0,
                parent_chunk_id=None,
                section_path=["Điều 1"],
                page_numbers=[2],
                source_block_ids=["b_2_0005", "b_2_0006"],
                text="Văn bản yêu cầu trường giải quyết hồ sơ trong thời hạn quy định.",
                token_count=12,
                embedding=[1.0] + [0.0] * 1023,
                embedding_model="bge-m3",
                embedding_version="bge-m3-v1",
                created_at=now,
            )
        )
    session.commit()
    return document


def _qa_service(session: Session, settings: Settings, response: str | Exception) -> QaService:
    embedding = FakeEmbeddingProvider(
        model_id=settings.embedding_model,
        embedding_version=f"{settings.embedding_model}-v1",
    )
    return QaService(
        chat_provider=FakeChatProvider(responses=[response]),
        embedding_provider=embedding,
        document_index=SqlDocumentIndex(
            session, default_embedding_version=embedding.embedding_version
        ),
        reranker=FakeReranker(ordering=["chunk_qa"]),
    )


def _answered_json() -> str:
    return json.dumps(
        {
            "answer": "Nhà trường phải giải quyết hồ sơ trong thời hạn quy định.",
            "status": "answered",
            "citations": [
                {
                    "citation_id": "c1",
                    "document_id": "doc_qa",
                    "page_number": 2,
                    "block_ids": ["b_2_0005", "b_2_0006"],
                    "quote": "Văn bản yêu cầu trường giải quyết hồ sơ trong thời hạn quy định.",
                }
            ],
        },
        ensure_ascii=False,
    )


def _override_service(service: QaService) -> None:
    app.dependency_overrides[get_qa_service] = lambda: service


class _StubQaService:
    def __init__(self, result: QaAnswer | Exception) -> None:
        self.result = result

    async def answer(self, question: str, *, scope: EvidenceScope) -> QaAnswer:
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class _EmptyVersionedIndex:
    def stats(self, scope: EvidenceScope) -> IndexStats:
        return IndexStats(
            document_id=scope.document_id or "",
            parse_run_id=scope.parse_run_id or "",
            document_version=scope.document_version,
            total_chunks=0,
            embedded_chunks=0,
            embedding_version="bge-m3-v1",
        )


def test_answered_response_matches_documented_shape(
    client: TestClient, session: Session, settings: Settings
) -> None:
    _create_current_document(session)
    _override_service(_qa_service(session, settings, _answered_json()))
    try:
        response = client.post(
            "/api/v1/documents/doc_qa/qa", json={"question": "Trường phải làm gì?"}
        )
    finally:
        app.dependency_overrides.pop(get_qa_service, None)

    assert response.status_code == 200
    assert response.json() == {
        "answer": "Nhà trường phải giải quyết hồ sơ trong thời hạn quy định.",
        "status": "answered",
        "citations": [
            {
                "citation_id": "c1",
                "document_id": "doc_qa",
                "page_number": 2,
                "block_ids": ["b_2_0005", "b_2_0006"],
                "quote": "Văn bản yêu cầu trường giải quyết hồ sơ trong thời hạn quy định.",
            }
        ],
        "retrieval": {"query_id": response.json()["retrieval"]["query_id"]},
        "model": {"provider": "fake_chat", "model": "fake-qwen2.5-7b", "version": "unknown"},
    }
    assert response.json()["retrieval"]["query_id"].startswith("qry_")


def test_insufficient_evidence_is_http_200_with_empty_citations(
    client: TestClient, session: Session, settings: Settings
) -> None:
    _create_current_document(session)
    _override_service(_qa_service(session, settings, _answered_json()))
    try:
        # The API preserves the service's abstention status and does not turn it into an error.
        service = _qa_service(session, settings, _answered_json())
        original = service.answer

        async def abstain(question: str, *, scope):
            answer = await original(question, scope=scope)
            return answer.model_copy(
                update={
                    "answer": "Không đủ bằng chứng trong tài liệu để trả lời câu hỏi này.",
                    "status": "insufficient_evidence",
                    "citations": [],
                }
            )

        service.answer = abstain  # type: ignore[method-assign]
        _override_service(service)
        response = client.post("/api/v1/documents/doc_qa/qa", json={"question": "Câu hỏi?"})
    finally:
        app.dependency_overrides.pop(get_qa_service, None)

    assert response.status_code == 200
    assert response.json()["status"] == "insufficient_evidence"
    assert response.json()["citations"] == []


def test_worker_unavailable_is_structured_retryable_error(
    client: TestClient, session: Session, settings: Settings
) -> None:
    _create_current_document(session)
    _override_service(
        _qa_service(session, settings, WorkerError(WorkerErrorCode.UNAVAILABLE, "offline"))
    )
    try:
        response = client.post("/api/v1/documents/doc_qa/qa", json={"question": "Câu hỏi?"})
    finally:
        app.dependency_overrides.pop(get_qa_service, None)

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "ai_worker_unavailable"
    assert response.json()["error"]["retryable"] is True


def test_scope_rejection_is_structured_defence_in_depth_error(
    client: TestClient, session: Session, settings: Settings
) -> None:
    _create_current_document(session)
    _override_service(_StubQaService(ValueError("scope mismatch")))  # type: ignore[arg-type]
    try:
        response = client.post("/api/v1/documents/doc_qa/qa", json={"question": "Câu hỏi?"})
    finally:
        app.dependency_overrides.pop(get_qa_service, None)

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "qa_scope_violation"
    assert response.json()["error"]["retryable"] is False


def test_cross_document_citation_is_rejected(
    client: TestClient, session: Session, settings: Settings
) -> None:
    _create_current_document(session)
    answer = QaAnswer(
        answer="Không hợp lệ",
        status="answered",
        citations=[
            {
                "citation_id": "c1",
                "document_id": "doc_other",
                "page_number": 1,
                "block_ids": ["other"],
                "quote": "other",
            }
        ],
        retrieval=RetrievalRef(query_id="qry_test"),
        model=ModelRef(provider="fake", model="fake", version="v1"),
    )
    _override_service(_StubQaService(answer))  # type: ignore[arg-type]
    try:
        response = client.post("/api/v1/documents/doc_qa/qa", json={"question": "Câu hỏi?"})
    finally:
        app.dependency_overrides.pop(get_qa_service, None)

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "qa_scope_violation"


def test_not_indexed_document_is_structured_conflict(client: TestClient, session: Session) -> None:
    _create_current_document(session, indexed=False)
    response = client.post("/api/v1/documents/doc_qa/qa", json={"question": "Câu hỏi?"})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "document_not_indexed"
    assert response.json()["error"]["retryable"] is True


def test_zero_chunk_index_is_not_queryable_even_with_matching_version(
    client: TestClient, session: Session
) -> None:
    _create_current_document(session, indexed=False)
    app.dependency_overrides[get_document_index] = lambda: _EmptyVersionedIndex()
    try:
        response = client.post("/api/v1/documents/doc_qa/qa", json={"question": "Câu hỏi?"})
    finally:
        app.dependency_overrides.pop(get_document_index, None)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "document_not_indexed"


def test_document_without_current_parse_run_is_not_indexed(
    client: TestClient, session: Session
) -> None:
    _create_current_document(session)
    document = session.get(Document, "doc_qa")
    assert document is not None
    document.current_parse_run_id = None
    session.commit()

    response = client.post("/api/v1/documents/doc_qa/qa", json={"question": "Câu hỏi?"})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "document_not_indexed"


def test_missing_current_parse_run_pointer_is_scope_violation(
    client: TestClient, session: Session
) -> None:
    _create_current_document(session)
    document = session.get(Document, "doc_qa")
    assert document is not None
    document.current_parse_run_id = "run_missing"
    session.commit()

    response = client.post("/api/v1/documents/doc_qa/qa", json={"question": "Câu hỏi?"})

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "qa_scope_violation"


def test_incomplete_index_is_not_queryable(client: TestClient, session: Session) -> None:
    _create_current_document(session)
    chunk = session.get(DocumentChunk, "chunk_qa")
    assert chunk is not None
    chunk.embedding = None
    session.commit()

    response = client.post("/api/v1/documents/doc_qa/qa", json={"question": "Câu hỏi?"})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "document_not_indexed"


def test_stale_embedding_version_is_not_queryable(client: TestClient, session: Session) -> None:
    _create_current_document(session)
    chunk = session.get(DocumentChunk, "chunk_qa")
    assert chunk is not None
    chunk.embedding_version = "bge-m3-v0"
    session.commit()

    response = client.post("/api/v1/documents/doc_qa/qa", json={"question": "Câu hỏi?"})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "document_not_indexed"


def test_stale_current_parse_run_pointer_is_rejected(client: TestClient, session: Session) -> None:
    _create_current_document(session)
    parse_run = session.get(ParseRun, "run_qa")
    assert parse_run is not None
    parse_run.is_current = False
    session.commit()

    response = client.post("/api/v1/documents/doc_qa/qa", json={"question": "Câu hỏi?"})

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "qa_scope_violation"


def test_unknown_document_is_404(client: TestClient) -> None:
    response = client.post("/api/v1/documents/doc_missing/qa", json={"question": "Câu hỏi?"})

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


@pytest.mark.parametrize("body", [{}, {"question": ""}, {"question": "  \t"}])
def test_empty_or_missing_question_is_rejected(client: TestClient, body: dict[str, Any]) -> None:
    response = client.post("/api/v1/documents/doc_missing/qa", json=body)

    assert response.status_code == 422


def test_document_detail_and_canonical_responses_remain_unchanged(
    client: TestClient, session: Session
) -> None:
    _create_current_document(session, indexed=False)
    detail_before = client.get("/api/v1/documents/doc_qa").json()
    canonical_before = client.get("/api/v1/documents/doc_qa/canonical").json()

    qa_response = client.post("/api/v1/documents/doc_qa/qa", json={"question": "Câu hỏi?"})
    assert qa_response.status_code == 409

    assert client.get("/api/v1/documents/doc_qa").json() == detail_before
    assert client.get("/api/v1/documents/doc_qa/canonical").json() == canonical_before
