"""Deterministic contract tests for grounded prompt construction."""

from __future__ import annotations

import pytest

from mamagift_rag.prompt import build_grounded_prompt
from mamagift_retrieval.budget import BudgetBreakdown
from mamagift_retrieval.evidence import Evidence, EvidenceSet
from mamagift_retrieval.scope import EvidenceScope

pytestmark = pytest.mark.unit


def _evidence_set(*texts: str) -> EvidenceSet:
    scope = EvidenceScope(
        family_id="family-1",
        document_id="document-1",
        document_version=2,
        parse_run_id="parse-2",
    )
    evidence = [
        Evidence(
            citation_id=f"c{index}",
            chunk_id=f"chunk-{index}",
            document_id="document-1",
            parse_run_id="parse-2",
            document_version=2,
            page_numbers=[index],
            source_block_ids=[f"block-{index}"],
            section_path=["Điều 1"],
            text=text,
        )
        for index, text in enumerate(texts, start=1)
    ]
    return EvidenceSet(
        scope=scope,
        evidence=evidence,
        budget=BudgetBreakdown(categories=[]),
        query_id="query-1",
    )


def test_prompt_contains_every_bounded_evidence_item_and_only_its_text() -> None:
    evidence = _evidence_set("Nội dung thứ nhất", "Nội dung thứ hai")

    messages = build_grounded_prompt("Văn bản yêu cầu gì?", evidence)
    user_content = messages[1].content

    assert [message.role for message in messages] == ["system", "user"]
    assert "[citation_id=c1]" in user_content
    assert "[citation_id=c2]" in user_content
    assert "Nội dung thứ nhất" in user_content
    assert "Nội dung thứ hai" in user_content
    assert "chunk-1" not in user_content
    assert "document-1" not in user_content
    assert "query-1" not in user_content
    assert "Điều 1" not in user_content


def test_prompt_respects_already_bounded_retrieved_blocks() -> None:
    evidence = _evidence_set("đã bị cắt")

    messages = build_grounded_prompt("Câu hỏi", evidence)

    assert "đã bị cắt" in messages[1].content
    assert "nội dung chưa được truy xuất" not in messages[1].content


def test_system_message_declares_document_data_untrusted_and_requires_vietnamese() -> None:
    messages = build_grounded_prompt("Câu hỏi", _evidence_set("Một đoạn"))

    system_content = messages[0].content
    assert "UNTRUSTED_DOCUMENT_DATA" in system_content
    assert "dữ liệu" in system_content
    assert "không phải chỉ dẫn" in system_content
    assert "tiếng Việt" in system_content
