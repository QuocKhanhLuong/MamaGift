"""Tests for the Phase 3.5 deterministic evaluation data-contract schemas.

No LLM evaluator or generation-quality scoring is implemented here — these are data
shapes an eval runner scores deterministic parser/chunking output against.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from mamagift_eval.schemas import ExpectedTaskRelation, ParserSemanticCase, RetrievalQACase

pytestmark = pytest.mark.unit


def test_parser_semantic_case_minimal_construction() -> None:
    case = ParserSemanticCase(case_id="case_1", document_id="doc_1", document_type="quyet_dinh")
    assert case.expected_critical_fields == {}
    assert case.expected_task_relations == []


def test_parser_semantic_case_with_task_relations() -> None:
    case = ParserSemanticCase(
        case_id="case_2",
        document_id="doc_2",
        document_type="ke_hoach",
        expected_task_relations=[
            ExpectedTaskRelation(
                task_ordinal="1",
                task_title="Rà soát danh sách",
                owner="Phòng Giáo dục và Đào tạo",
                deadline="2026-08-15",
            ),
            ExpectedTaskRelation(
                task_ordinal="2",
                task_title="Tổ chức tiếp nhận hồ sơ",
                owner="Trường Tiểu học Mai Giang",
                deadline="2026-08-30",
            ),
        ],
    )
    assert len(case.expected_task_relations) == 2
    assert case.expected_task_relations[0].deadline != case.expected_task_relations[1].deadline


def test_parser_semantic_case_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError):
        ParserSemanticCase(
            case_id="case_3",
            document_id="doc_3",
            document_type="cong_van",
            not_a_real_field="x",  # type: ignore[call-arg]
        )


def test_retrieval_qa_case_requires_at_least_one_expected_document() -> None:
    with pytest.raises(ValidationError):
        RetrievalQACase(
            case_id="qa_1", question="Văn bản này yêu cầu gì?", expected_document_ids=[]
        )


def test_retrieval_qa_case_minimal_construction() -> None:
    case = RetrievalQACase(
        case_id="qa_2",
        question="Đơn vị nào chủ trì rà soát danh sách?",
        expected_document_ids=["doc_2"],
    )
    assert case.forbidden_document_ids == []
    assert case.required_metadata_scope == {}
