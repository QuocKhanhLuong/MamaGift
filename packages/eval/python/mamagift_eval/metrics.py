"""Deterministic per-document-type evaluation metric hooks (Phase 3.5).

Metrics here score parser/chunking structure against a `ParserSemanticCase`, never
model-generated prose (CI must not depend on nondeterministic model quality). Plan
(`ke_hoach`) metrics are the ones the /goal calls out explicitly: task recall, task
order accuracy, task-owner and task-deadline association accuracy, deadline
accuracy, nested-hierarchy F1 and table/appendix preservation.

Provenance Isolation Decision:
Any input item whose provenance (document_id, document_version, parse_run_id, or
document_type) does not match the target case identity is excluded from scoring and
never credited. If an input contains items with mixed provenance and no target
identity was provided to disambiguate, an explicit ValueError is raised rather than
silently inferring identity from the first input item.
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


def _resolve_identity(
    case: ParserSemanticCase | None,
    document_id: str | None,
    document_version: int | None,
    parse_run_id: str | None,
    document_type: str | None,
    default_document_type: str | None = None,
) -> tuple[str | None, int | None, str | None, str | None]:
    target_doc_id = document_id if document_id is not None else (case.document_id if case else None)
    target_doc_type = (
        document_type
        if document_type is not None
        else (case.document_type if case else default_document_type)
    )
    return target_doc_id, document_version, parse_run_id, target_doc_type


def _plan_task_chunks(
    chunks: list[Chunk],
    *,
    case: ParserSemanticCase | None = None,
    document_id: str | None = None,
    document_version: int | None = None,
    parse_run_id: str | None = None,
    document_type: str | None = "ke_hoach",
) -> list[Chunk]:
    """Filter and isolate `ke_hoach` plan task chunks.

    Rejects chunks that:
    - are not `ChunkType.PLAN_TASK`
    - have missing or invalid ordinal metadata
    - do not match the target provenance identity (document_id, document_version,
      parse_run_id, document_type)

    Raises `ValueError` if:
    - the input contains mixed provenance items without an explicit target identity
    - multiple actual chunks declare the same task ordinal within the isolated set
    """
    target_doc_id, target_version, target_run_id, target_doc_type = _resolve_identity(
        case,
        document_id,
        document_version,
        parse_run_id,
        document_type,
        default_document_type="ke_hoach",
    )

    candidates: list[Chunk] = []
    for chunk in chunks:
        if chunk.chunk_type != ChunkType.PLAN_TASK:
            continue
        if target_doc_type is not None and chunk.document_type != target_doc_type:
            continue
        ordinal = chunk.metadata.get("ordinal")
        if not isinstance(ordinal, str) or not ordinal:
            continue
        candidates.append(chunk)

    if not candidates:
        return []

    # Enforce strict provenance identity (document_id + version + parse_run_id + document_type)
    if target_doc_id is None:
        doc_ids = {c.document_id for c in candidates}
        if len(doc_ids) > 1:
            raise ValueError(
                f"mixed document_id in actual chunks {sorted(doc_ids)}; specify document_id or case"
            )
        target_doc_id = next(iter(doc_ids))

    if target_version is None:
        versions = {
            c.document_version
            for c in candidates
            if c.document_id == target_doc_id and c.document_version is not None
        }
        if len(versions) > 1:
            raise ValueError(
                f"mixed document_version in actual chunks {sorted(versions)}; "
                "specify document_version"
            )

    if target_run_id is None:
        matching_runs = {
            c.parse_run_id
            for c in candidates
            if c.document_id == target_doc_id
            and (target_version is None or c.document_version == target_version)
        }
        if len(matching_runs) > 1:
            raise ValueError(
                f"mixed parse_run_id in actual chunks {sorted(matching_runs)}; specify parse_run_id"
            )

    isolated: list[Chunk] = [
        c
        for c in candidates
        if c.document_id == target_doc_id
        and (target_version is None or c.document_version == target_version)
        and (target_run_id is None or c.parse_run_id == target_run_id)
        and (target_doc_type is None or c.document_type == target_doc_type)
    ]

    # Validate ordinal uniqueness within the isolated chunk set
    seen_ordinals: set[str] = set()
    for chunk in isolated:
        ord_val = chunk.metadata["ordinal"]
        if ord_val in seen_ordinals:
            raise ValueError(f"duplicate task ordinal {ord_val!r} in actual chunks")
        seen_ordinals.add(ord_val)

    return isolated


def _isolated_hierarchy_chunks(
    chunks: list[Chunk],
    *,
    case: ParserSemanticCase | None = None,
    document_id: str | None = None,
    document_version: int | None = None,
    parse_run_id: str | None = None,
    document_type: str | None = None,
) -> list[Chunk]:
    """Filter chunks to match the target document provenance identity."""
    if not chunks:
        return []

    target_doc_id, target_version, target_run_id, target_doc_type = _resolve_identity(
        case,
        document_id,
        document_version,
        parse_run_id,
        document_type,
        default_document_type=None,
    )

    if target_doc_id is None:
        doc_ids = {c.document_id for c in chunks}
        if len(doc_ids) > 1:
            raise ValueError(
                f"mixed document_id in actual chunks {sorted(doc_ids)}; specify document_id or case"
            )
        target_doc_id = next(iter(doc_ids))

    if target_version is None:
        versions = {
            c.document_version
            for c in chunks
            if c.document_id == target_doc_id and c.document_version is not None
        }
        if len(versions) > 1:
            raise ValueError(
                f"mixed document_version in actual chunks {sorted(versions)}; "
                "specify document_version"
            )

    if target_run_id is None:
        matching_runs = {
            c.parse_run_id
            for c in chunks
            if c.document_id == target_doc_id
            and (target_version is None or c.document_version == target_version)
        }
        if len(matching_runs) > 1:
            raise ValueError(
                f"mixed parse_run_id in actual chunks {sorted(matching_runs)}; specify parse_run_id"
            )

    return [
        chunk
        for chunk in chunks
        if chunk.document_id == target_doc_id
        and (target_version is None or chunk.document_version == target_version)
        and (target_run_id is None or chunk.parse_run_id == target_run_id)
        and (target_doc_type is None or chunk.document_type == target_doc_type)
    ]


def task_recall(
    expected: list[ExpectedTaskRelation] | ParserSemanticCase,
    actual_chunks: list[Chunk],
    *,
    case: ParserSemanticCase | None = None,
    document_id: str | None = None,
    document_version: int | None = None,
    parse_run_id: str | None = None,
    document_type: str | None = "ke_hoach",
) -> float:
    """Fraction of expected tasks (by ordinal) present as a `plan_task` chunk."""
    if isinstance(expected, ParserSemanticCase):
        case = expected
        expected_tasks = case.expected_task_relations
    else:
        expected_tasks = expected

    if not expected_tasks:
        return 1.0
    _validate_expected_ordinals(expected_tasks)
    task_chunks = _plan_task_chunks(
        actual_chunks,
        case=case,
        document_id=document_id,
        document_version=document_version,
        parse_run_id=parse_run_id,
        document_type=document_type,
    )
    if not task_chunks:
        return 0.0
    actual_ordinals = {chunk.metadata["ordinal"] for chunk in task_chunks}
    found = sum(1 for item in expected_tasks if item.task_ordinal in actual_ordinals)
    return found / len(expected_tasks)


def task_order_accuracy(
    expected: list[ExpectedTaskRelation] | ParserSemanticCase,
    actual_chunks: list[Chunk],
    *,
    case: ParserSemanticCase | None = None,
    document_id: str | None = None,
    document_version: int | None = None,
    parse_run_id: str | None = None,
    document_type: str | None = "ke_hoach",
) -> float:
    """Fraction of adjacent expected-task pairs whose relative chunk order matches."""
    if isinstance(expected, ParserSemanticCase):
        case = expected
        expected_tasks = case.expected_task_relations
    else:
        expected_tasks = expected

    _validate_expected_ordinals(expected_tasks)
    pairs = list(zip(expected_tasks, expected_tasks[1:], strict=False))
    if not pairs:
        return 1.0
    task_chunks = _plan_task_chunks(
        actual_chunks,
        case=case,
        document_id=document_id,
        document_version=document_version,
        parse_run_id=parse_run_id,
        document_type=document_type,
    )
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
    expected: list[ExpectedTaskRelation] | ParserSemanticCase,
    actual_chunks: list[Chunk],
    *,
    case: ParserSemanticCase | None = None,
    document_id: str | None = None,
    document_version: int | None = None,
    parse_run_id: str | None = None,
    document_type: str | None = "ke_hoach",
) -> float:
    """Fraction of expected task owners accurately associated in actual chunks."""
    if isinstance(expected, ParserSemanticCase):
        case = expected
        expected_tasks = case.expected_task_relations
    else:
        expected_tasks = expected

    _validate_expected_ordinals(expected_tasks)
    scored = [item for item in expected_tasks if item.owner is not None]
    if not scored:
        return 1.0
    task_chunks = _plan_task_chunks(
        actual_chunks,
        case=case,
        document_id=document_id,
        document_version=document_version,
        parse_run_id=parse_run_id,
        document_type=document_type,
    )
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
    expected: list[ExpectedTaskRelation] | ParserSemanticCase,
    actual_chunks: list[Chunk],
    *,
    case: ParserSemanticCase | None = None,
    document_id: str | None = None,
    document_version: int | None = None,
    parse_run_id: str | None = None,
    document_type: str | None = "ke_hoach",
) -> float:
    """Fraction of expected task deadlines accurately associated in actual chunks."""
    if isinstance(expected, ParserSemanticCase):
        case = expected
        expected_tasks = case.expected_task_relations
    else:
        expected_tasks = expected

    _validate_expected_ordinals(expected_tasks)
    scored = [item for item in expected_tasks if item.deadline is not None]
    if not scored:
        return 1.0
    task_chunks = _plan_task_chunks(
        actual_chunks,
        case=case,
        document_id=document_id,
        document_version=document_version,
        parse_run_id=parse_run_id,
        document_type=document_type,
    )
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


def deadline_accuracy(
    expected: list[ExpectedTaskRelation] | ParserSemanticCase,
    actual_chunks: list[Chunk],
    *,
    case: ParserSemanticCase | None = None,
    document_id: str | None = None,
    document_version: int | None = None,
    parse_run_id: str | None = None,
    document_type: str | None = "ke_hoach",
) -> float:
    """The document-level deadline-value metric the /goal names separately from
    task-deadline *association*; implemented identically because a plan case's only
    source of deadline ground truth is its per-task relations."""
    return task_deadline_association_accuracy(
        expected,
        actual_chunks,
        case=case,
        document_id=document_id,
        document_version=document_version,
        parse_run_id=parse_run_id,
        document_type=document_type,
    )


def nested_hierarchy_f1(
    expected_labels: list[str] | ParserSemanticCase,
    actual_chunks: list[Chunk],
    *,
    case: ParserSemanticCase | None = None,
    document_id: str | None = None,
    document_version: int | None = None,
    parse_run_id: str | None = None,
    document_type: str | None = None,
) -> float:
    """F1 over each chunk's own heading label — the last element of its
    `section_path`, never the full ancestor chain — so a task nested three levels
    deep contributes one label, not one per ancestor it shares with its siblings."""
    if isinstance(expected_labels, ParserSemanticCase):
        case = expected_labels
        labels = case.expected_hierarchy_labels
    else:
        labels = expected_labels

    if not labels:
        return 1.0
    valid_chunks = _isolated_hierarchy_chunks(
        actual_chunks,
        case=case,
        document_id=document_id,
        document_version=document_version,
        parse_run_id=parse_run_id,
        document_type=document_type,
    )
    if not valid_chunks:
        return 0.0
    actual_labels = {chunk.section_path[-1] for chunk in valid_chunks if chunk.section_path}
    if not actual_labels:
        return 0.0
    expected_set = set(labels)
    true_positives = len(expected_set & actual_labels)
    precision = true_positives / len(actual_labels) if actual_labels else 0.0
    recall = true_positives / len(expected_set)
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def table_appendix_preservation(
    case: ParserSemanticCase,
    actual_chunks: list[Chunk],
    *,
    document_version: int | None = None,
    parse_run_id: str | None = None,
) -> float:
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
        if document_version is not None and chunk.document_version != document_version:
            continue
        if parse_run_id is not None and chunk.parse_run_id != parse_run_id:
            continue
        if expected_pages_set and not (set(chunk.source_page_numbers) & expected_pages_set):
            continue
        matching.append(chunk)

    if not matching:
        return 0.0

    if document_version is None:
        matching_versions = {c.document_version for c in matching if c.document_version is not None}
        if len(matching_versions) > 1:
            raise ValueError(
                f"mixed document_version in actual chunks {sorted(matching_versions)}; "
                "specify document_version"
            )

    # If parse_run_id was not explicitly specified, verify parse_run_id uniqueness
    if parse_run_id is None:
        matching_runs = {c.parse_run_id for c in matching}
        if len(matching_runs) > 1:
            raise ValueError(
                f"mixed parse_run_id in actual chunks {sorted(matching_runs)}; specify parse_run_id"
            )

    valid_chunks = matching

    if case.expected_source_block_ids:
        expected_blocks = set(case.expected_source_block_ids)
        covered_blocks = {block_id for chunk in valid_chunks for block_id in chunk.source_block_ids}
        return len(expected_blocks & covered_blocks) / len(expected_blocks)

    # Fallback to page-level coverage when only expected_source_page_numbers is specified
    covered_pages = {p for chunk in valid_chunks for p in chunk.source_page_numbers}
    return len(expected_pages_set & covered_pages) / len(expected_pages_set)
