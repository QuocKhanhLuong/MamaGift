"""Tests for the Phase 3.5 deterministic evaluation data-contract schemas.

No LLM evaluator or generation-quality scoring is implemented here — these are data
shapes an eval runner scores deterministic parser/chunking output against.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from mamagift_eval.schemas import ExpectedTaskRelation, ParserSemanticCase, RetrievalQACase

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# ParserSemanticCase & ExpectedTaskRelation tests
# ---------------------------------------------------------------------------


def test_parser_semantic_case_minimal_construction() -> None:
    case = ParserSemanticCase(case_id="case_1", document_id="doc_1", document_type="quyet_dinh")
    assert case.case_id == "case_1"
    assert case.document_id == "doc_1"
    assert case.document_type == "quyet_dinh"
    assert case.expected_critical_fields == {}
    assert case.expected_hierarchy_labels == []
    assert case.expected_task_relations == []
    assert case.expected_source_block_ids == []
    assert case.expected_source_page_numbers == []


def test_parser_semantic_case_provenance_and_hierarchy() -> None:
    case = ParserSemanticCase(
        case_id="case_prov",
        document_id="doc_prov",
        document_type="quyet_dinh",
        expected_critical_fields={"so_ky_hieu": "123/QD-UBND", "ngay_ban_hanh": "2026-08-01"},
        expected_hierarchy_labels=["Điều 1", "Khoản 1"],
        expected_source_block_ids=["block_001", "block_002"],
        expected_source_page_numbers=[1, 2],
    )
    assert case.expected_critical_fields == {
        "so_ky_hieu": "123/QD-UBND",
        "ngay_ban_hanh": "2026-08-01",
    }
    assert case.expected_hierarchy_labels == ["Điều 1", "Khoản 1"]
    assert case.expected_source_block_ids == ["block_001", "block_002"]
    assert case.expected_source_page_numbers == [1, 2]


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


@pytest.mark.parametrize(
    ("case_id", "document_id", "document_type"),
    [
        ("", "doc_1", "quyet_dinh"),
        ("case_1", "", "quyet_dinh"),
        ("case_1", "doc_1", ""),
    ],
)
def test_parser_semantic_case_rejects_empty_ids(
    case_id: str, document_id: str, document_type: str
) -> None:
    with pytest.raises(ValidationError):
        ParserSemanticCase(
            case_id=case_id,
            document_id=document_id,
            document_type=document_type,
        )


def test_expected_task_relation_minimal_and_optional_fields() -> None:
    # Omitting optional fields
    relation = ExpectedTaskRelation(
        task_ordinal="1",
        task_title="Nhiệm vụ 1",
    )
    assert relation.task_ordinal == "1"
    assert relation.task_title == "Nhiệm vụ 1"
    assert relation.owner is None
    assert relation.coordinating_unit is None
    assert relation.deadline is None

    # Explicit None for optional fields
    relation_explicit_none = ExpectedTaskRelation(
        task_ordinal="1.1",
        task_title="Nhiệm vụ phụ",
        owner=None,
        coordinating_unit=None,
        deadline=None,
    )
    assert relation_explicit_none.owner is None
    assert relation_explicit_none.coordinating_unit is None
    assert relation_explicit_none.deadline is None


def test_expected_task_relation_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError):
        ExpectedTaskRelation(
            task_ordinal="1",
            task_title="Nhiệm vụ",
            unexpected_field="disallowed",  # type: ignore[call-arg]
        )


def test_expected_task_relation_rejects_empty_task_ordinal() -> None:
    with pytest.raises(ValidationError):
        ExpectedTaskRelation(
            task_ordinal="",
            task_title="Nhiệm vụ không có ordinal",
        )


# ---------------------------------------------------------------------------
# RetrievalQACase tests
# ---------------------------------------------------------------------------


def test_retrieval_qa_case_minimal_construction() -> None:
    case = RetrievalQACase(
        case_id="qa_2",
        question="Đơn vị nào chủ trì rà soát danh sách?",
        expected_document_ids=["doc_2"],
    )
    assert case.case_id == "qa_2"
    assert case.question == "Đơn vị nào chủ trì rà soát danh sách?"
    assert case.expected_document_ids == ["doc_2"]
    assert case.expected_block_ids == []
    assert case.expected_chunk_ids == []
    assert case.forbidden_document_ids == []
    assert case.required_metadata_scope == {}


def test_retrieval_qa_case_full_construction() -> None:
    case = RetrievalQACase(
        case_id="qa_full",
        question="Ai là người ký quyết định?",
        expected_document_ids=["doc_1", "doc_2"],
        expected_block_ids=["b_01", "b_02"],
        expected_chunk_ids=["c_01"],
        forbidden_document_ids=["doc_old"],
        required_metadata_scope={"document_type": "quyet_dinh"},
    )
    assert case.expected_block_ids == ["b_01", "b_02"]
    assert case.expected_chunk_ids == ["c_01"]
    assert case.forbidden_document_ids == ["doc_old"]
    assert case.required_metadata_scope == {"document_type": "quyet_dinh"}


def test_retrieval_qa_case_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError):
        RetrievalQACase(
            case_id="qa_3",
            question="Hỏi gì đó?",
            expected_document_ids=["doc_1"],
            unknown_attr="invalid",  # type: ignore[call-arg]
        )


def test_retrieval_qa_case_requires_at_least_one_expected_document() -> None:
    with pytest.raises(ValidationError):
        RetrievalQACase(
            case_id="qa_1", question="Văn bản này yêu cầu gì?", expected_document_ids=[]
        )


def test_retrieval_qa_case_rejects_empty_case_id() -> None:
    with pytest.raises(ValidationError):
        RetrievalQACase(
            case_id="",
            question="Câu hỏi hợp lệ?",
            expected_document_ids=["doc_1"],
        )


def test_retrieval_qa_case_rejects_empty_question() -> None:
    with pytest.raises(ValidationError):
        RetrievalQACase(
            case_id="qa_1",
            question="",
            expected_document_ids=["doc_1"],
        )
