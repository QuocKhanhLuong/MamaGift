"""Provider-neutral reranking contract and shared candidate validation."""

from __future__ import annotations

from typing import Protocol

from mamagift_retrieval.search.types import ScoredChunk


class Reranker(Protocol):
    """Score and reorder one document-scoped retrieval result set."""

    @property
    def reranker_version(self) -> str: ...

    async def rerank(
        self, query: str, candidates: list[ScoredChunk], top_k: int
    ) -> list[ScoredChunk]: ...


def validate_rerank_candidates(candidates: list[ScoredChunk]) -> None:
    """Reject ambiguous or cross-scope candidate collections before reranking.

    ``Chunk`` carries document, version, and parse-run provenance but not family_id;
    consequently this seam enforces the complete provenance tuple available on each
    chunk and leaves family validation to the retrieval scope/index boundary.
    """

    chunk_ids = [candidate.chunk.chunk_id for candidate in candidates]
    if len(chunk_ids) != len(set(chunk_ids)):
        raise ValueError("rerank candidates must contain unique chunk identities")

    provenance = {
        (
            candidate.chunk.document_id,
            candidate.chunk.document_version,
            candidate.chunk.parse_run_id,
        )
        for candidate in candidates
    }
    if len(provenance) > 1:
        raise ValueError("rerank candidates must share document, version, and parse run")


__all__ = ["Reranker"]
