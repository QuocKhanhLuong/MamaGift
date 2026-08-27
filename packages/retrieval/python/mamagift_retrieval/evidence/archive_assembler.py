"""Multi-document evidence assembler for archive-scoped retrieval."""

from __future__ import annotations

from mamagift_retrieval.archive.constants import (
    ARCHIVE_MAX_DOCUMENTS,
    ARCHIVE_PER_DOCUMENT_CHAR_CAP,
)
from mamagift_retrieval.archive.protocol import validate_archive_scope
from mamagift_retrieval.budget import (
    EvidenceBudget,
    assemble_bounded_context,
)
from mamagift_retrieval.chunk import Chunk
from mamagift_retrieval.evidence.assembler import Evidence, EvidenceSet
from mamagift_retrieval.scope import EvidenceScope, scope_matches
from mamagift_retrieval.search.types import ScoredChunk

# Structured fields the chunker binds to a chunk rather than leaving loose in its text.
# For a plan task these carry the owner and deadline, and keeping them attached is what stops
# one task's owner being read off another's. Every value here is verbatim parsed text, so
# rendering it into the evidence block adds no claim the document did not make.
_RENDERED_METADATA_FIELDS: tuple[tuple[str, str], ...] = (
    ("ordinal", "Số thứ tự"),
    ("owner", "Đơn vị chủ trì"),
    ("coordinating_unit", "Đơn vị phối hợp"),
    ("deadline_raw", "Thời hạn hoàn thành"),
)


def render_evidence_text(chunk: Chunk) -> str:
    """The text a model actually sees for one chunk, including its structured fields.

    Without this the association lives only in `Chunk.metadata`, which never reaches the
    prompt: a grounded answer could cite the chunk that holds a task but would have no
    evidence for who owns it or when it is due, and would have to guess.
    """
    lines = [chunk.text]
    for key, label in _RENDERED_METADATA_FIELDS:
        value = chunk.metadata.get(key)
        if isinstance(value, str) and value.strip():
            lines.append(f"{label}: {value.strip()}")
    return "\n".join(lines)


def assemble_archive_evidence(
    candidates: list[ScoredChunk],
    *,
    scope: EvidenceScope,
    budget: EvidenceBudget,
    query_id: str,
    allowed_documents: set[str] | None = None,
    max_documents: int = ARCHIVE_MAX_DOCUMENTS,
    per_document_char_cap: int = ARCHIVE_PER_DOCUMENT_CHAR_CAP,
) -> EvidenceSet:
    """Create a bounded, ordered evidence set from cross-document archive candidates.

    Candidate order is the final evidence order, determining citation identifiers (c1..cN)
    densely and deterministically. Cross-document fairness is enforced by a per-document
    character cap and a total admitted document count cap.
    """
    if max_documents <= 0:
        raise ValueError(f"max_documents must be positive, got {max_documents}")
    if per_document_char_cap <= 0:
        raise ValueError(f"per_document_char_cap must be positive, got {per_document_char_cap}")

    # 1. Reject anything that is not a true archive wildcard.
    validate_archive_scope(scope)

    # 2-4. Validate candidates against duplicates, scope, version provenance, and allowed documents.
    validated_candidates: list[tuple[ScoredChunk, int]] = []
    seen_chunk_ids: set[str] = set()
    for candidate in candidates:
        chunk = candidate.chunk
        if chunk.chunk_id in seen_chunk_ids:
            raise ValueError(f"duplicate evidence chunk_id {chunk.chunk_id!r}")
        seen_chunk_ids.add(chunk.chunk_id)

        candidate_scope = EvidenceScope(
            family_id=scope.family_id,
            document_id=chunk.document_id,
            document_version=chunk.document_version,
            parse_run_id=chunk.parse_run_id,
            user_id=scope.user_id,
            thread_id=scope.thread_id,
        )
        if not scope_matches(candidate_scope, scope):
            raise ValueError(f"candidate chunk {chunk.chunk_id!r} violates requested EvidenceScope")
        if chunk.document_version is None:
            raise ValueError(
                f"candidate chunk {chunk.chunk_id!r} has no document_version provenance"
            )
        if allowed_documents is not None and chunk.document_id not in allowed_documents:
            raise ValueError(
                f"candidate chunk {chunk.chunk_id!r} document_id {chunk.document_id!r} "
                f"is not in allowed_documents"
            )
        validated_candidates.append((candidate, chunk.document_version))

    # 5-6. Enforce document count cap and per-document fairness.
    admitted_documents: set[str] = set()
    doc_char_counts: dict[str, int] = {}
    surviving_candidates: list[tuple[ScoredChunk, int]] = []

    for candidate, document_version in validated_candidates:
        chunk = candidate.chunk
        doc_id = chunk.document_id

        # Document count cap: once max_documents distinct documents have contributed at least
        # one chunk, candidates from a new document are dropped.
        if doc_id not in admitted_documents and len(admitted_documents) >= max_documents:
            continue

        # Per-document fairness: a candidate whose document has already used per_document_char_cap
        # characters is dropped rather than truncated mid-chunk. Mid-chunk truncation would produce
        # partial sentences or severed legal clauses that cannot be cited safely.
        if doc_char_counts.get(doc_id, 0) >= per_document_char_cap:
            continue

        admitted_documents.add(doc_id)
        doc_char_counts[doc_id] = doc_char_counts.get(doc_id, 0) + len(chunk.text)
        surviving_candidates.append((candidate, document_version))

    # 7. Feed surviving candidate text to assemble_bounded_context under "archive_semantic".
    candidate_texts = [
        render_evidence_text(candidate.chunk) for candidate, _ in surviving_candidates
    ]
    offered_text = "".join(candidate_texts)
    bounded, breakdown = assemble_bounded_context(
        budget,
        {"archive_semantic": offered_text},
    )
    bounded_text = bounded["archive_semantic"]

    # 8. Split bounded text back across surviving candidates with dense citation IDs (c1..cN).
    evidence: list[Evidence] = []
    offset = 0
    for index, (candidate, document_version) in enumerate(surviving_candidates, start=1):
        chunk = candidate.chunk
        rendered = render_evidence_text(chunk)
        end = min(offset + len(rendered), len(bounded_text))
        evidence.append(
            Evidence(
                citation_id=f"c{index}",
                chunk_id=chunk.chunk_id,
                document_id=chunk.document_id,
                parse_run_id=chunk.parse_run_id,
                document_version=document_version,
                page_numbers=list(chunk.source_page_numbers),
                source_block_ids=list(chunk.source_block_ids),
                section_path=list(chunk.section_path),
                text=bounded_text[offset:end],
            )
        )
        offset += len(rendered)

    # 9. Return the assembled EvidenceSet.
    return EvidenceSet(
        scope=scope,
        evidence=evidence,
        budget=breakdown,
        query_id=query_id,
    )


def group_evidence_by_document(evidence: EvidenceSet) -> dict[str, list[Evidence]]:
    """Group Evidence items by document_id preserving candidate order and first-appearance keys.

    Raises:
        ValueError: If any Evidence item has an empty document_id.
    """
    grouped: dict[str, list[Evidence]] = {}
    for item in evidence.evidence:
        if not item.document_id or not item.document_id.strip():
            raise ValueError(f"evidence item {item.citation_id!r} has empty document_id")
        grouped.setdefault(item.document_id, []).append(item)
    return grouped


__all__ = [
    "assemble_archive_evidence",
    "group_evidence_by_document",
    "render_evidence_text",
]
