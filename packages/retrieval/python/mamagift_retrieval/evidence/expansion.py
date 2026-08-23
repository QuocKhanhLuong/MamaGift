"""Bounded, provenance-safe expansion of retrieved evidence.

Expansion is deliberately ancestor-only.  In particular, a plan task's parent
section is useful context, while the section's other task children are not: the
latter would attach another task's owner or deadline to the retrieved task.

The default and hard maximum ancestor depth are three edges.  A plan content
chunk therefore reaches its task and section (and has one spare level for a
future hierarchy), while malformed or unexpectedly deep trees cannot fan out
without bound.  Results retain candidate order; each candidate is followed by
its nearest unseen ancestor, then the next ancestor, up to the requested depth.
"""

from __future__ import annotations

from collections.abc import Iterable

from mamagift_retrieval.chunk import Chunk
from mamagift_retrieval.scope import EvidenceScope, scope_matches
from mamagift_retrieval.search.types import ScoredChunk

DEFAULT_MAX_ANCESTOR_DEPTH = 3
MAX_ANCESTOR_DEPTH = 3


def _scope_for_chunk(chunk: Chunk, requested: EvidenceScope) -> EvidenceScope:
    """Represent a chunk's provenance using the request's family context."""

    return EvidenceScope(
        family_id=requested.family_id,
        user_id=requested.user_id,
        thread_id=requested.thread_id,
        document_id=chunk.document_id,
        document_version=chunk.document_version,
        parse_run_id=chunk.parse_run_id,
        archive_scope=False,
    )


def _is_allowed(chunk: Chunk, requested: EvidenceScope) -> bool:
    """Check a chunk against the request and its complete provenance tuple."""

    return scope_matches(_scope_for_chunk(chunk, requested), requested)


def _context_candidate(source: ScoredChunk, chunk: Chunk) -> ScoredChunk:
    """Attach the source ranking metadata to a newly expanded context chunk.

    ``ScoredChunk`` has no separate context variant.  Keeping the originating
    candidate's metadata makes expansion lossless for D3 while leaving the
    chunk's own provenance untouched.
    """

    return ScoredChunk(
        chunk=chunk,
        score=source.score,
        rank=source.rank,
        retriever=source.retriever,
    )


def expand_evidence(
    candidates: list[ScoredChunk],
    *,
    scope: EvidenceScope,
    chunk_tree: Iterable[Chunk] | None = None,
    chunks: Iterable[Chunk] | None = None,
    max_depth: int = DEFAULT_MAX_ANCESTOR_DEPTH,
) -> list[ScoredChunk]:
    """Add bounded ancestor context to reranked candidates.

    ``chunk_tree`` supplies the complete Phase 3.5 tree from which parents can
    be resolved.  ``chunks`` is accepted as a descriptive alias for callers
    that already expose their indexed chunks; passing both is an error.  The
    input candidates are always retained in their original order, except that
    duplicate chunk identities are emitted once.  Ancestors are considered
    nearest-first and are followed only when ``scope_matches`` accepts both the
    request and the candidate's full document/version/parse-run provenance.

    No siblings are traversed.  A parent that is missing, stale, cross-document,
    cross-version, or cross-parse-run is simply not followed.  ``max_depth`` is
    measured in parent edges and is bounded by ``MAX_ANCESTOR_DEPTH``.
    """

    if max_depth < 0 or max_depth > MAX_ANCESTOR_DEPTH:
        raise ValueError(f"max_depth must be between 0 and {MAX_ANCESTOR_DEPTH}, got {max_depth}")
    if chunk_tree is not None and chunks is not None:
        raise ValueError("provide only one of chunk_tree or chunks")

    available = tuple(chunk_tree if chunk_tree is not None else (chunks or ()))
    by_id: dict[str, Chunk] = {}
    for chunk in available:
        if chunk.chunk_id not in by_id:
            by_id[chunk.chunk_id] = chunk

    result: list[ScoredChunk] = []
    emitted: set[str] = set()

    for candidate in candidates:
        candidate_id = candidate.chunk.chunk_id
        if candidate_id in emitted:
            continue
        emitted.add(candidate_id)
        result.append(candidate)

        # Include candidates in the lookup too.  This keeps expansion useful
        # when a parent was itself returned by retrieval, without changing its
        # original scored object or opening a sibling path.
        if candidate_id not in by_id:
            by_id[candidate_id] = candidate.chunk

        current = candidate.chunk
        for _ in range(max_depth):
            parent_id = current.parent_chunk_id
            if parent_id is None:
                break
            parent = by_id.get(parent_id)
            if parent is None:
                break

            # Check the parent against the request and against this candidate's
            # exact provenance tuple.  The second check is what prevents a
            # stale parent from being followed when its ID is supplied by a
            # caller independently of the validated Phase 3.5 tree.
            candidate_scope = _scope_for_chunk(current, scope)
            parent_scope = _scope_for_chunk(parent, scope)
            if not _is_allowed(parent, scope) or not (
                scope_matches(parent_scope, candidate_scope)
                and scope_matches(candidate_scope, parent_scope)
            ):
                break

            if parent.chunk_id in emitted:
                current = parent
                continue

            emitted.add(parent.chunk_id)
            result.append(_context_candidate(candidate, parent))
            current = parent

    return result


__all__ = [
    "DEFAULT_MAX_ANCESTOR_DEPTH",
    "MAX_ANCESTOR_DEPTH",
    "expand_evidence",
]
