"""Protocol interface for single-document version-keyed DocumentIndex."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from mamagift_retrieval.scope import EvidenceScope

from .entries import IndexEntry, IndexStats, ScoredChunk


# Phase 4 is deliberately single-family. Supporting more families requires a real
# tenancy source; no authoritative family_id exists in the current documents/auth
# model, and multi-family support is a Phase 5+ concern. Keep this explicit rather
# than allowing a caller to manufacture family identity through an EvidenceScope.
AUTHORITATIVE_FAMILY_ID = "mamagift"


@runtime_checkable
class DocumentIndex(Protocol):
    """Version-isolated, single-document index contract.

    Every method takes an EvidenceScope and MUST filter on it internally.
    Scope filtering is NEVER the caller's job.
    """

    def replace(self, scope: EvidenceScope, entries: list[IndexEntry]) -> IndexStats:
        """Atomically replace all chunk rows for the specified (document_id, parse_run_id).

        Existing rows for this parse run are removed and replaced with `entries`.
        Rows for other parse runs or other documents are unaffected.
        """
        ...

    def search_dense(
        self,
        scope: EvidenceScope,
        query_vector: list[float],
        top_k: int,
    ) -> list[ScoredChunk]:
        """Perform exact brute-force cosine similarity search over scoped chunks.

        Rows with missing or stale embedding_version are excluded.
        Returns candidates ranked 1-based in descending score order.
        """
        ...

    def search_lexical(
        self,
        scope: EvidenceScope,
        query: str,
        top_k: int,
    ) -> list[ScoredChunk]:
        """Perform lexical term-overlap search over chunks in the scoped document version.

        Returns candidates ranked 1-based in descending score order.
        """
        ...

    def drop(self, scope: EvidenceScope) -> int:
        """Delete all chunks for the scoped document version / parse run.

        Returns the number of deleted rows.
        """
        ...

    def stats(self, scope: EvidenceScope) -> IndexStats:
        """Return indexing statistics for the scoped document version / parse run."""
        ...
