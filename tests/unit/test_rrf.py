"""Unit tests for rank-only Reciprocal Rank Fusion (Phase 4 / Task C3)."""

from __future__ import annotations

import math

import pytest

from mamagift_retrieval.chunk import Chunk, ChunkType
from mamagift_retrieval.scope import EvidenceScope
from mamagift_retrieval.search.fusion import RRF_K, reciprocal_rank_fusion
from mamagift_retrieval.search.types import ScoredChunk


def _scope() -> EvidenceScope:
    return EvidenceScope(
        family_id="family_01",
        document_id="document_01",
        document_version=2,
        parse_run_id="parse_run_02",
    )


def _chunk(
    chunk_id: str,
    *,
    document_id: str = "document_01",
    document_version: int = 2,
    parse_run_id: str = "parse_run_02",
) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        document_id=document_id,
        document_version=document_version,
        parse_run_id=parse_run_id,
        section_path=["Điều 1"],
        chunk_type=ChunkType.LEGAL_ARTICLE,
        text=f"Nội dung {chunk_id}",
        source_block_ids=[f"block_{chunk_id}"],
        source_page_numbers=[1],
    )


def _scored(
    chunk_id: str,
    rank: int,
    *,
    score: float = 0.0,
    retriever: str = "lexical",
    **chunk_kwargs: object,
) -> ScoredChunk:
    return ScoredChunk(
        chunk=_chunk(chunk_id, **chunk_kwargs),
        score=score,
        rank=rank,
        retriever=retriever,  # type: ignore[arg-type]
    )


def test_rrf_matches_hand_worked_arithmetic() -> None:
    assert RRF_K == 60
    results = reciprocal_rank_fusion(
        [
            [_scored("a", 1, score=91.0), _scored("b", 2, score=4.0)],
            [
                _scored("b", 1, score=0.2, retriever="dense"),
                _scored("filler", 2, score=17.0, retriever="dense"),
                _scored("a", 3, score=-700.0, retriever="dense"),
            ],
        ],
        _scope(),
    )

    expected_a = 1.0 / (RRF_K + 1) + 1.0 / (RRF_K + 3)
    expected_b = 1.0 / (RRF_K + 2) + 1.0 / (RRF_K + 1)
    assert [item.chunk.chunk_id for item in results][:2] == ["b", "a"]
    assert math.isclose(results[0].score, expected_b)
    assert math.isclose(results[1].score, expected_a)
    assert [item.rank for item in results] == [1, 2, 3]
    assert all(item.retriever == "fused" for item in results)


def test_high_ranked_chunk_absent_from_other_retriever_still_surfaces() -> None:
    results = reciprocal_rank_fusion(
        [
            [_scored("only_lexical", 1)],
            [_scored("dense_other", 1, retriever="dense")],
        ],
        _scope(),
    )

    assert {item.chunk.chunk_id for item in results} == {"only_lexical", "dense_other"}


def test_mid_ranked_by_both_outranks_top_ranked_by_only_one() -> None:
    results = reciprocal_rank_fusion(
        [
            [_scored("top_once", 1), _scored("mid_both", 2)],
            [
                _scored("filler", 1, retriever="dense"),
                _scored("mid_both", 2, retriever="dense"),
            ],
        ],
        _scope(),
    )

    result_ids = [item.chunk.chunk_id for item in results]
    assert result_ids.index("mid_both") < result_ids.index("top_once")
    mid = next(item for item in results if item.chunk.chunk_id == "mid_both")
    top = next(item for item in results if item.chunk.chunk_id == "top_once")
    assert mid.score > top.score


def test_raw_scores_do_not_influence_fusion() -> None:
    ranks_only = [
        [_scored("a", 1, score=0.0001), _scored("b", 2, score=0.0002)],
        [
            _scored("b", 1, score=1000000.0, retriever="dense"),
            _scored("a", 2, score=-1000000.0, retriever="dense"),
        ],
    ]
    wildly_changed_scores = [
        [_scored("a", 1, score=-999999999.0), _scored("b", 2, score=999999999.0)],
        [
            _scored("b", 1, score=-1e-12, retriever="dense"),
            _scored("a", 2, score=1e12, retriever="dense"),
        ],
    ]

    baseline = reciprocal_rank_fusion(ranks_only, _scope())
    changed = reciprocal_rank_fusion(wildly_changed_scores, _scope())
    assert [item.chunk.chunk_id for item in baseline] == [item.chunk.chunk_id for item in changed]
    assert [item.score for item in baseline] == [item.score for item in changed]


def test_ties_have_deterministic_chunk_id_tie_break() -> None:
    lexical = [_scored("z", 1)]
    dense = [_scored("a", 1, retriever="dense")]
    first = reciprocal_rank_fusion(
        [lexical, dense],
        _scope(),
    )
    repeated = reciprocal_rank_fusion(
        [dense, lexical],
        _scope(),
    )

    assert [item.chunk.chunk_id for item in first] == ["a", "z"]
    assert [item.chunk.chunk_id for item in first] == [item.chunk.chunk_id for item in repeated]


def test_empty_single_and_partly_empty_inputs() -> None:
    assert reciprocal_rank_fusion([]) == []
    assert reciprocal_rank_fusion([[]]) == []

    single = reciprocal_rank_fusion([[_scored("single", 1, score=123.0)]], _scope())
    assert [item.chunk.chunk_id for item in single] == ["single"]
    assert math.isclose(single[0].score, 1.0 / (RRF_K + 1))

    partly_empty = reciprocal_rank_fusion(
        [[], [_scored("present", 1, retriever="dense")], []],
        _scope(),
    )
    assert [item.chunk.chunk_id for item in partly_empty] == ["present"]


@pytest.mark.parametrize(
    ("provenance_field", "provenance_value"),
    [
        ("document_id", "document_02"),
        ("document_version", 3),
        ("parse_run_id", "parse_run_03"),
    ],
)
def test_mixed_document_version_or_parse_run_is_rejected(
    provenance_field: str,
    provenance_value: object,
) -> None:
    with pytest.raises(ValueError, match="violates fusion EvidenceScope"):
        reciprocal_rank_fusion(
            [
                [_scored("valid", 1)],
                [
                    _scored(
                        "invalid",
                        1,
                        retriever="dense",
                        **{provenance_field: provenance_value},
                    )
                ],
            ],
            _scope(),
        )


def test_scope_is_required_instead_of_inferred_from_first_chunk() -> None:
    with pytest.raises(ValueError, match="scope is required"):
        reciprocal_rank_fusion([[_scored("chunk", 1)]])


def test_non_dense_ranks_are_rejected() -> None:
    with pytest.raises(ValueError, match="dense 1-based ranks"):
        reciprocal_rank_fusion(
            [[_scored("a", 2)]],
            _scope(),
        )


def test_duplicate_chunk_within_one_retriever_is_rejected() -> None:
    assert reciprocal_rank_fusion([[_scored("unique", 1)]], _scope())
    with pytest.raises(ValueError, match="duplicate chunk_id"):
        reciprocal_rank_fusion(
            [[_scored("duplicate", 1), _scored("duplicate", 2)]],
            _scope(),
        )
