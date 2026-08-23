"""Dense retrieval implementation for single-document RAG (Phase 4 / Task C2).

This module embeds search queries with an `EmbeddingProvider` and searches
a single document version via `DocumentIndex.search_dense` exact brute-force cosine.

Key invariants:
- Scope filtering is enforced through `EvidenceScope` passed directly to the index.
- Queries are embedded using `embed_query`, never `embed_documents`.
- Provider `embedding_version` must match the indexed chunks' `embedding_version`;
  mismatches raise `EmbeddingVersionMismatchError`.
- Results are returned as `ScoredChunk` with `retriever="dense"` and 1-based dense `rank`.
- Ties in cosine similarity are broken deterministically by `chunk_id` ascending.
"""

from __future__ import annotations

from mamagift_retrieval.index.protocol import DocumentIndex
from mamagift_retrieval.providers.embedding import EmbeddingProvider
from mamagift_retrieval.scope import EvidenceScope, scope_matches

from .types import ScoredChunk


class EmbeddingVersionMismatchError(ValueError):
    """Raised when provider's embedding_version differs from indexed rows."""

    def __init__(self, provider_version: str, index_version: str) -> None:
        self.provider_version = provider_version
        self.index_version = index_version
        super().__init__(
            f"Embedding version mismatch: provider has {provider_version!r}, "
            f"but indexed document has {index_version!r}"
        )


class DenseRetriever:
    """Dense retriever that searches scoped document chunks via cosine similarity."""

    def __init__(
        self,
        index: DocumentIndex,
        embedding_provider: EmbeddingProvider,
    ) -> None:
        self._index = index
        self._embedding_provider = embedding_provider

    @property
    def index(self) -> DocumentIndex:
        """The underlying DocumentIndex instance."""
        return self._index

    @property
    def embedding_provider(self) -> EmbeddingProvider:
        """The underlying EmbeddingProvider instance."""
        return self._embedding_provider

    async def search(
        self,
        query: str,
        scope: EvidenceScope,
        top_k: int = 10,
    ) -> list[ScoredChunk]:
        """Search chunks in the scoped document version using dense embedding cosine similarity.

        Args:
            query: The user search query string.
            scope: The strict EvidenceScope identifying document_id, parse_run_id, etc.
            top_k: Maximum number of top hits to return (must be > 0).

        Returns:
            A list of `ScoredChunk` instances ranked 1-based in descending score order.
            Ties in score are broken deterministically by `chunk_id` ascending.

        Raises:
            ValueError: If `top_k <= 0`, `scope.document_id` is missing, or returned
                chunk provenance violates `scope`.
            EmbeddingVersionMismatchError: If the provider's `embedding_version` does
                not match the indexed document's `embedding_version`.
        """
        if top_k <= 0:
            raise ValueError(f"top_k must be a positive integer, got {top_k}")
        if not scope.document_id:
            raise ValueError("scope must specify document_id")

        if not query or not query.strip():
            return []

        stats = self._index.stats(scope)
        if stats.embedded_chunks == 0:
            return []

        if (
            stats.embedding_version is not None
            and stats.embedding_version != self._embedding_provider.embedding_version
        ):
            raise EmbeddingVersionMismatchError(
                provider_version=self._embedding_provider.embedding_version,
                index_version=stats.embedding_version,
            )

        embedding_result = await self._embedding_provider.embed_query(query)
        if embedding_result.embedding_version != self._embedding_provider.embedding_version:
            raise EmbeddingVersionMismatchError(
                provider_version=self._embedding_provider.embedding_version,
                index_version=embedding_result.embedding_version,
            )

        if not embedding_result.vectors or not embedding_result.vectors[0]:
            return []

        query_vector = embedding_result.vectors[0]

        raw_hits = self._index.search_dense(
            scope=scope,
            query_vector=query_vector,
            top_k=top_k,
            embedding_version=self._embedding_provider.embedding_version,
        )

        results: list[ScoredChunk] = []
        for idx, hit in enumerate(raw_hits):
            hit_scope = EvidenceScope(
                family_id=scope.family_id,
                document_id=hit.chunk.document_id,
                document_version=hit.chunk.document_version,
                parse_run_id=hit.chunk.parse_run_id,
                user_id=scope.user_id,
                thread_id=scope.thread_id,
            )
            if not scope_matches(hit_scope, scope):
                raise ValueError(
                    f"retrieved chunk {hit.chunk.chunk_id!r} violates requested EvidenceScope"
                )

            results.append(
                ScoredChunk(
                    chunk=hit.chunk,
                    score=float(hit.score),
                    rank=idx + 1,
                    retriever="dense",
                )
            )

        return results
