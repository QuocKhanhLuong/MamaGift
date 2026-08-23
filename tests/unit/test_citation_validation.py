"""Deterministic fake-model tests for answer and citation validation."""

from __future__ import annotations

import asyncio
import json

import pytest

from mamagift_contracts.llm import ChatMessage, CompletionRequest
from mamagift_rag.schema import ModelRef
from mamagift_rag.validation import (
    FAILED_VALIDATION_MESSAGE,
    INSUFFICIENT_EVIDENCE_MESSAGE,
    parse_and_validate_answer,
)
from mamagift_retrieval.budget import BudgetBreakdown
from mamagift_retrieval.evidence import Evidence, EvidenceSet
from mamagift_retrieval.providers import FakeChatProvider
from mamagift_retrieval.scope import EvidenceScope

pytestmark = pytest.mark.unit

MODEL = ModelRef(provider="fake_chat", model="fake-qwen", version="test-1")


def _evidence_set(
    *, document_id: str = "document-1", parse_run_id: str = "parse-2", document_version: int = 2
) -> EvidenceSet:
    scope = EvidenceScope(
        family_id="family-1",
        document_id="document-1",
        document_version=2,
        parse_run_id="parse-2",
    )
    return EvidenceSet(
        scope=scope,
        evidence=[
            Evidence(
                citation_id="c1",
                chunk_id="chunk-1",
                document_id=document_id,
                parse_run_id=parse_run_id,
                document_version=document_version,
                page_numbers=[2],
                source_block_ids=["block-1"],
                section_path=["Điều 1"],
                text="Nhà trường phải báo cáo trước ngày 10.",
            )
        ],
        budget=BudgetBreakdown(categories=[]),
        query_id="query-1",
    )


def _citation(*, citation_id: str = "c1", document_id: str = "document-1") -> dict[str, object]:
    return {
        "citation_id": citation_id,
        "document_id": document_id,
        "page_number": 2,
        "block_ids": ["block-1"],
        "quote": "Nhà trường phải báo cáo trước ngày 10.",
    }


def _fake_raw(payload: dict[str, object]) -> str:
    provider = FakeChatProvider(responses=[json.dumps(payload, ensure_ascii=False)])
    request = CompletionRequest(
        messages=[ChatMessage(role="user", content="deterministic test")],
        max_output_tokens=128,
        response_format="json_object",
    )
    return asyncio.run(provider.complete(request)).text


def test_only_allow_listed_citation_ids_survive() -> None:
    raw = _fake_raw(
        {
            "answer": "Nhà trường phải báo cáo.",
            "status": "answered",
            "citations": [_citation()],
        }
    )

    result = parse_and_validate_answer(raw, _evidence_set(), model=MODEL)

    assert result.status == "answered"
    assert [citation.citation_id for citation in result.citations] == ["c1"]


def test_unknown_citation_rejects_the_whole_answer() -> None:
    raw = _fake_raw(
        {
            "answer": "Nội dung có vẻ hợp lý.",
            "status": "answered",
            "citations": [_citation(citation_id="c999")],
        }
    )

    result = parse_and_validate_answer(raw, _evidence_set(), model=MODEL)

    assert result.status == "failed"
    assert result.answer == FAILED_VALIDATION_MESSAGE
    assert result.citations == []


def test_answer_without_citations_downgrades_to_insufficient_evidence() -> None:
    raw = _fake_raw(
        {"answer": "Một câu trả lời không có nguồn.", "status": "answered", "citations": []}
    )

    result = parse_and_validate_answer(raw, _evidence_set(), model=MODEL)

    assert result.status == "insufficient_evidence"
    assert result.answer == INSUFFICIENT_EVIDENCE_MESSAGE
    assert result.citations == []


def test_abstention_branch_has_documented_shape() -> None:
    raw = _fake_raw(
        {"answer": "Tôi không biết.", "status": "insufficient_evidence", "citations": []}
    )

    result = parse_and_validate_answer(raw, _evidence_set(), model=MODEL)

    assert result.model == MODEL
    assert result.retrieval.query_id == "query-1"
    assert result.status == "insufficient_evidence"
    assert result.citations == []
    assert result.answer == INSUFFICIENT_EVIDENCE_MESSAGE


@pytest.mark.parametrize("raw_text", ["not json", "[]", '{"answer": "missing fields"}'])
def test_malformed_response_fails_loudly(raw_text: str) -> None:
    result = parse_and_validate_answer(raw_text, _evidence_set(), model=MODEL)

    assert result.status == "failed"
    assert result.answer == FAILED_VALIDATION_MESSAGE
    assert result.citations == []


def test_citation_from_another_document_is_rejected() -> None:
    raw = _fake_raw(
        {
            "answer": "Câu trả lời ngoài phạm vi.",
            "status": "answered",
            "citations": [_citation(document_id="document-2")],
        }
    )

    result = parse_and_validate_answer(raw, _evidence_set(document_id="document-2"), model=MODEL)

    assert result.status == "failed"
    assert result.citations == []


def test_citation_metadata_from_another_document_is_rejected() -> None:
    raw = _fake_raw(
        {
            "answer": "Câu trả lời giả mạo.",
            "status": "answered",
            "citations": [_citation(document_id="document-2")],
        }
    )

    result = parse_and_validate_answer(raw, _evidence_set(), model=MODEL)

    assert result.status == "failed"
    assert result.citations == []


def test_stale_parse_run_evidence_is_rejected() -> None:
    raw = _fake_raw(
        {
            "answer": "Câu trả lời từ bản cũ.",
            "status": "answered",
            "citations": [_citation()],
        }
    )

    result = parse_and_validate_answer(raw, _evidence_set(parse_run_id="parse-old"), model=MODEL)

    assert result.status == "failed"
    assert result.citations == []


def test_stale_document_version_evidence_is_rejected() -> None:
    raw = _fake_raw(
        {
            "answer": "Câu trả lời từ bản cũ.",
            "status": "answered",
            "citations": [_citation()],
        }
    )

    result = parse_and_validate_answer(raw, _evidence_set(document_version=1), model=MODEL)

    assert result.status == "failed"
    assert result.citations == []


@pytest.mark.parametrize(
    "citation_update",
    [
        {"page_number": 99},
        {"block_ids": ["block-other"]},
        {"quote": "Không nằm trong bằng chứng."},
    ],
)
def test_forged_citation_location_or_quote_is_rejected(
    citation_update: dict[str, object],
) -> None:
    citation = _citation()
    citation.update(citation_update)
    raw = _fake_raw(
        {"answer": "Câu trả lời giả mạo.", "status": "answered", "citations": [citation]}
    )

    result = parse_and_validate_answer(raw, _evidence_set(), model=MODEL)

    assert result.status == "failed"
    assert result.citations == []
