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


def _validate_expected_ordinals(expected: list[ExpectedTaskRelation]) -> None:
    seen: set[str] = set()
    for item in expected:
        if item.task_ordinal in seen:
            raise ValueError(f"duplicate expected task_ordinal {item.task_ordinal!r}")
        seen.add(item.task_ordinal)


def _plan_task_chunks(chunks: list[Chunk]) -> list[Chunk]:
    """Filter and isolate `ke_hoach` plan task chunks.

    Rejects chunks that:
    - are not `ChunkType.PLAN_TASK`
    - have `document_type != 'ke_hoach'`
    - have missing or invalid ordinal metadata
    - belong to a different document, version, or parse run than the primary chunk tree

    Raises `ValueError` if multiple actual chunks declare the same task ordinal.
    """
    candidates: list[Chunk] = []
    for chunk in chunks:
        if chunk.chunk_type != ChunkType.PLAN_TASK:
            continue
        if chunk.document_type != "ke_hoach":
            continue
        ordinal = chunk.metadata.get("ordinal")
        if not isinstance(ordinal, str) or not ordinal:
            continue
        candidates.append(chunk)

    if not candidates:
        return []

    # Enforce strict provenance identity (document_id + version + parse_run_id + document_type)
    primary_identity = (
        candidates[0].document_id,
        candidates[0].document_version,
        candidates[0].parse_run_id,
        candidates[0].document_type,
    )
    isolated = [
        c
        for c in candidates
        if (
            c.document_id,
            c.document_version,
            c.parse_run_id,
            c.document_type,
        )
        == primary_identity
    ]

    # Validate ordinal uniqueness within the isolated chunk set
    seen_ordinals: set[str] = set()
    for chunk in isolated:
        ord_val = chunk.metadata["ordinal"]
        if ord_val in seen_ordinals:
            raise ValueError(f"duplicate task ordinal {ord_val!r} in actual chunks")
        seen_ordinals.add(ord_val)

    return isolated


def _isolated_hierarchy_chunks(chunks: list[Chunk]) -> list[Chunk]:
    """Filter chunks to a single consistent document provenance identity."""
    if not chunks:
        return []
    primary_identity = (
        chunks[0].document_id,
        chunks[0].document_version,
        chunks[0].parse_run_id,
        chunks[0].document_type,
    )
    return [
        chunk
        for chunk in chunks
        if (
            chunk.document_id,
            chunk.document_version,
            chunk.parse_run_id,
            chunk.document_type,
        )
        == primary_identity
    ]


def task_recall(expected: list[ExpectedTaskRelation], actual_chunks: list[Chunk]) -> float:
    """Fraction of expected tasks (by ordinal) present as a `plan_task` chunk."""
    if not expected:
        return 1.0
    _validate_expected_ordinals(expected)
    task_chunks = _plan_task_chunks(actual_chunks)
    if not task_chunks:
        return 0.0
    actual_ordinals = {chunk.metadata["ordinal"] for chunk in task_chunks}
    found = sum(1 for item in expected if item.task_ordinal in actual_ordinals)
    return found / len(expected)


def task_order_accuracy(expected: list[ExpectedTaskRelation], actual_chunks: list[Chunk]) -> float:
    """Fraction of adjacent expected-task pairs whose relative chunk order matches."""
    _validate_expected_ordinals(expected)
    pairs = list(zip(expected, expected[1:], strict=False))
    if not pairs:
        return 1.0
    task_chunks = _plan_task_chunks(actual_chunks)
    if not task_chunks:
        return 0.0
    position = {chunk.metadata["ordinal"]: index for index, chunk in enumerate(task_chunks)}
    correct = 0
    for left, right in pairs:
        left_pos, right_pos = position.get(left.task_ordinal), position.get(right.task_ordinal)
        if left_pos is not None and right_pos is not None and left_pos < right_pos:
            correct += 1
    return correct / len(pairs)


def task_owner_association_accuracy(
    expected: list[ExpectedTaskRelation], actual_chunks: list[Chunk]
) -> float:
    _validate_expected_ordinals(expected)
    scored = [item for item in expected if item.owner is not None]
    if not scored:
        return 1.0
    task_chunks = _plan_task_chunks(actual_chunks)
    if not task_chunks:
        return 0.0
    by_ordinal = {chunk.metadata["ordinal"]: chunk for chunk in task_chunks}
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
    _validate_expected_ordinals(expected)
    scored = [item for item in expected if item.deadline is not None]
    if not scored:
        return 1.0
    task_chunks = _plan_task_chunks(actual_chunks)
    if not task_chunks:
        return 0.0
    by_ordinal = {chunk.metadata["ordinal"]: chunk for chunk in task_chunks}
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
    valid_chunks = _isolated_hierarchy_chunks(actual_chunks)
    if not valid_chunks:
        return 0.0
    actual_labels = {chunk.section_path[-1] for chunk in valid_chunks if chunk.section_path}
    if not actual_labels:
        return 0.0
    expected_set = set(expected_labels)
    true_positives = len(expected_set & actual_labels)
    precision = true_positives / len(actual_labels) if actual_labels else 0.0
    recall = true_positives / len(expected_set)
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def table_appendix_preservation(case: ParserSemanticCase, actual_chunks: list[Chunk]) -> float:
    """Fraction of the case's expected source blocks/pages that survive into some
    chunk's provenance — the basic "nothing silently dropped" preservation check
    for document types where table/appendix structure matters most."""
    if not case.expected_source_block_ids and not case.expected_source_page_numbers:
        return 1.0

    # Filter candidate chunks matching case document identity and expected pages
    expected_pages_set = set(case.expected_source_page_numbers)
    matching: list[Chunk] = []
    for chunk in actual_chunks:
        if chunk.document_id != case.document_id:
            continue
        if chunk.document_type != case.document_type:
            continue
        if expected_pages_set and not (set(chunk.source_page_numbers) & expected_pages_set):
            continue
        matching.append(chunk)

    if not matching:
        return 0.0

    # Enforce consistent parse-run and version isolation: all credited evidence must belong
    # to the same parse run and version
    primary_version_run = (matching[0].document_version, matching[0].parse_run_id)
    valid_chunks = [
        c for c in matching if (c.document_version, c.parse_run_id) == primary_version_run
    ]

    if case.expected_source_block_ids:
        expected_blocks = set(case.expected_source_block_ids)
        covered_blocks = {block_id for chunk in valid_chunks for block_id in chunk.source_block_ids}
        return len(expected_blocks & covered_blocks) / len(expected_blocks)

    # Fallback to page-level coverage when only expected_source_page_numbers is specified
    covered_pages = {p for chunk in valid_chunks for p in chunk.source_page_numbers}
    return len(expected_pages_set & covered_pages) / len(expected_pages_set)
