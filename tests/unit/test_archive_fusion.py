"""Unit tests for archive-scoped Reciprocal Rank Fusion (Phase 5 / Task C2)."""

from __future__ import annotations

import math

import pytest

from mamagift_retrieval.archive.protocol import AUTHORITATIVE_FAMILY_ID
from mamagift_retrieval.chunk import Chunk, ChunkType
from mamagift_retrieval.scope import EvidenceScope
from mamagift_retrieval.search.fusion import (
    RRF_K,
    archive_reciprocal_rank_fusion,
    reciprocal_rank_fusion,
)
from mamagift_retrieval.search.types import ScoredChunk


def _archive_scope(
    *,
    family_id: str = AUTHORITATIVE_FAMILY_ID,
    user_id: str | None = None,
    thread_id: str | None = None,
) -> EvidenceScope:
    return EvidenceScope(
        family_id=family_id,
        user_id=user_id,
        thread_id=thread_id,
        archive_scope=True,
    )


def _single_doc_scope(
    *,
    family_id: str = AUTHORITATIVE_FAMILY_ID,
    document_id: str = "doc_1",
    document_version: int = 1,
    parse_run_id: str = "prun_1",
) -> EvidenceScope:
    return EvidenceScope(
        family_id=family_id,
        document_id=document_id,
        document_version=document_version,
        parse_run_id=parse_run_id,
        archive_scope=False,
    )


def _chunk(
    chunk_id: str,
    *,
    document_id: str = "doc_1",
    document_version: int = 1,
    parse_run_id: str = "prun_1",
    document_type: str | None = "Thông tư",
    document_number: str | None = "01/2026/TT-BGDĐT",
) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        document_id=document_id,
        document_version=document_version,
        parse_run_id=parse_run_id,
        document_type=document_type,
        document_number=document_number,
        section_path=["Điều 1"],
        chunk_type=ChunkType.LEGAL_ARTICLE,
        text=f"Nội dung {chunk_id} từ {document_id}",
        source_block_ids=[f"block_{chunk_id}"],
        source_page_numbers=[1],
    )


def _scored(
    chunk_id: str,
    rank: int,
    *,
    score: float = 0.0,
    retriever: str = "lexical",
    document_id: str = "doc_1",
    document_version: int = 1,
    parse_run_id: str = "prun_1",
) -> ScoredChunk:
    return ScoredChunk(
        chunk=_chunk(
            chunk_id,
            document_id=document_id,
            document_version=document_version,
            parse_run_id=parse_run_id,
        ),
        score=score,
        rank=rank,
        retriever=retriever,  # type: ignore[arg-type]
    )


# Case 1: Multi-document candidates succeed in archive RRF but fail in single-doc RRF.
def test_multi_document_fusion_succeeds_in_archive_and_fails_in_single_doc() -> None:
    lexical = [
        _scored("c1", 1, document_id="doc_1", parse_run_id="prun_1"),
        _scored("c2", 2, document_id="doc_2", parse_run_id="prun_2"),
    ]
    dense = [
        _scored("c3", 1, retriever="dense", document_id="doc_3", parse_run_id="prun_3"),
        _scored("c1", 2, retriever="dense", document_id="doc_1", parse_run_id="prun_1"),
    ]

    # Archive fusion succeeds and returns all 3 distinct documents' chunks
    archive_results = archive_reciprocal_rank_fusion([lexical, dense], _archive_scope())
    returned_doc_ids = {r.chunk.document_id for r in archive_results}
    assert returned_doc_ids == {"doc_1", "doc_2", "doc_3"}
    assert [r.chunk.chunk_id for r in archive_results] == ["c1", "c3", "c2"]
    assert [r.rank for r in archive_results] == [1, 2, 3]
    assert all(r.retriever == "fused" for r in archive_results)

    # Single-document reciprocal_rank_fusion raises on the exact same multi-doc input
    # (whether passed a single-doc scope or an archive scope)
    with pytest.raises(ValueError, match="violates fusion EvidenceScope"):
        reciprocal_rank_fusion([lexical, dense], _single_doc_scope(document_id="doc_1"))

    with pytest.raises(ValueError, match="fusion scope must not be an archive wildcard"):
        reciprocal_rank_fusion([lexical, dense], _archive_scope())


# Case 2: archive_reciprocal_rank_fusion raises for non-archive or pinned scopes.
@pytest.mark.parametrize(
    ("scope_kwargs", "error_match"),
    [
        (
            {"family_id": AUTHORITATIVE_FAMILY_ID, "archive_scope": False},
            "archive index requires an archive scope",
        ),
        (
            {"family_id": AUTHORITATIVE_FAMILY_ID, "archive_scope": True, "document_id": "doc_1"},
            "archive scope must not pin document_id",
        ),
        (
            {"family_id": AUTHORITATIVE_FAMILY_ID, "archive_scope": True, "parse_run_id": "pr_1"},
            "archive scope must not pin parse_run_id",
        ),
        (
            {"family_id": AUTHORITATIVE_FAMILY_ID, "archive_scope": True, "document_version": 2},
            "archive scope must not pin document_version",
        ),
        (
            {"family_id": "unauthoritative_family", "archive_scope": True},
            "is not authoritative",
        ),
    ],
)
def test_archive_fusion_rejects_invalid_scopes(
    scope_kwargs: dict[str, object],
    error_match: str,
) -> None:
    invalid_scope = EvidenceScope(**scope_kwargs)  # type: ignore[arg-type]
    candidates = [[_scored("c1", 1)]]
    with pytest.raises(ValueError, match=error_match):
        archive_reciprocal_rank_fusion(candidates, invalid_scope)


# Case 3: Scores are ignored, ranks decide. Hand-worked arithmetic assertion.
def test_raw_scores_ignored_rank_arithmetic_decides() -> None:
    # "c1" has top ranks (1 in lexical, 1 in dense) but terrible raw scores (0.001, -1000.0)
    # "c2" has lower ranks (2 in lexical, 3 in dense) but huge raw scores (99999.0, 88888.0)
    lexical = [
        _scored("c1", 1, score=0.001, document_id="doc_1"),
        _scored("c2", 2, score=99999.0, document_id="doc_2"),
    ]
    dense = [
        _scored("c1", 1, score=-1000.0, retriever="dense", document_id="doc_1"),
        _scored("filler", 2, score=50000.0, retriever="dense", document_id="doc_3"),
        _scored("c2", 3, score=88888.0, retriever="dense", document_id="doc_2"),
    ]

    results = archive_reciprocal_rank_fusion([lexical, dense], _archive_scope())

    # Rank-derived order wins ("c1" at rank 1, "c2" at rank 2, "filler" at rank 3)
    assert [r.chunk.chunk_id for r in results] == ["c1", "c2", "filler"]
    assert [r.rank for r in results] == [1, 2, 3]

    # Exact hand-computed scores
    expected_c1 = 1.0 / (RRF_K + 1) + 1.0 / (RRF_K + 1)
    expected_c2 = 1.0 / (RRF_K + 2) + 1.0 / (RRF_K + 3)
    expected_filler = 1.0 / (RRF_K + 2)

    assert math.isclose(results[0].score, expected_c1)
    assert math.isclose(results[1].score, expected_c2)
    assert math.isclose(results[2].score, expected_filler)


# Case 4: A chunk appearing in both lists outranks one appearing in a single list at the same rank.
def test_chunk_in_both_lists_outranks_single_list_at_same_rank() -> None:
    # "a" is rank 1 in lexical only -> score 1/(60+1) = 1/61
    # "b" is rank 2 in lexical and rank 1 in dense -> score 1/(60+2) + 1/(60+1) = 1/62 + 1/61
    lexical = [_scored("a", 1, document_id="doc_1"), _scored("b", 2, document_id="doc_2")]
    dense = [_scored("b", 1, retriever="dense", document_id="doc_2")]

    results = archive_reciprocal_rank_fusion([lexical, dense], _archive_scope())

    assert [r.chunk.chunk_id for r in results] == ["b", "a"]
    assert results[0].score > results[1].score


# Case 5: Deterministic tie-break by ascending chunk_id.
def test_deterministic_chunk_id_tie_break() -> None:
    lexical = [_scored("z_chunk", 1, document_id="doc_1")]
    dense = [_scored("a_chunk", 1, retriever="dense", document_id="doc_2")]

    order_1 = archive_reciprocal_rank_fusion([lexical, dense], _archive_scope())
    order_2 = archive_reciprocal_rank_fusion([dense, lexical], _archive_scope())

    assert [r.chunk.chunk_id for r in order_1] == ["a_chunk", "z_chunk"]
    assert [r.chunk.chunk_id for r in order_2] == ["a_chunk", "z_chunk"]
    assert order_1[0].score == order_1[1].score


# Case 6: Non-dense ranks or duplicate chunk_id within one list raise ValueError.
def test_non_dense_ranks_raise_value_error() -> None:
    with pytest.raises(ValueError, match="dense 1-based ranks"):
        archive_reciprocal_rank_fusion(
            [[_scored("a", 1), _scored("b", 3)]],
            _archive_scope(),
        )


def test_duplicate_chunk_id_within_list_raises_value_error() -> None:
    with pytest.raises(ValueError, match="duplicate chunk_id"):
        archive_reciprocal_rank_fusion(
            [[_scored("a", 1), _scored("a", 2)]],
            _archive_scope(),
        )


# Case 7: allowed_documents restricts candidate documents; offending chunk raises ValueError.
def test_allowed_documents_rejects_disallowed_doc_and_succeeds_when_allowed() -> None:
    candidates = [
        [
            _scored("c1", 1, document_id="doc_allowed"),
            _scored("c2", 2, document_id="doc_forbidden"),
        ]
    ]

    # When allowed_documents is provided, document not in allowed_documents raises ValueError
    # naming both chunk and document
    with pytest.raises(
        ValueError, match="chunk 'c2' from document 'doc_forbidden' is not in allowed_documents"
    ):
        archive_reciprocal_rank_fusion(
            candidates,
            _archive_scope(),
            allowed_documents={"doc_allowed"},
        )

    # When allowed_documents contains all candidate documents, it succeeds
    allowed_results = archive_reciprocal_rank_fusion(
        candidates,
        _archive_scope(),
        allowed_documents={"doc_allowed", "doc_forbidden"},
    )
    assert [r.chunk.chunk_id for r in allowed_results] == ["c1", "c2"]

    # Without allowed_documents parameter (None), it also succeeds
    unfiltered_results = archive_reciprocal_rank_fusion(
        candidates,
        _archive_scope(),
        allowed_documents=None,
    )
    assert [r.chunk.chunk_id for r in unfiltered_results] == ["c1", "c2"]


# Case 8: Empty inputs return [] without requiring scope.
def test_empty_inputs_return_empty_list_without_requiring_scope() -> None:
    assert archive_reciprocal_rank_fusion([]) == []
    assert archive_reciprocal_rank_fusion([[]]) == []
    assert archive_reciprocal_rank_fusion([], scope=None) == []
    assert archive_reciprocal_rank_fusion([[]], scope=None) == []
    assert archive_reciprocal_rank_fusion([[], []], scope=None) == []

    # Non-empty input requires scope
    with pytest.raises(ValueError, match="scope is required"):
        archive_reciprocal_rank_fusion([[_scored("c1", 1)]], scope=None)
