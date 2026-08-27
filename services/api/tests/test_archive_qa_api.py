"""Contract tests for the archive-wide Q&A endpoint."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app
from app.models import Document, DocumentChunk, DocumentRelation, ParseRun
from app.routers.archive import get_archive_qa_service
from app.settings import Settings
from mamagift_rag.archive_service import ArchiveQaService
from mamagift_retrieval.archive.sql_archive_index import SqlArchiveIndex
from mamagift_retrieval.providers import FakeChatProvider, FakeEmbeddingProvider
from mamagift_retrieval.rerank import FakeReranker

NOW = datetime(2026, 8, 27, 12, 0, 0, tzinfo=UTC)
DIM = 1024


def _vec(seed: float) -> list[float]:
    return [seed] + [0.0] * (DIM - 1)


def _seed_document(
    session: Session,
    doc_id: str,
    *,
    number: str,
    text: str,
    issued: date,
    document_type: str = "Công văn",
    issuer: str = "UBND Tỉnh",
    is_current: bool = True,
    version: int = 1,
    seed: float = 1.0,
) -> None:
    run_id = f"run_{doc_id}_v{version}"
    existing = session.get(Document, doc_id)
    if existing is None:
        session.add(
            Document(
                id=doc_id,
                filename=f"{doc_id}.pdf",
                content_type="application/pdf",
                byte_size=10,
                checksum_sha256=f"{doc_id:a<64}"[:64],
                storage_uri=f"local://{doc_id}.bin",
                status="READY",
                document_type=document_type,
                document_number=number,
                title=f"Tiêu đề {doc_id}",
                issuer=issuer,
                issued_date=issued,
                current_parse_run_id=run_id if is_current else None,
            )
        )
    elif is_current:
        existing.current_parse_run_id = run_id

    session.add(
        ParseRun(
            id=run_id,
            document_id=doc_id,
            version=version,
            is_current=is_current,
            parser_name="baseline",
            parser_version="1",
            configuration_hash="c" * 64,
            strategy_decided=False,
            degraded=False,
            route="baseline",
            schema_version="1",
            canonical={"document_id": doc_id, "extracted_fields": []},
            inspection={},
            quality_report={},
            started_at=NOW,
            finished_at=NOW,
        )
    )
    session.add(
        DocumentChunk(
            id=f"{doc_id}:v{version}:c0",
            document_id=doc_id,
            parse_run_id=run_id,
            document_version=version,
            chunk_index=0,
            section_path=["Điều 1"],
            page_numbers=[2],
            source_block_ids=[f"b_{doc_id}_1"],
            text=text,
            token_count=len(text.split()),
            embedding=_vec(seed),
            embedding_model="bge-m3",
            embedding_version="bge-m3-v1",
            created_at=NOW,
        )
    )
    session.commit()


def _archive_service(
    session: Session, settings: Settings, response: str | Exception
) -> ArchiveQaService:
    embedding = FakeEmbeddingProvider(
        model_id=settings.embedding_model,
        embedding_version=f"{settings.embedding_model}-v1",
        dimension=DIM,
    )
    return ArchiveQaService(
        chat_provider=FakeChatProvider(responses=[response]),
        embedding_provider=embedding,
        archive_index=SqlArchiveIndex(
            session, default_embedding_version=embedding.embedding_version
        ),
        reranker=FakeReranker(cross_document=True),
    )


def _answer_json(citation_ids: list[str], *, status: str = "answered") -> str:
    return json.dumps(
        {
            "answer": "Theo các văn bản đã tải lên, đây là câu trả lời.",
            "status": status,
            "citations": [{"citation_id": cid} for cid in citation_ids],
        },
        ensure_ascii=False,
    )


def _override(service: ArchiveQaService) -> None:
    app.dependency_overrides[get_archive_qa_service] = lambda: service


def _two_documents(session: Session) -> None:
    _seed_document(
        session,
        "doc_tt",
        number="19/2026/TT-BGDĐT",
        text="Thông tư quy định về công tác tuyển sinh đầu cấp năm học 2026.",
        issued=date(2026, 3, 31),
        document_type="Thông tư",
        issuer="Bộ Giáo dục và Đào tạo",
        seed=1.0,
    )
    _seed_document(
        session,
        "doc_qd",
        number="57/QĐ-UBND",
        text="Quyết định ban hành kế hoạch tuyển sinh của tỉnh.",
        issued=date(2026, 1, 15),
        document_type="Quyết định",
        seed=0.9,
    )


def test_archive_qa_answers_across_documents_with_grouped_citations(
    client: TestClient, session: Session, settings: Settings
) -> None:
    _two_documents(session)
    _override(_archive_service(session, settings, _answer_json(["c1", "c2"])))
    try:
        response = client.post("/api/v1/archive/qa", json={"question": "tuyển sinh"})
    finally:
        app.dependency_overrides.pop(get_archive_qa_service, None)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "answered"
    assert len(body["document_groups"]) >= 2

    grouped = [cid for group in body["document_groups"] for cid in group["citation_ids"]]
    assert sorted(grouped) == sorted(c["citation_id"] for c in body["citations"])
    assert len(grouped) == len(set(grouped))
    for group in body["document_groups"]:
        assert group["document_number"] in {"19/2026/TT-BGDĐT", "57/QĐ-UBND"}
        assert group["document_version"] == 1
        for citation_id in group["citation_ids"]:
            citation = next(c for c in body["citations"] if c["citation_id"] == citation_id)
            assert citation["document_id"] == group["document_id"]
            assert citation["page_number"] == 2


def test_archive_qa_never_returns_a_stale_parse_version(
    client: TestClient, session: Session, settings: Settings
) -> None:
    """v1 chunks exist and are indexed, but only the current v2 may be cited."""
    _seed_document(
        session,
        "doc_v",
        number="12/KH-UBND",
        text="Phiên bản cũ nói về tuyển sinh theo quy định trước đây.",
        issued=date(2026, 1, 1),
        version=1,
        is_current=False,
        seed=0.5,
    )
    _seed_document(
        session,
        "doc_v",
        number="12/KH-UBND",
        text="Phiên bản hiện hành nói về tuyển sinh theo quy định mới.",
        issued=date(2026, 1, 1),
        version=2,
        is_current=True,
        seed=0.6,
    )
    _override(_archive_service(session, settings, _answer_json(["c1"])))
    try:
        response = client.post("/api/v1/archive/qa", json={"question": "tuyển sinh"})
    finally:
        app.dependency_overrides.pop(get_archive_qa_service, None)

    assert response.status_code == 200
    body = response.json()
    assert body["document_groups"], "the current version should still be retrievable"
    for group in body["document_groups"]:
        assert group["document_version"] == 2
        assert group["parse_run_id"] == "run_doc_v_v2"


def test_archive_qa_metadata_filter_leaks_no_outside_document(
    client: TestClient, session: Session, settings: Settings
) -> None:
    _two_documents(session)
    _override(_archive_service(session, settings, _answer_json(["c1"])))
    try:
        response = client.post(
            "/api/v1/archive/qa",
            json={"question": "tuyển sinh", "filters": {"document_types": ["Thông tư"]}},
        )
    finally:
        app.dependency_overrides.pop(get_archive_qa_service, None)

    assert response.status_code == 200
    body = response.json()
    assert {group["document_id"] for group in body["document_groups"]} == {"doc_tt"}
    assert all(c["document_id"] == "doc_tt" for c in body["citations"])


def test_archive_qa_empty_filter_list_matches_nothing(
    client: TestClient, session: Session, settings: Settings
) -> None:
    """An empty list must never be widened into 'match everything'."""
    _two_documents(session)
    _override(_archive_service(session, settings, _answer_json(["c1"])))
    try:
        response = client.post(
            "/api/v1/archive/qa",
            json={"question": "tuyển sinh", "filters": {"document_types": []}},
        )
    finally:
        app.dependency_overrides.pop(get_archive_qa_service, None)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "archive_not_indexed"


def test_archive_qa_returns_409_when_nothing_is_indexed(
    client: TestClient, settings: Settings
) -> None:
    response = client.post("/api/v1/archive/qa", json={"question": "tuyển sinh"})
    assert response.status_code == 409
    body = response.json()["error"]
    assert body["code"] == "archive_not_indexed"
    assert body["retryable"] is True


def test_archive_qa_surfaces_an_evidence_backed_relation_with_citations(
    client: TestClient, session: Session, settings: Settings
) -> None:
    _two_documents(session)
    session.add(
        DocumentRelation(
            id="rel_1",
            source_document_id="doc_tt",
            source_parse_run_id="run_doc_tt_v1",
            source_document_version=1,
            source_block_ids=["b_doc_tt_1"],
            page_numbers=[2],
            relation_type="replaces",
            target_document_id="doc_qd",
            target_document_number="57/QĐ-UBND",
            target_raw_text="thay thế Quyết định 57/QĐ-UBND",
            confidence=0.9,
            review_state="unverified",
        )
    )
    session.commit()

    _override(_archive_service(session, settings, _answer_json(["c1", "c2"])))
    try:
        response = client.post("/api/v1/archive/qa", json={"question": "tuyển sinh"})
    finally:
        app.dependency_overrides.pop(get_archive_qa_service, None)

    body = response.json()
    assert len(body["relations"]) == 1
    relation = body["relations"][0]
    assert relation["relation_type"] == "replaces"
    assert relation["review_state"] == "unverified"
    assert relation["target_document_number"] == "57/QĐ-UBND"
    assert relation["citation_ids"], "a surfaced relation must point at real citations"
    assert set(relation["citation_ids"]) <= {c["citation_id"] for c in body["citations"]}


def test_archive_qa_does_not_invent_a_relation(
    client: TestClient, session: Session, settings: Settings
) -> None:
    """Two documents on the same topic with no relation row must yield no relation."""
    _two_documents(session)
    _override(_archive_service(session, settings, _answer_json(["c1", "c2"])))
    try:
        response = client.post(
            "/api/v1/archive/qa",
            json={"question": "Văn bản mới nhất về tuyển sinh là văn bản nào?"},
        )
    finally:
        app.dependency_overrides.pop(get_archive_qa_service, None)

    body = response.json()
    assert body["relations"] == []
    assert body["freshness_caveat"] is not None
    assert "thay thế" in body["freshness_caveat"]


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"question": ""},
        {"question": "   "},
        {"question": "hợp lệ", "unknown_field": 1},
        {"question": "hợp lệ", "filters": {"unknown": 1}},
        {
            "question": "hợp lệ",
            "filters": {"issued_date_from": "2026-05-01", "issued_date_to": "2026-01-01"},
        },
    ],
)
def test_archive_qa_rejects_malformed_requests(
    client: TestClient, session: Session, payload: dict[str, object]
) -> None:
    _two_documents(session)
    response = client.post("/api/v1/archive/qa", json=payload)
    assert response.status_code == 422


def test_archive_qa_request_cannot_forge_the_evidence_scope(
    client: TestClient, session: Session
) -> None:
    """The scope is built server-side; a client may not pin, widen or supply one."""
    _two_documents(session)
    response = client.post(
        "/api/v1/archive/qa",
        json={"question": "tuyển sinh", "scope": {"document_id": "doc_tt"}},
    )
    assert response.status_code == 422
