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
        chunk_ids: set[str] = set()
        for chunk in chunks:
            if chunk.chunk_id in chunk_ids:
                raise ValueError(f"duplicate chunk_id {chunk.chunk_id!r}")
            chunk_ids.add(chunk.chunk_id)

        for chunk in chunks:
            if chunk.chunk_id not in scopes:
                raise ValueError(f"chunk {chunk.chunk_id!r} has no registered scope")

        for chunk_id in scopes:
            if chunk_id not in chunk_ids:
                raise ValueError(f"unknown scope for chunk_id {chunk_id!r}")

        for chunk in chunks:
            registered_scope = scopes[chunk.chunk_id]
            if (
                registered_scope.document_id is not None
                and registered_scope.document_id != chunk.document_id
            ):
                raise ValueError(
                    f"chunk {chunk.chunk_id!r} document_id {chunk.document_id!r} does not "
                    f"match scope document_id {registered_scope.document_id!r}"
                )
            if (
                registered_scope.document_version is not None
                and registered_scope.document_version != chunk.document_version
            ):
                raise ValueError(
                    f"chunk {chunk.chunk_id!r} document_version "
                    f"{chunk.document_version!r} does not match "
                    f"scope document_version {registered_scope.document_version!r}"
                )
            if (
                registered_scope.parse_run_id is not None
                and registered_scope.parse_run_id != chunk.parse_run_id
            ):
                raise ValueError(
                    f"chunk {chunk.chunk_id!r} parse_run_id {chunk.parse_run_id!r} does not "
                    f"match scope parse_run_id {registered_scope.parse_run_id!r}"
                )

        self._chunks: dict[str, Chunk] = {chunk.chunk_id: chunk for chunk in chunks}
        self._scopes: dict[str, EvidenceScope] = {
            chunk.chunk_id: EvidenceScope(
                family_id=scopes[chunk.chunk_id].family_id,
                user_id=scopes[chunk.chunk_id].user_id,
                thread_id=scopes[chunk.chunk_id].thread_id,
                document_id=chunk.document_id,
                document_version=chunk.document_version,
                parse_run_id=chunk.parse_run_id,
                archive_scope=scopes[chunk.chunk_id].archive_scope,
            )
            for chunk in chunks
        }
        self._tokens: dict[str, set[str]] = {
            chunk.chunk_id: _tokenize(chunk.text) for chunk in chunks
        }

    def search(self, query: str, *, scope: EvidenceScope, top_k: int = 10) -> list[LexicalHit]:
        if top_k <= 0:
            raise ValueError(f"top_k must be a positive integer, got {top_k}")
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
