"""API-level acceptance tests for the real grounded QA pipeline.

The upload route, parser worker, runtime indexer, SQL index, retrieval/fusion,
reranker, evidence assembly and citation validator are real in these tests.  Only
the chat and embedding provider seams use deterministic fakes.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import cast

import pymupdf
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.main import app
from app.models import Document, DocumentChunk, ParseRun
from app.routers.qa import get_qa_service
from app.settings import Settings
from app.state_machine import DocumentStatus
from app.storage import LocalObjectStorage
from app.worker import process_next_job
from mamagift_contracts.errors import WorkerError, WorkerErrorCode
from mamagift_rag import QaService
from mamagift_retrieval.index import SqlDocumentIndex
from mamagift_retrieval.providers import FakeChatProvider, FakeEmbeddingProvider
from mamagift_retrieval.rerank import FakeReranker

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "qa" / "acceptance_cases.json"


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"fixture value is not an object: {value!r}")
    return value


def _fixture() -> Mapping[str, object]:
    return _mapping(json.loads(FIXTURE_PATH.read_text(encoding="utf-8")))


def _pdf_from_pages(pages: list[list[str]]) -> bytes:
    """Render authored Vietnamese lines into a born-digital synthetic PDF."""

    pdf = pymupdf.open()
    font = pymupdf.Font("notos")
    for lines in pages:
        page = pdf.new_page(width=595.0, height=842.0)
        page.insert_font(fontname="notos", fontbuffer=font.buffer)
        for index, line in enumerate(lines):
            page.insert_text(
                (72.0, 110.0 + index * 26.0),
                line,
                fontname="notos",
                fontsize=11.0,
            )
    return pdf.tobytes()


def _row_for_text(
    session: Session, document_id: str, parse_run_id: str, needle: str
) -> DocumentChunk:
    rows = list(
        session.scalars(
            select(DocumentChunk)
            .where(
                DocumentChunk.document_id == document_id,
                DocumentChunk.parse_run_id == parse_run_id,
            )
            .order_by(DocumentChunk.chunk_index)
        ).all()
    )
    row = next((candidate for candidate in rows if needle in candidate.text), None)
    assert row is not None, (
        f"no indexed chunk contains fixture text {needle!r}; "
        f"available={[candidate.text for candidate in rows]!r}"
    )
    return row


def _citation_payload(
    *,
    answer: str,
    document_id: str,
    row: DocumentChunk,
    status: str = "answered",
) -> str:
    return json.dumps(
        {
            "answer": answer,
            "status": status,
            "citations": [
                {
                    "citation_id": "c1",
                    "document_id": document_id,
                    "page_number": row.page_numbers[0],
                    "block_ids": list(row.source_block_ids),
                    "quote": row.text,
                }
            ],
        },
        ensure_ascii=False,
    )


def _abstention_payload() -> str:
    return json.dumps(
        {
            "answer": "Không đủ bằng chứng trong tài liệu để trả lời câu hỏi này.",
            "status": "insufficient_evidence",
            "citations": [],
        },
        ensure_ascii=False,
    )


def _upload_and_index(
    client: TestClient,
    upload: Callable[..., Response],
    session: Session,
    storage: LocalObjectStorage,
    settings: Settings,
    data: bytes,
    *,
    filename: str,
    target_text: str,
) -> tuple[str, ParseRun, DocumentChunk, SqlDocumentIndex, FakeEmbeddingProvider]:
    upload_response = upload(client, data, filename=filename)
    assert upload_response.status_code == 202
    document_id = cast(str, upload_response.json()["document"]["id"])

    embedding = FakeEmbeddingProvider(
        model_id=settings.embedding_model,
        embedding_version=f"{settings.embedding_model}-v1",
    )
    document_index = SqlDocumentIndex(
        session,
        default_embedding_version=embedding.embedding_version,
    )
    parse_run = process_next_job(
        session,
        storage,
        settings,
        "qa-integration-worker",
        auto_index=True,
        embedding_provider=embedding,
        document_index=document_index,
    )
    assert parse_run is not None
    assert parse_run.document_id == document_id
    document = session.get(Document, document_id)
    assert document is not None
    assert document.status == DocumentStatus.READY.value

    target = _row_for_text(session, document_id, parse_run.id, target_text)
    return document_id, parse_run, target, document_index, embedding


def _ask(
    client: TestClient,
    service: QaService,
    document_id: str,
    question: str,
) -> Response:
    app.dependency_overrides[get_qa_service] = lambda: service
    try:
        return client.post(
            f"/api/v1/documents/{document_id}/qa",
            json={"question": question},
        )
    finally:
        app.dependency_overrides.pop(get_qa_service, None)


def _service_for_target(
    target: DocumentChunk,
    document_index: SqlDocumentIndex,
    embedding: FakeEmbeddingProvider,
    chat: FakeChatProvider,
) -> QaService:
    service = QaService(
        chat_provider=chat,
        embedding_provider=embedding,
        document_index=document_index,
        reranker=FakeReranker(ordering=[target.id]),
    )
    return service


def test_case_1_exact_fact_runs_upload_to_cited_source_block(
    client: TestClient,
    upload: Callable[..., Response],
    session: Session,
    storage: LocalObjectStorage,
    settings: Settings,
) -> None:
    case = _mapping(_fixture()["decision"])
    source_pdf = REPO_ROOT / cast(str, case["source_pdf"])
    document_id, _, target, index, embedding = _upload_and_index(
        client,
        upload,
        session,
        storage,
        settings,
        source_pdf.read_bytes(),
        filename=cast(str, case["filename"]),
        target_text=cast(str, case["number_block_text"]),
    )
    chat = FakeChatProvider(
        responses=[
            _citation_payload(
                answer="Số văn bản là 57/QĐ-UBND.",
                document_id=document_id,
                row=target,
            )
        ]
    )
    response = _ask(
        client,
        _service_for_target(target, index, embedding, chat),
        document_id,
        "Số văn bản là bao nhiêu?",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "answered"
    assert body["answer"] == "Số văn bản là 57/QĐ-UBND."
    citation = body["citations"][0]
    assert citation["document_id"] == document_id
    assert citation["page_number"] == target.page_numbers[0] == case["number_page"]
    assert citation["block_ids"] == target.source_block_ids
    assert citation["quote"] == target.text
    assert "57/QĐ-UBND" in citation["quote"]
    assert chat.calls, "the real pipeline must reach the fake LLM"


def test_case_2_plan_answer_keeps_owner_and_deadline_task_local(
    client: TestClient,
    upload: Callable[..., Response],
    session: Session,
    storage: LocalObjectStorage,
    settings: Settings,
) -> None:
    case = _mapping(_fixture()["plan"])
    pages = cast(list[list[str]], case["pages"])
    document_id, _, target, index, embedding = _upload_and_index(
        client,
        upload,
        session,
        storage,
        settings,
        _pdf_from_pages(pages),
        filename=cast(str, case["filename"]),
        target_text=cast(str, case["evidence_text"]),
    )
    owner = cast(str, case["owner"])
    other_owner = cast(str, case["other_owner"])
    other_deadline = cast(str, case["other_deadline"])
    answer = f"Nhiệm vụ X do {owner} chủ trì và phải hoàn thành trước ngày 15 tháng 08 năm 2026."
    chat = FakeChatProvider(
        responses=[_citation_payload(answer=answer, document_id=document_id, row=target)]
    )
    response = _ask(
        client,
        _service_for_target(target, index, embedding, chat),
        document_id,
        cast(str, case["question"]),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "answered"
    assert body["answer"] == answer
    assert owner in body["answer"]
    deadline_text = cast(str, case["deadline_text"])
    other_deadline_text = cast(str, case["other_deadline_text"])
    assert deadline_text in body["answer"]
    # Explicit negative direction: Task X must not receive Task Y's owner/deadline.
    assert other_owner not in body["answer"]
    assert other_deadline not in body["answer"]
    assert other_deadline_text not in body["answer"]
    citation = body["citations"][0]
    assert citation["block_ids"] == target.source_block_ids
    assert citation["quote"] == target.text
    assert owner in citation["quote"]
    assert deadline_text in citation["quote"]


def test_case_3_hierarchy_question_cites_the_exact_legal_level(
    client: TestClient,
    upload: Callable[..., Response],
    session: Session,
    storage: LocalObjectStorage,
    settings: Settings,
) -> None:
    case = _mapping(_fixture()["decision"])
    source_pdf = REPO_ROOT / cast(str, case["source_pdf"])
    document_id, _, target, index, embedding = _upload_and_index(
        client,
        upload,
        session,
        storage,
        settings,
        source_pdf.read_bytes(),
        filename=cast(str, case["filename"]),
        target_text=cast(str, case["hierarchy_block_text"]),
    )
    assert any("Điều 3" in path for path in target.section_path)
    chat = FakeChatProvider(
        responses=[
            _citation_payload(
                answer="Điều 3 quy định hiệu lực thi hành.",
                document_id=document_id,
                row=target,
            )
        ]
    )
    response = _ask(
        client,
        _service_for_target(target, index, embedding, chat),
        document_id,
        cast(str, case["hierarchy_question"]),
    )

    assert response.status_code == 200
    citation = response.json()["citations"][0]
    assert citation["page_number"] == case["hierarchy_page"]
    assert citation["block_ids"] == target.source_block_ids
    assert "Hiệu lực thi hành" in citation["quote"]


def test_case_4_absent_fact_abstains_with_zero_citations(
    client: TestClient,
    upload: Callable[..., Response],
    session: Session,
    storage: LocalObjectStorage,
    settings: Settings,
) -> None:
    case = _mapping(_fixture()["decision"])
    source_pdf = REPO_ROOT / cast(str, case["source_pdf"])
    document_id, _, target, index, embedding = _upload_and_index(
        client,
        upload,
        session,
        storage,
        settings,
        source_pdf.read_bytes(),
        filename=cast(str, case["filename"]),
        target_text=cast(str, case["number_block_text"]),
    )
    chat = FakeChatProvider(responses=[_abstention_payload()])
    response = _ask(
        client,
        _service_for_target(target, index, embedding, chat),
        document_id,
        "Đơn vị nào cấp kinh phí cho dự án không có trong tài liệu này?",
    )

    assert response.status_code == 200
    assert response.json()["status"] == "insufficient_evidence"
    assert response.json()["citations"] == []
    assert "kinh phí" not in response.json()["answer"]


def test_case_5_prompt_injection_remains_untrusted_source_data(
    client: TestClient,
    upload: Callable[..., Response],
    session: Session,
    storage: LocalObjectStorage,
    settings: Settings,
) -> None:
    case = _mapping(_fixture()["injection"])
    document_id, _, target, index, embedding = _upload_and_index(
        client,
        upload,
        session,
        storage,
        settings,
        _pdf_from_pages(cast(list[list[str]], case["pages"])),
        filename=cast(str, case["filename"]),
        target_text=cast(str, case["target_text"]),
    )
    safe_answer = cast(str, case["safe_answer"])
    chat = FakeChatProvider(
        responses=[_citation_payload(answer=safe_answer, document_id=document_id, row=target)]
    )
    response = _ask(
        client,
        _service_for_target(target, index, embedding, chat),
        document_id,
        cast(str, case["question"]),
    )

    assert response.status_code == 200
    assert response.json()["answer"] == safe_answer
    assert "system prompt" not in response.json()["answer"].lower()
    assert "secret" not in response.json()["answer"].lower()
    assert len(chat.calls) == 1
    system_prompt = chat.calls[0].messages[0].content
    user_prompt = chat.calls[0].messages[1].content
    assert "không gọi công cụ/dịch vụ" in system_prompt
    assert "system prompt" in system_prompt
    injection_text = cast(str, case["injection_text"])
    assert "<UNTRUSTED_DOCUMENT_DATA>" in user_prompt
    assert injection_text in user_prompt
    assert "</UNTRUSTED_DOCUMENT_DATA>" in user_prompt
    citation = response.json()["citations"][0]
    assert citation["quote"] == target.text


def test_case_6_current_qa_scope_cannot_retrieve_stale_parse_run(
    client: TestClient,
    upload: Callable[..., Response],
    session: Session,
    storage: LocalObjectStorage,
    settings: Settings,
) -> None:
    case = _mapping(_fixture()["decision"])
    source_pdf = REPO_ROOT / cast(str, case["source_pdf"])
    document_id, run_v1, _, index, embedding = _upload_and_index(
        client,
        upload,
        session,
        storage,
        settings,
        source_pdf.read_bytes(),
        filename=cast(str, case["filename"]),
        target_text=cast(str, case["number_block_text"]),
    )
    reprocess = client.post(f"/api/v1/documents/{document_id}/reprocess")
    assert reprocess.status_code == 202
    run_v2 = process_next_job(
        session,
        storage,
        settings,
        "qa-integration-worker-v2",
        auto_index=True,
        embedding_provider=embedding,
        document_index=index,
    )
    assert run_v2 is not None
    assert run_v2.id != run_v1.id
    stale_rows = list(
        session.scalars(select(DocumentChunk).where(DocumentChunk.parse_run_id == run_v1.id)).all()
    )
    assert stale_rows
    stale_rows[0].text = "STALE_VERSION_ONLY secret from the historical parse run"
    session.commit()
    current_target = _row_for_text(
        session,
        document_id,
        run_v2.id,
        cast(str, case["number_block_text"]),
    )
    chat = FakeChatProvider(responses=[_abstention_payload()])
    response = _ask(
        client,
        _service_for_target(current_target, index, embedding, chat),
        document_id,
        "STALE_VERSION_ONLY có nghĩa là gì?",
    )

    assert response.status_code == 200
    assert response.json()["status"] == "insufficient_evidence"
    assert response.json()["citations"] == []
    data_blocks = [
        part for part in chat.calls[0].messages[1].content.split("<UNTRUSTED_DOCUMENT_DATA>")[1:]
    ]
    assert all("STALE_VERSION_ONLY secret" not in part for part in data_blocks)
    assert all(row.parse_run_id == run_v1.id for row in stale_rows)


def test_case_7_worker_offline_preserves_document_and_returns_retryable_state(
    client: TestClient,
    upload: Callable[..., Response],
    session: Session,
    storage: LocalObjectStorage,
    settings: Settings,
) -> None:
    case = _mapping(_fixture()["decision"])
    source_pdf = REPO_ROOT / cast(str, case["source_pdf"])
    document_id, _, target, index, embedding = _upload_and_index(
        client,
        upload,
        session,
        storage,
        settings,
        source_pdf.read_bytes(),
        filename=cast(str, case["filename"]),
        target_text=cast(str, case["number_block_text"]),
    )
    original = client.get(f"/api/v1/documents/{document_id}/file")
    assert original.status_code == 200
    chat = FakeChatProvider(
        responses=[WorkerError(WorkerErrorCode.UNAVAILABLE, "synthetic offline worker")]
    )
    response = _ask(
        client,
        _service_for_target(target, index, embedding, chat),
        document_id,
        "Số văn bản là bao nhiêu?",
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "ai_worker_unavailable"
    assert response.json()["error"]["retryable"] is True
    assert client.get(f"/api/v1/documents/{document_id}/file").content == original.content
    document = session.get(Document, document_id)
    assert document is not None
    assert document.status == DocumentStatus.READY.value
