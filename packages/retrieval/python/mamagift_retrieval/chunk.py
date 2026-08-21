"""Structure-aware retrieval chunk contract (Phase 3.5).

A `Chunk` is derived only from a `CanonicalDocument`: chunking never invents text,
and every chunk keeps enough provenance to point back to its source blocks/pages and
the parse run/document version it was built from. No chunk is embedded or indexed by
this phase (docs/09_CODEX_EXECUTION.md non-goals).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ChunkType(StrEnum):
    """What kind of canonical structure a chunk represents."""

    LEGAL_CHAPTER = "legal_chapter"
    LEGAL_SECTION = "legal_section"
    LEGAL_ARTICLE = "legal_article"
    LEGAL_CLAUSE = "legal_clause"
    LEGAL_POINT = "legal_point"
    APPENDIX = "appendix"
    PLAN_SECTION = "plan_section"
    PLAN_TASK = "plan_task"
    PARAGRAPH = "paragraph"


class Chunk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunk_id: str = Field(min_length=1)
    parent_chunk_id: str | None = None
    document_id: str = Field(min_length=1)
    parse_run_id: str = Field(min_length=1)
    document_version: int | None = Field(default=None, ge=1)
    document_type: str | None = None
    document_number: str | None = None
    issuer: str | None = None
    issued_date: str | None = None
    section_path: list[str] = Field(default_factory=list)
    chunk_type: ChunkType
    text: str
    source_block_ids: list[str] = Field(min_length=1)
    source_page_numbers: list[int] = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


def validate_chunk_tree(chunks: list[Chunk]) -> None:
    """Structural invariants every chunk set must satisfy regardless of builder.

    Raises `ValueError` naming the first violation found: a duplicate `chunk_id`, a
    `parent_chunk_id` with no matching chunk, or a parent that belongs to a
    different document/parse run (which would let one document's chunk tree leak
    into another's).
    """
    by_id: dict[str, Chunk] = {}
    for chunk in chunks:
        if chunk.chunk_id in by_id:
            raise ValueError(f"duplicate chunk_id {chunk.chunk_id!r}")
        by_id[chunk.chunk_id] = chunk

    for chunk in chunks:
        if chunk.parent_chunk_id is None:
            continue
        parent = by_id.get(chunk.parent_chunk_id)
        if parent is None:
            raise ValueError(
                f"chunk {chunk.chunk_id!r} references unknown parent {chunk.parent_chunk_id!r}"
            )
        if parent.document_id != chunk.document_id or parent.parse_run_id != chunk.parse_run_id:
            raise ValueError(
                f"chunk {chunk.chunk_id!r} parent {parent.chunk_id!r} belongs to a "
                "different document/parse run"
            )
