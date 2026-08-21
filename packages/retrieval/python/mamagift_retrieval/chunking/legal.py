"""Chunks derived from the legal/administrative hierarchy
(`Chương/Mục/Điều/Khoản/Điểm/Phụ lục`) that `parse_admin_document` already built.

This module only re-shapes hierarchy nodes the admin parser already validated into
the Phase 3.5 `Chunk` contract; it never re-parses text and never invents structure.
"""

from __future__ import annotations

from mamagift_docpipe import CanonicalDocument, HierarchyKind, HierarchyNode

from ..chunk import Chunk, ChunkType
from ._shared import field_value

_KIND_TO_CHUNK_TYPE: dict[HierarchyKind, ChunkType] = {
    HierarchyKind.CHAPTER: ChunkType.LEGAL_CHAPTER,
    HierarchyKind.SECTION: ChunkType.LEGAL_SECTION,
    HierarchyKind.ARTICLE: ChunkType.LEGAL_ARTICLE,
    HierarchyKind.CLAUSE: ChunkType.LEGAL_CLAUSE,
    HierarchyKind.POINT: ChunkType.LEGAL_POINT,
    HierarchyKind.APPENDIX: ChunkType.APPENDIX,
}


def _section_path(node: HierarchyNode, by_id: dict[str, HierarchyNode]) -> list[str]:
    path: list[str] = []
    current: HierarchyNode | None = node
    seen: set[str] = set()
    while current is not None and current.id not in seen:
        seen.add(current.id)
        path.append(current.label)
        current = by_id.get(current.parent_id) if current.parent_id else None
    return list(reversed(path))


def build_legal_chunks(
    document: CanonicalDocument,
    *,
    document_version: int | None = None,
) -> list[Chunk]:
    """One chunk per hierarchy node the admin parser produced.

    `Nơi nhận` (`CUSTOM_HEADING`) nodes are intentionally excluded: they are a
    recipient list, not chunkable body content, and carry no useful retrieval text.
    """
    by_id = {
        node.id: node for node in document.hierarchy if node.kind != HierarchyKind.CUSTOM_HEADING
    }
    text_by_block = {block.id: block.text for page in document.pages for block in page.blocks}
    page_by_block = {block.id: page.page_number for page in document.pages for block in page.blocks}
    doc_type = field_value(document, "document_type")
    doc_number = field_value(document, "document_number")
    issuer = field_value(document, "issuer")
    issued_date = field_value(document, "issue_date")

    chunks: list[Chunk] = []
    for node in document.hierarchy:
        if node.kind == HierarchyKind.CUSTOM_HEADING:
            continue

        block_texts = [text_by_block[bid] for bid in node.source_block_ids if bid in text_by_block]
        text = node.text if node.text else "\n".join(block_texts)
        page_numbers = sorted(
            {page_by_block[bid] for bid in node.source_block_ids if bid in page_by_block}
        )
        parent_chunk_id = (
            f"chunk_{document.document_id}_{document.parser_run.id}_{node.parent_id}"
            if node.parent_id and node.parent_id in by_id
            else None
        )

        chunks.append(
            Chunk(
                chunk_id=f"chunk_{document.document_id}_{document.parser_run.id}_{node.id}",
                parent_chunk_id=parent_chunk_id,
                document_id=document.document_id,
                parse_run_id=document.parser_run.id,
                document_version=document_version,
                document_type=doc_type,
                document_number=doc_number,
                issuer=issuer,
                issued_date=issued_date,
                section_path=_section_path(node, by_id),
                chunk_type=_KIND_TO_CHUNK_TYPE[node.kind],
                text=text,
                source_block_ids=list(node.source_block_ids),
                source_page_numbers=page_numbers,
                metadata={"hierarchy_id": node.id, "hierarchy_label": node.label},
            )
        )
    return chunks
