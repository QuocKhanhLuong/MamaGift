"""Archive hybrid retrieval orchestration across current documents in one family."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from mamagift_retrieval.archive.constants import (
    ARCHIVE_DENSE_TOP_K,
    ARCHIVE_LEXICAL_TOP_K,
    ARCHIVE_RERANK_TOP_K,
)
from mamagift_retrieval.archive.filters import ArchiveFilter
from mamagift_retrieval.archive.identifiers import (
    QueryIdentifiers,
    extract_query_identifiers,
    identifier_match_score,
)
from mamagift_retrieval.archive.protocol import (
    ArchiveDocumentRef,
    ArchiveIndex,
    validate_archive_scope,
)
from mamagift_retrieval.providers.embedding import EmbeddingProvider
from mamagift_retrieval.rerank.protocol import (
    Reranker,
    validate_archive_rerank_candidates,
)
from mamagift_retrieval.scope import EvidenceScope
from mamagift_retrieval.search.fusion import archive_reciprocal_rank_fusion
from mamagift_retrieval.search.types import ScoredChunk


class ArchiveEmbeddingVersionMismatchError(ValueError):
    """Raised when embedding provider's embedding_version differs from archive index rows."""

    def __init__(self, provider_version: str, index_version: str) -> None:
        self.provider_version = provider_version
        self.index_version = index_version
        super().__init__(
            f"Embedding version mismatch: provider has {provider_version!r}, "
            f"but archive index has {index_version!r}"
        )


class ArchiveRetrievalResult(BaseModel):
    """Result of archive hybrid retrieval across current documents."""

    model_config = ConfigDict(extra="forbid")

    candidates: list[ScoredChunk]
    documents: list[ArchiveDocumentRef]
    allowed_document_ids: list[str]
    identifiers: QueryIdentifiers
    lexical_count: int
    dense_count: int


class ArchiveRetriever:
    """Hybrid retrieval across the current version of all documents in an archive scope."""

    def __init__(
        self,
        *,
        index: ArchiveIndex,
        embedding_provider: EmbeddingProvider,
        reranker: Reranker,
        lexical_top_k: int = ARCHIVE_LEXICAL_TOP_K,
        dense_top_k: int = ARCHIVE_DENSE_TOP_K,
        rerank_top_k: int = ARCHIVE_RERANK_TOP_K,
    ) -> None:
        if lexical_top_k <= 0 or dense_top_k <= 0 or rerank_top_k <= 0:
            raise ValueError(
                "top_k values must be positive integers: "
                f"lexical_top_k={lexical_top_k}, "
                f"dense_top_k={dense_top_k}, "
                f"rerank_top_k={rerank_top_k}"
            )

        self._index = index
        self._embedding_provider = embedding_provider
        self._reranker = reranker
        self._lexical_top_k = lexical_top_k
        self._dense_top_k = dense_top_k
        self._rerank_top_k = rerank_top_k

    @property
    def index(self) -> ArchiveIndex:
        return self._index

    @property
    def embedding_provider(self) -> EmbeddingProvider:
        return self._embedding_provider

    @property
    def reranker(self) -> Reranker:
        return self._reranker

    @property
    def lexical_top_k(self) -> int:
        return self._lexical_top_k

    @property
    def dense_top_k(self) -> int:
        return self._dense_top_k

    @property
    def rerank_top_k(self) -> int:
        return self._rerank_top_k

    async def retrieve(
        self,
        query: str,
        *,
        scope: EvidenceScope,
        filters: ArchiveFilter | None = None,
    ) -> ArchiveRetrievalResult:
        """Retrieve and rank candidate chunks from current documents across the archive.

        Pipeline execution sequence:
        1. Validate archive scope.
        2. Extract query identifiers.
        3. Build the independent current-version allow-list FIRST before retrieval.
           If the allow-list is empty, return an empty result immediately.
        4. If the query is empty or whitespace, return an empty result with allow-list.
        5. Lexical search using Okapi BM25 over current-version chunks.
        6. Dense vector search using query embedding (skip if zero embedded chunks in archive).
        7. Independent current-version re-check: verify all retrieved document_ids in allow-list.
        8. Fuse lexical and dense results with rank-only reciprocal rank fusion.
        9. Exact-identifier boost applied to the fused list only (reorders, never adds/removes).
        10. Validate multi-document candidate collection and rerank.
        11. Re-check reranked candidate document_ids against the allow-list one final time.
        """
        # 1. Validate archive scope
        validate_archive_scope(scope)

        # 2. Extract query identifiers
        identifiers = extract_query_identifiers(query)

        # 3. Build the allow-list FIRST before retrieval
        allowed = self._index.current_documents(scope, filters)
        allowed_ids = {d.document_id for d in allowed}
        sorted_allowed_ids = sorted(allowed_ids)

        if not allowed:
            return ArchiveRetrievalResult(
                candidates=[],
                documents=[],
                allowed_document_ids=[],
                identifiers=identifiers,
                lexical_count=0,
                dense_count=0,
            )

        # 4. Empty/whitespace query -> return empty candidates with documents populated
        if not query or not query.strip():
            return ArchiveRetrievalResult(
                candidates=[],
                documents=allowed,
                allowed_document_ids=sorted_allowed_ids,
                identifiers=identifiers,
                lexical_count=0,
                dense_count=0,
            )

        # 5. Lexical retrieval
        lexical = self._index.search_lexical(scope, query, self._lexical_top_k, filters)
        lexical_count = len(lexical)

        # 6. Dense retrieval
        stats = self._index.stats(scope, filters)
        if stats.embedded_chunks == 0:
            # If the archive has zero embedded chunks (e.g. initial migration or raw text),
            # gracefully skip dense retrieval and continue with lexical-only results.
            dense: list[ScoredChunk] = []
        else:
            if (
                stats.embedding_version is not None
                and stats.embedding_version != self._embedding_provider.embedding_version
            ):
                raise ArchiveEmbeddingVersionMismatchError(
                    provider_version=self._embedding_provider.embedding_version,
                    index_version=stats.embedding_version,
                )

            embedding_result = await self._embedding_provider.embed_query(query)
            if (
                embedding_result.embedding_version is not None
                and embedding_result.embedding_version != self._embedding_provider.embedding_version
            ):
                raise ArchiveEmbeddingVersionMismatchError(
                    provider_version=self._embedding_provider.embedding_version,
                    index_version=embedding_result.embedding_version,
                )

            if not embedding_result.vectors or not embedding_result.vectors[0]:
                dense = []
            else:
                query_vector = embedding_result.vectors[0]
                dense = self._index.search_dense(scope, query_vector, self._dense_top_k, filters)
        dense_count = len(dense)

        # 7. Independent current-version re-check
        for candidate in lexical:
            if candidate.chunk.document_id not in allowed_ids:
                raise ValueError(
                    f"lexical candidate chunk {candidate.chunk.chunk_id!r} from document "
                    f"{candidate.chunk.document_id!r} is not in allowed current documents: "
                    f"{allowed_ids}"
                )

        for candidate in dense:
            if candidate.chunk.document_id not in allowed_ids:
                raise ValueError(
                    f"dense candidate chunk {candidate.chunk.chunk_id!r} from document "
                    f"{candidate.chunk.document_id!r} is not in allowed current documents: "
                    f"{allowed_ids}"
                )

        # 8. Fuse lexical and dense result lists with archive RRF
        fused = archive_reciprocal_rank_fusion(
            [lexical, dense], scope, allowed_documents=allowed_ids
        )

        # 9. Exact-identifier boost, applied to the FUSED list only
        if not identifiers.is_empty() and fused:
            # Stably re-sort the fused candidates by (-identifier_match_score, fused_rank)
            # Use each chunk's own document_number for the score.
            sorted_candidates = sorted(
                fused,
                key=lambda candidate: (
                    -identifier_match_score(
                        identifiers,
                        chunk_text=candidate.chunk.text,
                        document_number=candidate.chunk.document_number,
                    ),
                    candidate.rank,
                ),
            )
            # Renumber rank densely 1..N after reorder, keeping retriever="fused"
            fused = [
                ScoredChunk(
                    chunk=candidate.chunk,
                    score=candidate.score,
                    rank=idx,
                    retriever="fused",
                )
                for idx, candidate in enumerate(sorted_candidates, start=1)
            ]

        # 10. Multi-document candidate validation before reranking
        validate_archive_rerank_candidates(fused, allowed_documents=allowed_ids)
        reranked = await self._reranker.rerank(query, fused, self._rerank_top_k)

        # 11. Final re-check against allowed_ids
        for candidate in reranked:
            if candidate.chunk.document_id not in allowed_ids:
                raise ValueError(
                    f"reranked candidate chunk {candidate.chunk.chunk_id!r} from document "
                    f"{candidate.chunk.document_id!r} is not in allowed current documents: "
                    f"{allowed_ids}"
                )

        return ArchiveRetrievalResult(
            candidates=reranked,
            documents=allowed,
            allowed_document_ids=sorted_allowed_ids,
            identifiers=identifiers,
            lexical_count=lexical_count,
            dense_count=dense_count,
        )


__all__ = [
    "ArchiveEmbeddingVersionMismatchError",
    "ArchiveRetrievalResult",
    "ArchiveRetriever",
]
