"""Contract tests for bounded, scoped evidence assembly."""

from __future__ import annotations

import pytest

from mamagift_retrieval.budget import EvidenceBudget
from mamagift_retrieval.chunk import Chunk, ChunkType
from mamagift_retrieval.evidence.assembler import assemble_evidence
from mamagift_retrieval.index.entries import ScoredChunk
from mamagift_retrieval.scope import EvidenceScope

pytestmark = pytest.mark.unit


def _scope(**overrides: object) -> EvidenceScope:
    values: dict[str, object] = {
        "family_id": "family-1",
        "document_id": "document-1",
        "document_version": 2,
        "parse_run_id": "parse-2",
    }
    values.update(overrides)
    return EvidenceScope(**values)


def _candidate(
    chunk_id: str,
    text: str,
    *,
    document_id: str = "document-1",
    document_version: int | None = 2,
    parse_run_id: str = "parse-2",
    pages: list[int] | None = None,
    blocks: list[str] | None = None,
    section: list[str] | None = None,
) -> ScoredChunk:
    chunk = Chunk(
        chunk_id=chunk_id,
        document_id=document_id,
        parse_run_id=parse_run_id,
        document_version=document_version,
        section_path=section or ["Chapter 1", "Article 2"],
        chunk_type=ChunkType.PARAGRAPH,
        text=text,
        source_block_ids=blocks or [f"block-{chunk_id}"],
        source_page_numbers=pages or [3],
    )
    return ScoredChunk(chunk=chunk, score=1.0, rank=1, retriever="reranked")


def _budget(selected: int) -> EvidenceBudget:
    return EvidenceBudget(
        selected_document_chars=selected,
        conversation_short_term_chars=0,
        user_long_term_memory_chars=0,
        episodic_memory_chars=0,
        archive_semantic_chars=0,
    )


def test_citation_ids_are_ordered_unique_and_stable() -> None:
    candidates = [_candidate("chunk-a", "A"), _candidate("chunk-b", "BB")]

    first = assemble_evidence(candidates, scope=_scope(), budget=_budget(10), query_id="query-1")
    second = assemble_evidence(candidates, scope=_scope(), budget=_budget(10), query_id="query-1")

    assert [item.citation_id for item in first.evidence] == ["c1", "c2"]
    assert len({item.citation_id for item in first.evidence}) == len(first.evidence)
    assert first == second


def test_duplicate_chunks_are_rejected_before_citation_assignment() -> None:
    with pytest.raises(ValueError, match="duplicate evidence chunk_id"):
        assemble_evidence(
            [_candidate("chunk-a", "A"), _candidate("chunk-a", "A")],
            scope=_scope(),
            budget=_budget(10),
            query_id="query-1",
        )


def test_budget_caps_total_size_and_accounts_offered_vs_used() -> None:
    result = assemble_evidence(
        [_candidate("chunk-a", "A" * 8), _candidate("chunk-b", "B" * 8)],
        scope=_scope(),
        budget=_budget(10),
        query_id="query-1",
    )

    selected = next(
        item for item in result.budget.categories if item.category == "selected_document"
    )
    assert sum(len(item.text) for item in result.evidence) == 10
    assert result.budget.total_used_chars() == 10
    assert selected.offered_chars == 16
    assert selected.used_chars == 10
    assert selected.truncated is True


def test_truncation_is_reported_and_keeps_candidate_provenance() -> None:
    result = assemble_evidence(
        [_candidate("chunk-a", "abcdefghij")],
        scope=_scope(),
        budget=_budget(4),
        query_id="query-1",
    )

    assert result.evidence[0].text == "abcd"
    assert result.evidence[0].chunk_id == "chunk-a"
    selected = next(
        item for item in result.budget.categories if item.category == "selected_document"
    )
    assert selected.offered_chars == 10
    assert selected.used_chars == 4
    assert selected.truncated is True


@pytest.mark.parametrize(
    "field,value",
    [("document_id", "other-document"), ("document_version", 1), ("parse_run_id", "parse-1")],
)
def test_candidate_outside_scope_is_rejected(field: str, value: object) -> None:
    with pytest.raises(ValueError, match="violates requested EvidenceScope"):
        assemble_evidence(
            [_candidate("chunk-a", "text", **{field: value})],
            scope=_scope(),
            budget=_budget(10),
            query_id="query-1",
        )


def test_empty_candidates_yield_empty_evidence_set() -> None:
    result = assemble_evidence([], scope=_scope(), budget=_budget(10), query_id="query-1")

    assert result.evidence == []
    assert result.scope == _scope()
    assert result.query_id == "query-1"
    selected = next(
        item for item in result.budget.categories if item.category == "selected_document"
    )
    assert selected.offered_chars == 0
    assert selected.used_chars == 0
    assert selected.truncated is False


def test_single_oversized_chunk_is_bounded_explicitly() -> None:
    result = assemble_evidence(
        [_candidate("chunk-a", "0123456789")],
        scope=_scope(),
        budget=_budget(3),
        query_id="query-1",
    )

    assert result.evidence[0].text == "012"
    assert len(result.evidence[0].text) <= 3
    selected = next(
        item for item in result.budget.categories if item.category == "selected_document"
    )
    assert selected.truncated is True


def test_provenance_round_trips_exactly() -> None:
    result = assemble_evidence(
        [
            _candidate(
                "chunk-a",
                "text",
                pages=[7, 8],
                blocks=["block-7", "block-8"],
                section=["Part II", "Section 4"],
            )
        ],
        scope=_scope(),
        budget=_budget(10),
        query_id="query-1",
    )

    evidence = result.evidence[0]
    assert evidence.document_id == "document-1"
    assert evidence.parse_run_id == "parse-2"
    assert evidence.document_version == 2
    assert evidence.page_numbers == [7, 8]
    assert evidence.source_block_ids == ["block-7", "block-8"]
    assert evidence.section_path == ["Part II", "Section 4"]


def test_unversioned_candidate_is_rejected_before_evidence_creation() -> None:
    with pytest.raises(ValueError, match="no document_version provenance"):
        assemble_evidence(
            [_candidate("chunk-a", "text", document_version=None)],
            scope=_scope(document_version=None),
            budget=_budget(10),
            query_id="query-1",
        )
