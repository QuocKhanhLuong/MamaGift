"""Deterministic fallback chunking for canonical blocks that neither the legal
hierarchy chunker nor the plan chunker claimed.

Every fallback chunk is exactly one canonical block: no fixed-token windowing, no
merging heuristic that could silently join unrelated paragraphs.
"""

from __future__ import annotations

from mamagift_docpipe import BlockType, CanonicalDocument, HierarchyKind

from ..chunk import Chunk, ChunkType
from ._shared import field_value

_SKIP_TYPES = frozenset(
    {BlockType.HEADER, BlockType.FOOTER, BlockType.PAGE_NUMBER, BlockType.STAMP_REGION}
)


def build_fallback_chunks(
    document: CanonicalDocument,
    claimed_block_ids: set[str],
    *,
    document_version: int | None = None,
) -> list[Chunk]:
    doc_id, run_id = document.document_id, document.parser_run.id
    doc_type = field_value(document, "document_type")
    doc_number = field_value(document, "document_number")
    issuer = field_value(document, "issuer")
    issued_date = field_value(document, "issue_date")

    chunk_id_by_hierarchy = {
        node.id: f"chunk_{doc_id}_{run_id}_{node.id}"
        for node in document.hierarchy
        if node.kind != HierarchyKind.CUSTOM_HEADING
    }

    chunks: list[Chunk] = []
    for page in document.pages:
        for block in sorted(page.blocks, key=lambda item: item.reading_order):
            if block.id in claimed_block_ids or not block.text.strip():
                continue
            if block.type in _SKIP_TYPES:
                continue
            parent_chunk_id = (
                chunk_id_by_hierarchy.get(block.parent_id) if block.parent_id else None
            )
            chunks.append(
                Chunk(
                    chunk_id=f"chunk_{doc_id}_{run_id}_fallback_{block.id}",
                    parent_chunk_id=parent_chunk_id,
                    document_id=doc_id,
                    parse_run_id=run_id,
                    document_version=document_version,
                    document_type=doc_type,
                    document_number=doc_number,
                    issuer=issuer,
                    issued_date=issued_date,
                    section_path=[],
                    chunk_type=ChunkType.PARAGRAPH,
                    text=block.text,
                    source_block_ids=[block.id],
                    source_page_numbers=[page.page_number],
                    metadata={"classified_by": "fallback"},
                )
            )
    return chunks
