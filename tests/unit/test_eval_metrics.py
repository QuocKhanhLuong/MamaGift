"""Tests for per-document-type evaluation metric hooks, focused on the plan
(`Kế hoạch`) task-owner-deadline metrics the /goal calls out explicitly."""

from __future__ import annotations

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


def _task_chunk(chunk_id: str, ordinal: str, owner: str | None, deadline: str | None) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        parent_chunk_id=None,
        document_id="doc_1",
        parse_run_id="run_1",
        document_version=1,
        document_type="ke_hoach",
        document_number=None,
        issuer=None,
        issued_date=None,
        section_path=[f"{ordinal}. task"],
        chunk_type=ChunkType.PLAN_TASK,
        text=f"task {ordinal}",
        source_block_ids=["b_1_0000"],
        source_page_numbers=[1],
        metadata={"ordinal": ordinal, "owner": owner, "deadline": deadline},
    )


_EXPECTED = [
    ExpectedTaskRelation(task_ordinal="1", task_title="A", owner="Owner A", deadline="2026-08-15"),
    ExpectedTaskRelation(task_ordinal="2", task_title="B", owner="Owner B", deadline="2026-08-30"),
]


def test_task_recall_is_perfect_when_both_tasks_present() -> None:
    chunks = [
        _task_chunk("t1", "1", "Owner A", "2026-08-15"),
        _task_chunk("t2", "2", "Owner B", "2026-08-30"),
    ]
    assert task_recall(_EXPECTED, chunks) == 1.0


def test_task_recall_drops_when_a_task_is_missing() -> None:
    chunks = [_task_chunk("t1", "1", "Owner A", "2026-08-15")]
    assert task_recall(_EXPECTED, chunks) == 0.5


def test_task_order_accuracy_detects_swapped_order() -> None:
    swapped = [
        _task_chunk("t2", "2", "Owner B", "2026-08-30"),
        _task_chunk("t1", "1", "Owner A", "2026-08-15"),
    ]
    assert task_order_accuracy(_EXPECTED, swapped) == 0.0


def test_owner_and_deadline_association_never_cross_tasks() -> None:
    # Task 1's owner/deadline swapped onto Task 2 must score as wrong, not right.
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


def test_nested_hierarchy_f1_perfect_match() -> None:
    chunks = [
        _task_chunk("t1", "1", "Owner A", "2026-08-15"),
        _task_chunk("t2", "2", "Owner B", "2026-08-30"),
    ]
    assert nested_hierarchy_f1(["1. task", "2. task"], chunks) == 1.0


def test_nested_hierarchy_f1_no_expected_labels_is_trivially_perfect() -> None:
    assert nested_hierarchy_f1([], []) == 1.0


def test_table_appendix_preservation_covers_expected_blocks() -> None:
    case = ParserSemanticCase(
        case_id="c1",
        document_id="doc_1",
        document_type="table_appendix",
        expected_source_block_ids=["b_1_0000"],
    )
    chunks = [_task_chunk("t1", "1", "Owner A", "2026-08-15")]
    assert table_appendix_preservation(case, chunks) == 1.0


def test_table_appendix_preservation_flags_missing_blocks() -> None:
    case = ParserSemanticCase(
        case_id="c2",
        document_id="doc_1",
        document_type="table_appendix",
        expected_source_block_ids=["b_1_0000", "b_1_9999"],
    )
    chunks = [_task_chunk("t1", "1", "Owner A", "2026-08-15")]
    assert table_appendix_preservation(case, chunks) == 0.5
