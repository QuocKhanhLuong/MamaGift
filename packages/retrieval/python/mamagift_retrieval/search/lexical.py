"""Vietnamese BM25 lexical retriever for Phase 4 single-document RAG.

Contracts implemented:
- Ranking contract (Phase 4 Plan §3.3): ScoredChunk with 1-based dense rank, retriever='lexical'.
- Named BM25 hyperparameters with stated rationales (k1=1.5, b=0.75).
- Deterministic ordering and stable tie-break by chunk_id.
- EvidenceScope validation and full tuple isolation: family_id, document_id,
  document_version, parse_run_id.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, Field

from mamagift_retrieval.chunk import Chunk, validate_chunk_tree
from mamagift_retrieval.index.protocol import DocumentIndex
from mamagift_retrieval.scope import EvidenceScope, scope_matches

from .types import ScoredChunk
from .vi_tokenize import tokenize_vi

# ============================================================================
# Named BM25 Hyperparameters and Rationales
# ============================================================================

DEFAULT_BM25_K1: float = 1.5
"""Default BM25 k1 term frequency saturation parameter.

Rationale: Controls non-linear term frequency scaling. In single-document Vietnamese
administrative and legal RAG, chunks are passage-length (typically 50-300 words).
A value of k1=1.5 prevents repeated boilerplate terms from overpowering distinct
keywords while still rewarding multiple occurrences of relevant terminology.
"""

DEFAULT_BM25_B: float = 0.75
"""Default BM25 b document length normalization parameter.

Rationale: Normalizes term frequency by chunk length relative to average chunk length (avgdl).
A value of b=0.75 provides standard document length normalization, moderately penalizing
lengthy multi-paragraph chunks in favor of concise, targeted chunks while avoiding
excessive penalty for naturally longer legal articles.
"""


class BM25Params(BaseModel):
    """Configurable hyperparameters for Okapi BM25 scoring."""

    model_config = ConfigDict(extra="forbid")

    k1: float = Field(
        default=DEFAULT_BM25_K1,
        ge=0.0,
        description="Term frequency saturation parameter.",
    )
    b: float = Field(
        default=DEFAULT_BM25_B,
        ge=0.0,
        le=1.0,
        description="Document length normalization parameter.",
    )


# ============================================================================
# BM25 In-Memory Index over Chunks
# ============================================================================


class BM25Index:
    """In-memory Okapi BM25 index over a collection of document chunks.

    Enforces full EvidenceScope isolation and deterministic ordering with
    stable tie-breaking on chunk_id.
    """

    def __init__(
        self,
        chunks: Sequence[Chunk],
        *,
        scope: EvidenceScope | None = None,
        k1: float = DEFAULT_BM25_K1,
        b: float = DEFAULT_BM25_B,
    ) -> None:
        """Initialize BM25 index with a collection of chunks.

        If `scope` is provided, all chunks are validated against it.
        """
        if k1 < 0.0:
            raise ValueError(f"k1 must be non-negative, got {k1}")
        if not (0.0 <= b <= 1.0):
            raise ValueError(f"b must be between 0.0 and 1.0, got {b}")

        self._k1 = k1
        self._b = b
        self._chunks_list: list[Chunk] = list(chunks)
        # A Chunk does not carry family_id.  Bind the family supplied by the
        # indexing boundary once, rather than copying the query's family onto
        # every candidate during search.  An unbound collection cannot prove
        # family isolation and is therefore rejected when searched.
        self._indexed_scope = scope

        if self._chunks_list:
            validate_chunk_tree(self._chunks_list)

        seen_ids: set[str] = set()
        for chunk in self._chunks_list:
            if chunk.chunk_id in seen_ids:
                raise ValueError(f"duplicate chunk_id {chunk.chunk_id!r}")
            seen_ids.add(chunk.chunk_id)

            if scope is not None:
                chunk_scope = EvidenceScope(
                    # This is provenance recorded at construction time, not
                    # the caller's later query scope.
                    family_id=scope.family_id,
                    document_id=chunk.document_id,
                    document_version=chunk.document_version,
                    parse_run_id=chunk.parse_run_id,
                    user_id=scope.user_id,
                    thread_id=scope.thread_id,
                )
                _validate_indexed_chunk_scope(chunk, chunk_scope, scope)

        # Precompute tokenizations, term frequencies, document lengths
        self._doc_tf: dict[str, dict[str, int]] = {}
        self._doc_len: dict[str, int] = {}
        self._doc_freq: dict[str, int] = Counter()

        for chunk in self._chunks_list:
            tokens = tokenize_vi(chunk.text)
            self._doc_len[chunk.chunk_id] = len(tokens)
            tf = Counter(tokens)
            self._doc_tf[chunk.chunk_id] = dict(tf)
            for term in tf:
                self._doc_freq[term] += 1

        self._num_docs = len(self._chunks_list)
        total_len = sum(self._doc_len.values())
        self._avgdl = (total_len / self._num_docs) if self._num_docs > 0 else 0.0

    @property
    def total_chunks(self) -> int:
        """Return total number of chunks indexed."""
        return self._num_docs

    @property
    def k1(self) -> float:
        """BM25 k1 hyperparameter."""
        return self._k1

    @property
    def b(self) -> float:
        """BM25 b hyperparameter."""
        return self._b

    def search(
        self,
        query: str,
        *,
        scope: EvidenceScope,
        top_k: int = 10,
    ) -> list[ScoredChunk]:
        """Search the indexed chunks using BM25 with Vietnamese tokenisation.

        Args:
            query: Query text in Vietnamese.
            scope: Required EvidenceScope for version/document isolation.
            top_k: Number of top results to return (must be >= 1).

        Returns:
            List of ScoredChunk values sorted by descending score with stable chunk_id tie-break.
        """
        if top_k <= 0:
            raise ValueError(f"top_k must be a positive integer, got {top_k}")
        _validate_search_scope(scope)

        if self._num_docs == 0:
            return []

        if self._indexed_scope is None:
            raise ValueError("BM25Index must be initialized with an indexed EvidenceScope")

        query_tokens = tokenize_vi(query)
        if not query_tokens:
            return []

        query_tf = Counter(query_tokens)

        # Filter candidate chunks strictly matching scope
        scoped_chunks: list[Chunk] = []
        for chunk in self._chunks_list:
            chunk_scope = EvidenceScope(
                family_id=self._indexed_scope.family_id,
                document_id=chunk.document_id,
                document_version=chunk.document_version,
                parse_run_id=chunk.parse_run_id,
                user_id=self._indexed_scope.user_id,
                thread_id=self._indexed_scope.thread_id,
            )
            if not scope_matches(chunk_scope, scope):
                continue
            scoped_chunks.append(chunk)

        if not scoped_chunks:
            return []

        candidates: list[tuple[float, Chunk]] = []

        for chunk in scoped_chunks:
            chunk_id = chunk.chunk_id
            tf_map = self._doc_tf.get(chunk_id, {})
            dl = self._doc_len.get(chunk_id, 0)
            len_norm = (1.0 - self._b + self._b * (dl / self._avgdl)) if self._avgdl > 0.0 else 1.0

            score = 0.0
            has_match = False

            for term, qtf in query_tf.items():
                f = tf_map.get(term, 0)
                if f > 0:
                    has_match = True
                    df = self._doc_freq.get(term, 0)
                    # Standard Robertson / Lucene IDF: ln(1 + (N - df + 0.5) / (df + 0.5))
                    idf = math.log(1.0 + (self._num_docs - df + 0.5) / (df + 0.5))
                    tf_norm = (f * (self._k1 + 1.0)) / (f + self._k1 * len_norm)
                    score += qtf * idf * tf_norm

            if has_match and score > 0.0:
                candidates.append((score, chunk))

        # Deterministic sort: descending score, ascending chunk_id for tie-break
        candidates.sort(key=lambda item: (-item[0], item[1].chunk_id))
        top_candidates = candidates[:top_k]

        return [
            ScoredChunk(
                chunk=chunk,
                score=score,
                rank=idx + 1,
                retriever="lexical",
            )
            for idx, (score, chunk) in enumerate(top_candidates)
        ]


# ============================================================================
# BM25 Lexical Retriever
# ============================================================================


class BM25LexicalRetriever:
    """Vietnamese BM25 lexical retriever for Phase 4 single-document RAG.

    Can be initialized either with an in-memory sequence of `Chunk`s (or `BM25Index`)
    or with a `DocumentIndex` protocol instance.
    """

    def __init__(
        self,
        chunks_or_index: Sequence[Chunk] | BM25Index | DocumentIndex | None = None,
        *,
        k1: float = DEFAULT_BM25_K1,
        b: float = DEFAULT_BM25_B,
    ) -> None:
        self._k1 = k1
        self._b = b
        self._doc_index: DocumentIndex | None = None
        self._bm25_index: BM25Index | None = None

        if isinstance(chunks_or_index, BM25Index):
            self._bm25_index = chunks_or_index
        elif isinstance(chunks_or_index, DocumentIndex):
            self._doc_index = chunks_or_index
        elif isinstance(chunks_or_index, Sequence):
            self._bm25_index = BM25Index(chunks_or_index, k1=k1, b=b)
        elif chunks_or_index is None:
            self._bm25_index = BM25Index([], k1=k1, b=b)
        else:
            raise TypeError(f"unsupported index or chunk source type: {type(chunks_or_index)}")

    @classmethod
    def from_chunks(
        cls,
        chunks: Sequence[Chunk],
        *,
        scope: EvidenceScope | None = None,
        k1: float = DEFAULT_BM25_K1,
        b: float = DEFAULT_BM25_B,
    ) -> BM25LexicalRetriever:
        """Create a BM25LexicalRetriever from a collection of chunks with scope validation."""
        index = BM25Index(chunks, scope=scope, k1=k1, b=b)
        return cls(index, k1=k1, b=b)

    def search(
        self,
        query: str,
        *,
        scope: EvidenceScope,
        top_k: int = 10,
    ) -> list[ScoredChunk]:
        """Search lexical candidates.

        The query is always supplied first and the complete evidence scope is
        supplied by keyword so callers cannot accidentally swap the two.
        """
        if scope is None:
            raise ValueError("scope must be provided as a keyword argument")
        _validate_search_scope(scope)

        if self._doc_index is not None:
            # DocumentIndex.search_lexical is the frozen production seam.  Its
            # current SQL adapter performs deterministic term overlap, not
            # BM25; this adapter must not claim to recalculate BM25 without a
            # chunk-enumeration contract.  The index remains responsible for
            # family/version/parse-run isolation.
            results = self._doc_index.search_lexical(
                scope=scope,
                query=query,
                top_k=top_k,
            )
            for result in results:
                _validate_returned_chunk_scope(result.chunk, scope)
            return results

        if self._bm25_index is not None:
            return self._bm25_index.search(
                query=query,
                scope=scope,
                top_k=top_k,
            )

        return []


# Alias for compatibility
LexicalRetriever = BM25LexicalRetriever


def _validate_search_scope(scope: EvidenceScope) -> None:
    """Reject retrieval scopes that are broad enough to mix document data."""
    if not scope.document_id:
        raise ValueError("scope must specify document_id")
    if scope.document_version is None and scope.parse_run_id is None:
        raise ValueError("scope must specify parse_run_id or document_version")


def _validate_returned_chunk_scope(chunk: Chunk, scope: EvidenceScope) -> None:
    """Ensure an index adapter did not return a chunk outside its request."""
    candidate = EvidenceScope(
        family_id=scope.family_id,
        document_id=chunk.document_id,
        document_version=chunk.document_version,
        parse_run_id=chunk.parse_run_id,
    )
    if not scope_matches(candidate, scope):
        raise ValueError(f"retrieved chunk {chunk.chunk_id!r} violates requested EvidenceScope")


def _validate_indexed_chunk_scope(
    chunk: Chunk,
    candidate: EvidenceScope,
    allowed: EvidenceScope,
) -> None:
    """Validate recorded chunk provenance against the index's construction scope."""
    if candidate.document_id != allowed.document_id and not allowed.archive_scope:
        raise ValueError(
            f"chunk {chunk.chunk_id!r} document_id {chunk.document_id!r} "
            f"contradicts scope document_id {allowed.document_id!r}"
        )
    if (
        allowed.document_version is not None
        and candidate.document_version != allowed.document_version
    ):
        raise ValueError(
            f"chunk {chunk.chunk_id!r} document_version {chunk.document_version!r} "
            f"contradicts scope document_version {allowed.document_version!r}"
        )
    if allowed.parse_run_id is not None and candidate.parse_run_id != allowed.parse_run_id:
        raise ValueError(
            f"chunk {chunk.chunk_id!r} parse_run_id {chunk.parse_run_id!r} "
            f"contradicts scope parse_run_id {allowed.parse_run_id!r}"
        )
    if not scope_matches(candidate, allowed):
        raise ValueError(f"chunk {chunk.chunk_id!r} scope violates requested EvidenceScope")
