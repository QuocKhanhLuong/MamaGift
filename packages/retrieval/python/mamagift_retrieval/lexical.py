"""Naive lexical retrieval baseline seam (Phase 3.5).

This is deliberately the simplest possible deterministic baseline: token-overlap
scoring over `Chunk.text`, with ties broken by `chunk_id`. It is not a claim of
retrieval quality — it exists only so a later hybrid/reranked implementation
(Phase 4/5) has something naive to beat, per the required
`naive baseline vs hybrid retrieval vs reranked retrieval` comparison seam.

No embeddings, vector store, BM25 term-frequency weighting or reranker model is
implemented here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from .chunk import Chunk
from .scope import EvidenceScope, scope_matches

_TOKEN_RE = re.compile(r"[^\W\d_]+|\d+", re.UNICODE)


def _tokenize(text: str) -> set[str]:
    return {token.lower() for token in _TOKEN_RE.findall(text)}


@dataclass(frozen=True)
class LexicalHit:
    chunk_id: str
    score: float


class RetrievalBaseline(Protocol):
    """The seam a future hybrid/reranked baseline must also satisfy, so an eval
    harness can compare candidates without knowing which one is running."""

    def search(self, query: str, *, scope: EvidenceScope, top_k: int = 10) -> list[LexicalHit]: ...


class LexicalIndex:
    """Deterministic term-overlap search over a fixed set of chunks.

    Scope filtering (`scope_matches`) is applied before scoring: a chunk outside the
    caller's scope is never returned, regardless of lexical score.
    """

    def __init__(self, chunks: list[Chunk], scopes: dict[str, EvidenceScope]) -> None:
        """`scopes` maps `chunk_id -> EvidenceScope` the chunk belongs to."""
        self._chunks = {chunk.chunk_id: chunk for chunk in chunks}
        self._scopes = scopes
        self._tokens = {chunk.chunk_id: _tokenize(chunk.text) for chunk in chunks}

    def search(self, query: str, *, scope: EvidenceScope, top_k: int = 10) -> list[LexicalHit]:
        query_tokens = _tokenize(query)
        if not query_tokens:
            return []

        hits: list[LexicalHit] = []
        for chunk_id, chunk_scope in self._scopes.items():
            if not scope_matches(chunk_scope, scope):
                continue
            overlap = query_tokens & self._tokens[chunk_id]
            if not overlap:
                continue
            score = len(overlap) / len(query_tokens)
            hits.append(LexicalHit(chunk_id=chunk_id, score=score))

        hits.sort(key=lambda hit: (-hit.score, hit.chunk_id))
        return hits[:top_k]
