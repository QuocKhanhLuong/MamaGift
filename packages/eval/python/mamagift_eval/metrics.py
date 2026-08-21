"""Deterministic per-document-type evaluation metric hooks (Phase 3.5).

Metrics here score parser/chunking structure against a `ParserSemanticCase`, never
model-generated prose (CI must not depend on nondeterministic model quality). Plan
(`ke_hoach`) metrics are the ones the /goal calls out explicitly: task recall, task
order accuracy, task-owner and task-deadline association accuracy, deadline
accuracy, nested-hierarchy F1 and table/appendix preservation.
"""

from __future__ import annotations

from mamagift_retrieval.chunk import Chunk, ChunkType

from .schemas import ExpectedTaskRelation, ParserSemanticCase


def _plan_task_chunks(chunks: list[Chunk]) -> list[Chunk]:
    return [chunk for chunk in chunks if chunk.chunk_type == ChunkType.PLAN_TASK]


def task_recall(expected: list[ExpectedTaskRelation], actual_chunks: list[Chunk]) -> float:
    """Fraction of expected tasks (by ordinal) present as a `plan_task` chunk."""
    if not expected:
        return 1.0
    actual_ordinals = {chunk.metadata.get("ordinal") for chunk in _plan_task_chunks(actual_chunks)}
    found = sum(1 for item in expected if item.task_ordinal in actual_ordinals)
    return found / len(expected)


def task_order_accuracy(expected: list[ExpectedTaskRelation], actual_chunks: list[Chunk]) -> float:
    """Fraction of adjacent expected-task pairs whose relative chunk order matches."""
    task_chunks = _plan_task_chunks(actual_chunks)
    position = {chunk.metadata.get("ordinal"): index for index, chunk in enumerate(task_chunks)}
    pairs = list(zip(expected, expected[1:], strict=False))
    if not pairs:
        return 1.0
    correct = 0
    for left, right in pairs:
        left_pos, right_pos = position.get(left.task_ordinal), position.get(right.task_ordinal)
        if left_pos is not None and right_pos is not None and left_pos < right_pos:
            correct += 1
    return correct / len(pairs)


def task_owner_association_accuracy(
    expected: list[ExpectedTaskRelation], actual_chunks: list[Chunk]
) -> float:
    by_ordinal = {
        chunk.metadata.get("ordinal"): chunk for chunk in _plan_task_chunks(actual_chunks)
    }
    scored = [item for item in expected if item.owner is not None]
    if not scored:
        return 1.0
    correct = sum(
        1
        for item in scored
        if by_ordinal.get(item.task_ordinal) is not None
        and by_ordinal[item.task_ordinal].metadata.get("owner") == item.owner
    )
    return correct / len(scored)


def task_deadline_association_accuracy(
    expected: list[ExpectedTaskRelation], actual_chunks: list[Chunk]
) -> float:
    by_ordinal = {
        chunk.metadata.get("ordinal"): chunk for chunk in _plan_task_chunks(actual_chunks)
    }
    scored = [item for item in expected if item.deadline is not None]
    if not scored:
        return 1.0
    correct = sum(
        1
        for item in scored
        if by_ordinal.get(item.task_ordinal) is not None
        and by_ordinal[item.task_ordinal].metadata.get("deadline") == item.deadline
    )
    return correct / len(scored)


def deadline_accuracy(expected: list[ExpectedTaskRelation], actual_chunks: list[Chunk]) -> float:
    """The document-level deadline-value metric the /goal names separately from
    task-deadline *association*; implemented identically because a plan case's only
    source of deadline ground truth is its per-task relations."""
    return task_deadline_association_accuracy(expected, actual_chunks)


def nested_hierarchy_f1(expected_labels: list[str], actual_chunks: list[Chunk]) -> float:
    """F1 over each chunk's own heading label — the last element of its
    `section_path`, never the full ancestor chain — so a task nested three levels
    deep contributes one label, not one per ancestor it shares with its siblings."""
    if not expected_labels:
        return 1.0
    actual_labels = {chunk.section_path[-1] for chunk in actual_chunks if chunk.section_path}
    expected_set = set(expected_labels)
    true_positives = len(expected_set & actual_labels)
    precision = true_positives / len(actual_labels) if actual_labels else 0.0
    recall = true_positives / len(expected_set)
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def table_appendix_preservation(case: ParserSemanticCase, actual_chunks: list[Chunk]) -> float:
    """Fraction of the case's expected source blocks that survive into some
    chunk's provenance — the basic "nothing silently dropped" preservation check
    for document types where table/appendix structure matters most."""
    if not case.expected_source_block_ids:
        return 1.0
    covered = {block_id for chunk in actual_chunks for block_id in chunk.source_block_ids}
    expected_set = set(case.expected_source_block_ids)
    return len(expected_set & covered) / len(expected_set)
