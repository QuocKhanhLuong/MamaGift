"""Adversarial contract tests for Phase 4 D2 evidence expansion."""

from __future__ import annotations

import pytest

from mamagift_retrieval.chunk import Chunk, ChunkType
from mamagift_retrieval.evidence import MAX_ANCESTOR_DEPTH, expand_evidence
from mamagift_retrieval.scope import EvidenceScope
from mamagift_retrieval.search.types import ScoredChunk


def _scope(
    *,
    document_id: str = "plan-1",
    document_version: int | None = 2,
    parse_run_id: str = "run-2",
) -> EvidenceScope:
    return EvidenceScope(
        family_id="family-1",
        document_id=document_id,
        document_version=document_version,
        parse_run_id=parse_run_id,
    )


def _chunk(
    chunk_id: str,
    *,
    parent_chunk_id: str | None = None,
    document_id: str = "plan-1",
    document_version: int | None = 2,
    parse_run_id: str = "run-2",
    chunk_type: ChunkType = ChunkType.PARAGRAPH,
    text: str | None = None,
    metadata: dict[str, str | None] | None = None,
) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        parent_chunk_id=parent_chunk_id,
        document_id=document_id,
        document_version=document_version,
        parse_run_id=parse_run_id,
        chunk_type=chunk_type,
        text=text or chunk_id,
        source_block_ids=[f"block-{chunk_id}"],
        source_page_numbers=[1],
        metadata=metadata or {},
    )


def _scored(chunk: Chunk, *, rank: int = 1) -> ScoredChunk:
    return ScoredChunk(chunk=chunk, score=1.0 / rank, rank=rank, retriever="reranked")


def test_plan_expansion_is_task_local_in_both_directions() -> None:
    section = _chunk(
        "section",
        parent_chunk_id=None,
        chunk_type=ChunkType.PLAN_SECTION,
        text="II. Nội dung thực hiện",
    )
    task_a = _chunk(
        "task-a",
        parent_chunk_id=section.chunk_id,
        chunk_type=ChunkType.PLAN_TASK,
        text="Task A",
        metadata={"owner": "owner A", "deadline": "deadline A"},
    )
    task_b = _chunk(
        "task-b",
        parent_chunk_id=section.chunk_id,
        chunk_type=ChunkType.PLAN_TASK,
        text="Task B",
        metadata={"owner": "owner B", "deadline": "deadline B"},
    )
    content_a = _chunk("content-a", parent_chunk_id=task_a.chunk_id, text="details A")
    content_b = _chunk("content-b", parent_chunk_id=task_b.chunk_id, text="details B")
    tree = [section, task_a, task_b, content_a, content_b]

    expanded_a = expand_evidence([_scored(content_a)], scope=_scope(), chunk_tree=tree)
    expanded_b = expand_evidence([_scored(content_b)], scope=_scope(), chunk_tree=tree)

    by_id_a = {item.chunk.chunk_id: item.chunk for item in expanded_a}
    by_id_b = {item.chunk.chunk_id: item.chunk for item in expanded_b}
    assert by_id_a["task-a"].metadata["owner"] == "owner A"
    assert by_id_a["task-a"].metadata["deadline"] == "deadline A"
    assert "task-b" not in by_id_a
    assert by_id_a["task-a"].metadata["owner"] != "owner B"
    assert by_id_a["task-a"].metadata["deadline"] != "deadline B"
    assert by_id_b["task-b"].metadata["owner"] == "owner B"
    assert by_id_b["task-b"].metadata["deadline"] == "deadline B"
    assert "task-a" not in by_id_b
    assert by_id_b["task-b"].metadata["owner"] != "owner A"
    assert by_id_b["task-b"].metadata["deadline"] != "deadline A"


def test_expansion_has_a_hard_ancestor_depth_bound() -> None:
    chunks: list[Chunk] = []
    parent_id: str | None = None
    for index in range(MAX_ANCESTOR_DEPTH + 2):
        chunk = _chunk(f"level-{index}", parent_chunk_id=parent_id)
        chunks.append(chunk)
        parent_id = chunk.chunk_id

    expanded = expand_evidence([_scored(chunks[-1])], scope=_scope(), chunk_tree=chunks)

    assert [item.chunk.chunk_id for item in expanded] == [
        f"level-{index}" for index in range(MAX_ANCESTOR_DEPTH + 1, 0, -1)
    ]


@pytest.mark.parametrize("invalid_depth", [-1, MAX_ANCESTOR_DEPTH + 1])
def test_expansion_rejects_depth_outside_hard_bound(invalid_depth: int) -> None:
    with pytest.raises(ValueError, match="max_depth"):
        expand_evidence([], scope=_scope(), max_depth=invalid_depth)


def test_expansion_honors_requested_depth() -> None:
    root = _chunk("root")
    parent = _chunk("parent", parent_chunk_id=root.chunk_id)
    child = _chunk("child", parent_chunk_id=parent.chunk_id)

    expanded = expand_evidence(
        [_scored(child)], scope=_scope(), chunk_tree=[root, parent, child], max_depth=1
    )

    assert [item.chunk.chunk_id for item in expanded] == ["child", "parent"]


def test_expansion_is_deterministic_and_nearest_ancestor_first() -> None:
    root = _chunk("root")
    parent = _chunk("parent", parent_chunk_id=root.chunk_id)
    first = _chunk("first", parent_chunk_id=parent.chunk_id)
    second = _chunk("second", parent_chunk_id=root.chunk_id)
    candidates = [_scored(first), _scored(second, rank=2)]

    first_run = expand_evidence(
        candidates, scope=_scope(), chunk_tree=[root, parent, first, second]
    )
    second_run = expand_evidence(
        candidates, scope=_scope(), chunk_tree=[root, parent, first, second]
    )

    assert first_run == second_run
    assert [item.chunk.chunk_id for item in first_run] == ["first", "parent", "root", "second"]
    assert first_run[1].score == candidates[0].score
    assert first_run[1].rank == candidates[0].rank
    assert first_run[1].retriever == candidates[0].retriever


def test_expansion_never_duplicates_candidates_or_context() -> None:
    root = _chunk("root")
    child = _chunk("child", parent_chunk_id=root.chunk_id)
    other_child = _chunk("other-child", parent_chunk_id=root.chunk_id)
    candidate = _scored(child)

    expanded = expand_evidence(
        [candidate, candidate, _scored(other_child, rank=2)],
        scope=_scope(),
        chunk_tree=[child, other_child, root, root],
    )

    assert [item.chunk.chunk_id for item in expanded] == ["child", "root", "other-child"]


def test_parent_from_another_version_or_parse_run_is_not_followed() -> None:
    stale_parent = _chunk(
        "stale-parent",
        document_version=1,
        parse_run_id="run-1",
        text="stale context",
    )
    current_child = _chunk(
        "current-child",
        parent_chunk_id=stale_parent.chunk_id,
        text="current evidence",
    )

    expanded = expand_evidence(
        [_scored(current_child)], scope=_scope(), chunk_tree=[current_child, stale_parent]
    )

    assert [item.chunk.chunk_id for item in expanded] == ["current-child"]


def test_out_of_scope_candidate_is_not_expanded() -> None:
    parent = _chunk("other-parent", document_id="other-plan")
    child = _chunk(
        "other-child",
        parent_chunk_id=parent.chunk_id,
        document_id="other-plan",
    )

    expanded = expand_evidence([_scored(child)], scope=_scope(), chunk_tree=[child, parent])

    assert [item.chunk.chunk_id for item in expanded] == ["other-child"]


def test_unpinned_scope_still_does_not_follow_parent_with_different_identity() -> None:
    stale_parent = _chunk("stale-parent", document_version=2, parse_run_id="run-current")
    current_child = _chunk(
        "current-child",
        parent_chunk_id=stale_parent.chunk_id,
        document_version=None,
        parse_run_id="run-current",
    )
    unpinned = _scope(document_version=None, parse_run_id=None)

    expanded = expand_evidence(
        [_scored(current_child)], scope=unpinned, chunk_tree=[current_child, stale_parent]
    )

    assert [item.chunk.chunk_id for item in expanded] == ["current-child"]


def test_chunk_with_no_parent_is_returned_unchanged() -> None:
    candidate = _scored(_chunk("root"))

    expanded = expand_evidence([candidate], scope=_scope(), chunk_tree=[candidate.chunk])

    assert expanded == [candidate]


def test_empty_candidates_return_empty() -> None:
    assert expand_evidence([], scope=_scope(), chunk_tree=[]) == []
