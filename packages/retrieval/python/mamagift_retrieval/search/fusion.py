"""Rank-only reciprocal rank fusion for scoped retrieval results."""

from __future__ import annotations

from collections.abc import Sequence

from mamagift_retrieval.archive.protocol import validate_archive_scope
from mamagift_retrieval.scope import EvidenceScope, scope_matches

from .types import ScoredChunk

# RRF's conventional fixed constant dampens the effect of lower-ranked results.
RRF_K = 60


def reciprocal_rank_fusion(
    ranked_results: Sequence[Sequence[ScoredChunk]],
    scope: EvidenceScope | None = None,
) -> list[ScoredChunk]:
    """Fuse one or more retriever result lists using ranks only.

    ``scope`` is explicit because a ``Chunk`` records document provenance but not
    its evidence-family identity.  A non-empty fusion therefore cannot safely
    infer scope from a result item.  Each input list must have dense 1-based ranks;
    its raw scores are deliberately ignored.
    """
    if not ranked_results or not any(ranked_results):
        return []

    if scope is None:
        raise ValueError("scope is required when fusing non-empty retrieval results")
    _validate_fusion_scope(scope)

    for result_list in ranked_results:
        _validate_result_list(result_list, scope)

    return _fuse_by_rank(ranked_results)


def archive_reciprocal_rank_fusion(
    ranked_results: Sequence[Sequence[ScoredChunk]],
    scope: EvidenceScope | None = None,
    *,
    allowed_documents: set[str] | None = None,
) -> list[ScoredChunk]:
    """Fuse one or more retriever result lists across multiple current archive documents.

    Candidates may span multiple documents, but each candidate must match the archive scope
    and (if provided) its ``chunk.document_id`` must be in ``allowed_documents``.
    Raw scores are deliberately ignored; only ranks contribute.
    """
    if not ranked_results or not any(ranked_results):
        return []

    if scope is None:
        raise ValueError("scope is required when fusing non-empty retrieval results")
    validate_archive_scope(scope)

    for result_list in ranked_results:
        _validate_result_list(result_list, scope, allowed_documents=allowed_documents)

    return _fuse_by_rank(ranked_results)


def _fuse_by_rank(
    ranked_results: Sequence[Sequence[ScoredChunk]],
) -> list[ScoredChunk]:
    """Rank-accumulation and ordering maths shared by both fusion entry points."""
    fused_scores: dict[str, float] = {}
    chunks: dict[str, ScoredChunk] = {}

    for result_list in ranked_results:
        for result in result_list:
            chunk_id = result.chunk.chunk_id
            # Only rank contributes at the fusion boundary; result.score is never read.
            fused_scores[chunk_id] = fused_scores.get(chunk_id, 0.0) + 1.0 / (RRF_K + result.rank)
            chunks.setdefault(chunk_id, result)

    ordered_ids = sorted(fused_scores, key=lambda chunk_id: (-fused_scores[chunk_id], chunk_id))
    return [
        ScoredChunk(
            chunk=chunks[chunk_id].chunk,
            score=fused_scores[chunk_id],
            rank=rank,
            retriever="fused",
        )
        for rank, chunk_id in enumerate(ordered_ids, start=1)
    ]


def _validate_fusion_scope(scope: EvidenceScope) -> None:
    """Require the exact single-document scope that fusion is allowed to combine."""
    if scope.archive_scope:
        raise ValueError("fusion scope must not be an archive wildcard")
    if scope.document_id is None:
        raise ValueError("fusion scope must specify document_id")
    if scope.document_version is None:
        raise ValueError("fusion scope must specify document_version")
    if scope.parse_run_id is None:
        raise ValueError("fusion scope must specify parse_run_id")


def _validate_result_list(
    result_list: Sequence[ScoredChunk],
    scope: EvidenceScope,
    *,
    allowed_documents: set[str] | None = None,
) -> None:
    """Validate dense ranks, unique membership, and full chunk provenance."""
    seen_ids: set[str] = set()
    for expected_rank, result in enumerate(result_list, start=1):
        if result.rank != expected_rank:
            raise ValueError(
                "each retriever result list must have dense 1-based ranks; "
                f"expected {expected_rank}, got {result.rank}"
            )

        chunk_id = result.chunk.chunk_id
        if chunk_id in seen_ids:
            raise ValueError(f"duplicate chunk_id {chunk_id!r} in one retriever result list")
        seen_ids.add(chunk_id)

        if allowed_documents is not None and result.chunk.document_id not in allowed_documents:
            raise ValueError(
                f"chunk {chunk_id!r} from document {result.chunk.document_id!r} "
                "is not in allowed_documents"
            )

        candidate_scope = EvidenceScope(
            family_id=scope.family_id,
            document_id=result.chunk.document_id,
            document_version=result.chunk.document_version,
            parse_run_id=result.chunk.parse_run_id,
            user_id=scope.user_id,
            thread_id=scope.thread_id,
        )
        if not scope_matches(candidate_scope, scope):
            raise ValueError(
                f"chunk {chunk_id!r} violates fusion EvidenceScope "
                f"(document={result.chunk.document_id!r}, "
                f"version={result.chunk.document_version!r}, "
                f"parse_run={result.chunk.parse_run_id!r})"
            )


__all__ = [
    "RRF_K",
    "archive_reciprocal_rank_fusion",
    "reciprocal_rank_fusion",
]
