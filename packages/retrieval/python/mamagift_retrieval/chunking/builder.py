"""Chunk builder orchestrator: combines the legal-hierarchy, plan and fallback
chunkers into one validated chunk set for a `CanonicalDocument`.
"""

from __future__ import annotations

from mamagift_docpipe import CanonicalDocument

from ..chunk import Chunk, validate_chunk_tree
from .fallback import build_fallback_chunks
from .legal import build_legal_chunks
from .plan import build_plan_chunks


def build_chunks(
    document: CanonicalDocument,
    *,
    document_version: int | None = None,
) -> list[Chunk]:
    """Deterministic structure-aware chunks for one parse run of one document.

    Precedence: legal hierarchy chunks first (when `parse_admin_document` found
    `Chương/Mục/Điều/Khoản/Điểm`), then plan chunks (when the document type is
    `ke_hoach`), then a fallback paragraph chunk for every remaining block with
    text. A block claimed by the legal or plan builder is never re-chunked by the
    fallback builder — chunking partitions blocks with text, it never overlaps them.
    """
    legal_chunks = build_legal_chunks(document, document_version=document_version)
    plan_chunks = build_plan_chunks(document, document_version=document_version)

    claimed_block_ids: set[str] = set()
    for chunk in legal_chunks:
        claimed_block_ids.update(chunk.source_block_ids)
    for chunk in plan_chunks:
        claimed_block_ids.update(chunk.source_block_ids)

    fallback_chunks = build_fallback_chunks(
        document, claimed_block_ids, document_version=document_version
    )

    chunks = legal_chunks + plan_chunks + fallback_chunks
    validate_chunk_tree(chunks)
    return chunks
