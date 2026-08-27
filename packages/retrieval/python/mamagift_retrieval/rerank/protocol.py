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


def validate_archive_rerank_candidates(
    candidates: list[ScoredChunk],
    *,
    allowed_documents: set[str] | None = None,
) -> None:
    """Reject invalid or cross-version archive candidate collections before reranking.

    Unlike single-document rerank validation, candidates may span multiple documents.
    However, every candidate must have complete provenance (document_id, parse_run_id,
    and document_version). Within any single document, all candidates must share the
    exact same document_version and parse_run_id so stale versions never mix. If
    allowed_documents is specified, all candidate document_ids must belong to it.
    """
    chunk_ids = [candidate.chunk.chunk_id for candidate in candidates]
    if len(chunk_ids) != len(set(chunk_ids)):
        raise ValueError("rerank candidates must contain unique chunk identities")

    doc_provenance: dict[str, tuple[int, str]] = {}
    for candidate in candidates:
        chunk = candidate.chunk
        if not chunk.document_id or not chunk.document_id.strip():
            raise ValueError(f"candidate {chunk.chunk_id!r} is missing document_id")
        if not chunk.parse_run_id or not chunk.parse_run_id.strip():
            raise ValueError(f"candidate {chunk.chunk_id!r} is missing parse_run_id")
        if chunk.document_version is None:
            raise ValueError(f"candidate {chunk.chunk_id!r} is missing document_version")

        if allowed_documents is not None and chunk.document_id not in allowed_documents:
            raise ValueError(
                f"candidate {chunk.chunk_id!r} document_id {chunk.document_id!r} "
                "is not in allowed_documents"
            )

        existing_prov = doc_provenance.get(chunk.document_id)
        if existing_prov is not None:
            existing_version, existing_parse_run = existing_prov
            if (
                existing_parse_run != chunk.parse_run_id
                or existing_version != chunk.document_version
            ):
                raise ValueError(
                    f"document {chunk.document_id!r} has multiple parse runs or versions "
                    f"in rerank candidates: "
                    f"parse run {existing_parse_run!r} (v{existing_version}) vs "
                    f"{chunk.parse_run_id!r} (v{chunk.document_version})"
                )
        else:
            doc_provenance[chunk.document_id] = (chunk.document_version, chunk.parse_run_id)


__all__ = [
    "Reranker",
    "validate_archive_rerank_candidates",
    "validate_rerank_candidates",
]
