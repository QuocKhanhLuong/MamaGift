"""Tests for per-document-type evaluation metric hooks, focused on the plan
(`Kế hoạch`) task-owner-deadline metrics the /goal calls out explicitly."""

from __future__ import annotations

from typing import Any

import pytest

from mamagift_eval.metrics import (
    deadline_accuracy,
    nested_hierarchy_f1,
    table_appendix_preservation,
    task_deadline_association_accuracy,
    task_order_accuracy,
    task_owner_association_accuracy,
    task_recall,
)
from mamagift_eval.schemas import ExpectedTaskRelation, ParserSemanticCase
from mamagift_retrieval.chunk import Chunk, ChunkType

pytestmark = pytest.mark.unit


def _task_chunk(
    chunk_id: str,
    ordinal: str,
    owner: str | None = None,
    deadline: str | None = None,
    document_id: str = "doc_1",
    parse_run_id: str = "run_1",
    document_version: int = 1,
    document_type: str = "ke_hoach",
    chunk_type: ChunkType = ChunkType.PLAN_TASK,
    source_block_ids: list[str] | None = None,
    source_page_numbers: list[int] | None = None,
    metadata: dict[str, Any] | None = None,
) -> Chunk:
    meta = {"ordinal": ordinal, "owner": owner, "deadline": deadline}
    if metadata is not None:
        meta = metadata
    return Chunk(
        chunk_id=chunk_id,
        parent_chunk_id=None,
        document_id=document_id,
        parse_run_id=parse_run_id,
        document_version=document_version,
        document_type=document_type,
        document_number=None,
        issuer=None,
        issued_date=None,
        section_path=[f"{ordinal}. task"],
        chunk_type=chunk_type,
        text=f"task {ordinal}",
        source_block_ids=source_block_ids or ["b_1_0000"],
        source_page_numbers=source_page_numbers or [1],
        metadata=meta,
    )


_EXPECTED = [
    ExpectedTaskRelation(task_ordinal="1", task_title="A", owner="Owner A", deadline="2026-08-15"),
    ExpectedTaskRelation(task_ordinal="2", task_title="B", owner="Owner B", deadline="2026-08-30"),
]


# ===========================================================================
# 1. task_recall
# ===========================================================================


def test_task_recall_is_perfect_when_both_tasks_present() -> None:
    chunks = [
        _task_chunk("t1", "1", "Owner A", "2026-08-15"),
        _task_chunk("t2", "2", "Owner B", "2026-08-30"),
    ]
    assert task_recall(_EXPECTED, chunks) == 1.0


def test_task_recall_drops_when_a_task_is_missing() -> None:
    chunks = [_task_chunk("t1", "1", "Owner A", "2026-08-15")]
    assert task_recall(_EXPECTED, chunks) == 0.5


def test_task_recall_empty_expected_is_trivially_perfect() -> None:
    chunks = [_task_chunk("t1", "1", "Owner A", "2026-08-15")]
    assert task_recall([], chunks) == 1.0
    assert task_recall([], []) == 1.0


def test_task_recall_empty_actual_drops_to_zero() -> None:
    assert task_recall(_EXPECTED, []) == 0.0


def test_task_recall_ignores_non_plan_task_chunks() -> None:
    chunks = [
        _task_chunk("t1", "1", chunk_type=ChunkType.PARAGRAPH),
        _task_chunk("t2", "2", chunk_type=ChunkType.LEGAL_ARTICLE),
    ]
    assert task_recall(_EXPECTED, chunks) == 0.0


def test_task_recall_rejects_foreign_document_type() -> None:
    chunks = [
        _task_chunk("t1", "1", document_type="cong_van"),
        _task_chunk("t2", "2", document_type="cong_van"),
    ]
    assert task_recall(_EXPECTED, chunks) == 0.0


def test_task_recall_rejects_foreign_document_id() -> None:
    chunks = [
        _task_chunk("t1", "1", document_id="doc_1"),
        _task_chunk("t2", "2", document_id="doc_2"),
    ]
    assert task_recall(_EXPECTED, chunks) == 0.5


def test_task_recall_rejects_foreign_parse_run_id() -> None:
    chunks = [
        _task_chunk("t1", "1", parse_run_id="run_1"),
        _task_chunk("t2", "2", parse_run_id="run_2"),
    ]
    assert task_recall(_EXPECTED, chunks) == 0.5


def test_task_recall_rejects_foreign_document_version() -> None:
    chunks = [
        _task_chunk("t1", "1", document_version=1),
        _task_chunk("t2", "2", document_version=2),
    ]
    assert task_recall(_EXPECTED, chunks) == 0.5


def test_task_recall_raises_on_duplicate_actual_ordinals() -> None:
    chunks = [
        _task_chunk("t1", "1"),
        _task_chunk("t2", "1"),
    ]
    with pytest.raises(ValueError, match="duplicate task ordinal"):
        task_recall(_EXPECTED, chunks)


def test_task_recall_raises_on_duplicate_expected_ordinals() -> None:
    dup_expected = [
        ExpectedTaskRelation(task_ordinal="1", task_title="A"),
        ExpectedTaskRelation(task_ordinal="1", task_title="A duplicate"),
    ]
    chunks = [_task_chunk("t1", "1")]
    with pytest.raises(ValueError, match="duplicate expected task_ordinal"):
        task_recall(dup_expected, chunks)


def test_task_recall_ignores_chunk_with_missing_or_non_string_ordinal() -> None:
    chunks = [
        _task_chunk("t1", "1", metadata={"ordinal": None}),
        _task_chunk("t2", "2", metadata={"ordinal": None}),
        _task_chunk("t3", "3", metadata={"ordinal": 123}),
    ]
    assert task_recall(_EXPECTED, chunks) == 0.0


# ===========================================================================
# 2. task_order_accuracy
# ===========================================================================


def test_task_order_accuracy_detects_swapped_order() -> None:
    swapped = [
        _task_chunk("t2", "2", "Owner B", "2026-08-30"),
        _task_chunk("t1", "1", "Owner A", "2026-08-15"),
    ]
    assert task_order_accuracy(_EXPECTED, swapped) == 0.0


def test_task_order_accuracy_perfect_when_correctly_ordered() -> None:
    chunks = [
        _task_chunk("t1", "1", "Owner A", "2026-08-15"),
        _task_chunk("t2", "2", "Owner B", "2026-08-30"),
    ]
    assert task_order_accuracy(_EXPECTED, chunks) == 1.0


def test_task_order_accuracy_single_or_empty_expected_is_trivially_perfect() -> None:
    assert task_order_accuracy([], []) == 1.0
    assert task_order_accuracy([_EXPECTED[0]], []) == 1.0


def test_task_order_accuracy_empty_actual_drops_to_zero() -> None:
    assert task_order_accuracy(_EXPECTED, []) == 0.0


def test_task_order_accuracy_rejects_foreign_chunk() -> None:
    chunks = [
        _task_chunk("t1", "1", document_id="doc_1"),
        _task_chunk("t2", "2", document_id="doc_2"),
    ]
    assert task_order_accuracy(_EXPECTED, chunks) == 0.0


def test_task_order_accuracy_ignores_non_plan_task_chunks() -> None:
    chunks = [
        _task_chunk("t1", "1", chunk_type=ChunkType.PARAGRAPH),
        _task_chunk("t2", "2", chunk_type=ChunkType.PLAN_TASK),
    ]
    assert task_order_accuracy(_EXPECTED, chunks) == 0.0


def test_task_order_accuracy_raises_on_duplicate_ordinals() -> None:
    chunks = [
        _task_chunk("t1", "1"),
        _task_chunk("t2", "1"),
    ]
    with pytest.raises(ValueError, match="duplicate task ordinal"):
        task_order_accuracy(_EXPECTED, chunks)


# ===========================================================================
# 3. task_owner_association_accuracy
# ===========================================================================


def test_owner_and_deadline_association_never_cross_tasks() -> None:
    crossed = [
        _task_chunk("t1", "1", "Owner B", "2026-08-30"),
        _task_chunk("t2", "2", "Owner A", "2026-08-15"),
    ]
    assert task_owner_association_accuracy(_EXPECTED, crossed) == 0.0
    assert task_deadline_association_accuracy(_EXPECTED, crossed) == 0.0
    assert deadline_accuracy(_EXPECTED, crossed) == 0.0


def test_owner_and_deadline_association_perfect_when_correctly_scoped() -> None:
    chunks = [
        _task_chunk("t1", "1", "Owner A", "2026-08-15"),
        _task_chunk("t2", "2", "Owner B", "2026-08-30"),
    ]
    assert task_owner_association_accuracy(_EXPECTED, chunks) == 1.0
    assert task_deadline_association_accuracy(_EXPECTED, chunks) == 1.0


def test_owner_association_no_expected_owners_is_trivially_perfect() -> None:
    no_owner = [
        ExpectedTaskRelation(task_ordinal="1", task_title="A", owner=None),
        ExpectedTaskRelation(task_ordinal="2", task_title="B", owner=None),
    ]
    assert task_owner_association_accuracy(no_owner, []) == 1.0


def test_owner_association_empty_actual_drops_to_zero() -> None:
    assert task_owner_association_accuracy(_EXPECTED, []) == 0.0


def test_owner_association_rejects_foreign_chunk() -> None:
    chunks = [
        _task_chunk("t1", "1", "Owner A", "2026-08-15", document_id="doc_1"),
        _task_chunk("t2", "2", "Owner B", "2026-08-30", document_id="doc_2"),
    ]
    assert task_owner_association_accuracy(_EXPECTED, chunks) == 0.5


def test_owner_association_ignores_non_plan_task_chunks() -> None:
    chunks = [
        _task_chunk("t1", "1", "Owner A", chunk_type=ChunkType.PARAGRAPH),
        _task_chunk("t2", "2", "Owner B", chunk_type=ChunkType.PLAN_TASK),
    ]
    assert task_owner_association_accuracy(_EXPECTED, chunks) == 0.5


def test_owner_association_raises_on_duplicate_ordinals() -> None:
    chunks = [
        _task_chunk("t1", "1", "Owner A"),
        _task_chunk("t2", "1", "Owner A"),
    ]
    with pytest.raises(ValueError, match="duplicate task ordinal"):
        task_owner_association_accuracy(_EXPECTED, chunks)


# ===========================================================================
# 4. task_deadline_association_accuracy & deadline_accuracy
# ===========================================================================


def test_positive_deadline_accuracy_scores_perfect() -> None:
    chunks = [
        _task_chunk("t1", "1", "Owner A", "2026-08-15"),
        _task_chunk("t2", "2", "Owner B", "2026-08-30"),
    ]
    assert deadline_accuracy(_EXPECTED, chunks) == 1.0
    assert task_deadline_association_accuracy(_EXPECTED, chunks) == 1.0


def test_deadline_accuracy_partial_match() -> None:
    chunks = [
        _task_chunk("t1", "1", "Owner A", "2026-08-15"),
        _task_chunk("t2", "2", "Owner B", "2026-12-31"),  # Wrong deadline
    ]
    assert deadline_accuracy(_EXPECTED, chunks) == 0.5
    assert task_deadline_association_accuracy(_EXPECTED, chunks) == 0.5


def test_deadline_accuracy_no_expected_deadlines_is_trivially_perfect() -> None:
    no_deadline = [
        ExpectedTaskRelation(task_ordinal="1", task_title="A", deadline=None),
        ExpectedTaskRelation(task_ordinal="2", task_title="B", deadline=None),
    ]
    assert deadline_accuracy(no_deadline, []) == 1.0


def test_deadline_accuracy_empty_actual_drops_to_zero() -> None:
    assert deadline_accuracy(_EXPECTED, []) == 0.0


def test_deadline_accuracy_rejects_foreign_chunk() -> None:
    chunks = [
        _task_chunk("t1", "1", "Owner A", "2026-08-15", document_id="doc_1"),
        _task_chunk("t2", "2", "Owner B", "2026-08-30", document_id="doc_2"),
    ]
    assert deadline_accuracy(_EXPECTED, chunks) == 0.5


def test_deadline_accuracy_ignores_non_plan_task_chunks() -> None:
    chunks = [
        _task_chunk("t1", "1", deadline="2026-08-15", chunk_type=ChunkType.PARAGRAPH),
        _task_chunk("t2", "2", deadline="2026-08-30", chunk_type=ChunkType.PLAN_TASK),
    ]
    assert deadline_accuracy(_EXPECTED, chunks) == 0.5


def test_deadline_accuracy_raises_on_duplicate_ordinals() -> None:
    chunks = [
        _task_chunk("t1", "1", deadline="2026-08-15"),
        _task_chunk("t2", "1", deadline="2026-08-15"),
    ]
    with pytest.raises(ValueError, match="duplicate task ordinal"):
        deadline_accuracy(_EXPECTED, chunks)


# ===========================================================================
# 5. nested_hierarchy_f1
# ===========================================================================


def test_nested_hierarchy_f1_perfect_match() -> None:
    chunks = [
        _task_chunk("t1", "1", "Owner A", "2026-08-15"),
        _task_chunk("t2", "2", "Owner B", "2026-08-30"),
    ]
    assert nested_hierarchy_f1(["1. task", "2. task"], chunks) == 1.0


def test_nested_hierarchy_f1_no_expected_labels_is_trivially_perfect() -> None:
    assert nested_hierarchy_f1([], []) == 1.0
    assert nested_hierarchy_f1([], [_task_chunk("t1", "1")]) == 1.0


def test_nested_hierarchy_f1_empty_actual_labels_returns_zero() -> None:
    assert nested_hierarchy_f1(["1. task"], []) == 0.0


def test_nested_hierarchy_f1_non_perfect_f1() -> None:
    # Expected: ["A", "B"], Actual: ["A", "C"]
    # True Positives = 1 ("A"), Precision = 1/2 = 0.5, Recall = 1/2 = 0.5, F1 = 0.5
    chunk_a = Chunk(
        chunk_id="ca",
        document_id="doc_1",
        parse_run_id="run_1",
        document_version=1,
        document_type="ke_hoach",
        section_path=["A"],
        chunk_type=ChunkType.PLAN_TASK,
        text="A",
        source_block_ids=["b1"],
        source_page_numbers=[1],
    )
    chunk_c = Chunk(
        chunk_id="cc",
        document_id="doc_1",
        parse_run_id="run_1",
        document_version=1,
        document_type="ke_hoach",
        section_path=["C"],
        chunk_type=ChunkType.PLAN_TASK,
        text="C",
        source_block_ids=["b2"],
        source_page_numbers=[1],
    )
    assert nested_hierarchy_f1(["A", "B"], [chunk_a, chunk_c]) == 0.5


def test_nested_hierarchy_f1_zero_overlap_returns_zero() -> None:
    chunk = Chunk(
        chunk_id="c1",
        document_id="doc_1",
        parse_run_id="run_1",
        document_version=1,
        document_type="ke_hoach",
        section_path=["X"],
        chunk_type=ChunkType.PLAN_TASK,
        text="X",
        source_block_ids=["b1"],
        source_page_numbers=[1],
    )
    assert nested_hierarchy_f1(["A", "B"], [chunk]) == 0.0


def test_nested_hierarchy_f1_rejects_foreign_document_id() -> None:
    chunk1 = Chunk(
        chunk_id="c1",
        document_id="doc_1",
        parse_run_id="run_1",
        document_version=1,
        document_type="ke_hoach",
        section_path=["A"],
        chunk_type=ChunkType.PLAN_TASK,
        text="A",
        source_block_ids=["b1"],
        source_page_numbers=[1],
    )
    chunk2 = Chunk(
        chunk_id="c2",
        document_id="doc_2",  # Foreign document!
        parse_run_id="run_1",
        document_version=1,
        document_type="ke_hoach",
        section_path=["B"],
        chunk_type=ChunkType.PLAN_TASK,
        text="B",
        source_block_ids=["b2"],
        source_page_numbers=[1],
    )
    # With foreign chunk rejected: only "A" is valid. Expected: ["A", "B"], Actual: ["A"]
    # TP = 1, Precision = 1/1 = 1.0, Recall = 1/2 = 0.5, F1 = 2 * (1 * 0.5) / 1.5 = 2/3 ≈ 0.6667
    f1 = nested_hierarchy_f1(["A", "B"], [chunk1, chunk2])
    assert pytest.approx(f1, rel=1e-3) == 2.0 / 3.0


# ===========================================================================
# 6. table_appendix_preservation
# ===========================================================================


def _appendix_chunk(
    chunk_id: str,
    document_id: str = "doc_1",
    document_type: str = "table_appendix",
    parse_run_id: str = "run_1",
    document_version: int = 1,
    source_block_ids: list[str] | None = None,
    source_page_numbers: list[int] | None = None,
) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        parent_chunk_id=None,
        document_id=document_id,
        parse_run_id=parse_run_id,
        document_version=document_version,
        document_type=document_type,
        section_path=["Phụ lục"],
        chunk_type=ChunkType.APPENDIX,
        text="Bảng phụ lục",
        source_block_ids=source_block_ids or ["b_1_0000"],
        source_page_numbers=source_page_numbers or [1],
    )


def test_table_appendix_preservation_covers_expected_blocks() -> None:
    case = ParserSemanticCase(
        case_id="c1",
        document_id="doc_1",
        document_type="table_appendix",
        expected_source_block_ids=["b_1_0000"],
    )
    chunks = [_appendix_chunk("t1", source_block_ids=["b_1_0000"])]
    assert table_appendix_preservation(case, chunks) == 1.0


def test_table_appendix_preservation_flags_missing_blocks() -> None:
    case = ParserSemanticCase(
        case_id="c2",
        document_id="doc_1",
        document_type="table_appendix",
        expected_source_block_ids=["b_1_0000", "b_1_9999"],
    )
    chunks = [_appendix_chunk("t1", source_block_ids=["b_1_0000"])]
    assert table_appendix_preservation(case, chunks) == 0.5


def test_table_appendix_preservation_empty_expected_is_perfect() -> None:
    case = ParserSemanticCase(
        case_id="c3",
        document_id="doc_1",
        document_type="table_appendix",
        expected_source_block_ids=[],
        expected_source_page_numbers=[],
    )
    assert table_appendix_preservation(case, []) == 1.0


def test_table_appendix_preservation_empty_actual_drops_to_zero() -> None:
    case = ParserSemanticCase(
        case_id="c4",
        document_id="doc_1",
        document_type="table_appendix",
        expected_source_block_ids=["b_1_0000"],
    )
    assert table_appendix_preservation(case, []) == 0.0


def test_table_appendix_preservation_rejects_foreign_document_id() -> None:
    case = ParserSemanticCase(
        case_id="c5",
        document_id="doc_1",
        document_type="table_appendix",
        expected_source_block_ids=["b_1_0000", "b_1_0001"],
    )
    chunks = [
        _appendix_chunk("t1", document_id="doc_1", source_block_ids=["b_1_0000"]),
        _appendix_chunk("t2", document_id="doc_2", source_block_ids=["b_1_0001"]),
    ]
    assert table_appendix_preservation(case, chunks) == 0.5


def test_table_appendix_preservation_rejects_foreign_document_type() -> None:
    case = ParserSemanticCase(
        case_id="c6",
        document_id="doc_1",
        document_type="table_appendix",
        expected_source_block_ids=["b_1_0000", "b_1_0001"],
    )
    chunks = [
        _appendix_chunk("t1", document_type="table_appendix", source_block_ids=["b_1_0000"]),
        _appendix_chunk("t2", document_type="cong_van", source_block_ids=["b_1_0001"]),
    ]
    assert table_appendix_preservation(case, chunks) == 0.5


def test_table_appendix_preservation_rejects_foreign_parse_run_id() -> None:
    case = ParserSemanticCase(
        case_id="c7",
        document_id="doc_1",
        document_type="table_appendix",
        expected_source_block_ids=["b_1_0000", "b_1_0001"],
    )
    chunks = [
        _appendix_chunk("t1", parse_run_id="run_1", source_block_ids=["b_1_0000"]),
        _appendix_chunk("t2", parse_run_id="run_2", source_block_ids=["b_1_0001"]),
    ]
    assert table_appendix_preservation(case, chunks) == 0.5


def test_table_appendix_preservation_rejects_foreign_document_version() -> None:
    case = ParserSemanticCase(
        case_id="c8",
        document_id="doc_1",
        document_type="table_appendix",
        expected_source_block_ids=["b_1_0000", "b_1_0001"],
    )
    chunks = [
        _appendix_chunk("t1", document_version=1, source_block_ids=["b_1_0000"]),
        _appendix_chunk("t2", document_version=2, source_block_ids=["b_1_0001"]),
    ]
    assert table_appendix_preservation(case, chunks) == 0.5


def test_table_appendix_preservation_rejects_foreign_source_pages() -> None:
    case = ParserSemanticCase(
        case_id="c9",
        document_id="doc_1",
        document_type="table_appendix",
        expected_source_block_ids=["b_1_0000"],
        expected_source_page_numbers=[1],
    )
    # Chunk has correct block id but from wrong source page 2
    chunks = [_appendix_chunk("t1", source_block_ids=["b_1_0000"], source_page_numbers=[2])]
    assert table_appendix_preservation(case, chunks) == 0.0


def test_table_appendix_preservation_page_level_when_no_blocks_declared() -> None:
    case = ParserSemanticCase(
        case_id="c10",
        document_id="doc_1",
        document_type="table_appendix",
        expected_source_block_ids=[],
        expected_source_page_numbers=[1, 2],
    )
    chunks = [_appendix_chunk("t1", source_page_numbers=[1])]
    assert table_appendix_preservation(case, chunks) == 0.5
