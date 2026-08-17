"""CanonicalDocument v1 — the provider-neutral document representation.

The schema follows `docs/08_API_AND_DATA_CONTRACTS.md` sections 5-10. Its version is
independent of the REST API version; breaking changes require a new schema version
plus updated fixtures and contract tests.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = "1.0"

VALID_ROTATIONS = (0, 90, 180, 270)


class BlockType(StrEnum):
    TITLE = "title"
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    LIST_ITEM = "list_item"
    TABLE = "table"
    TABLE_CELL = "table_cell"
    CAPTION = "caption"
    HEADER = "header"
    FOOTER = "footer"
    PAGE_NUMBER = "page_number"
    SIGNATURE = "signature"
    STAMP_REGION = "stamp_region"
    IMAGE = "image"
    FORMULA = "formula"
    UNKNOWN = "unknown"


class HierarchyKind(StrEnum):
    CHAPTER = "chapter"
    SECTION = "section"
    ARTICLE = "article"
    CLAUSE = "clause"
    POINT = "point"
    APPENDIX = "appendix"
    CUSTOM_HEADING = "custom_heading"


class ReviewStatus(StrEnum):
    UNREVIEWED = "unreviewed"
    NEEDS_REVIEW = "needs_review"
    CONFIRMED = "confirmed"
    CORRECTED = "corrected"
    REJECTED = "rejected"


class BBox(BaseModel):
    """Bounding box in the canonical per-page coordinate space.

    Origin is the top-left corner of the *unrotated* page, units are PDF points,
    x grows right and y grows down. Provider-specific spaces are normalized before
    a `BBox` is constructed.
    """

    model_config = ConfigDict(extra="forbid")

    x0: float = Field(ge=0.0)
    y0: float = Field(ge=0.0)
    x1: float = Field(ge=0.0)
    y1: float = Field(ge=0.0)

    @model_validator(mode="after")
    def _validate_ordering(self) -> Self:
        if self.x1 < self.x0 or self.y1 < self.y0:
            raise ValueError("bbox requires x0 <= x1 and y0 <= y1")
        return self

    def as_list(self) -> list[float]:
        return [self.x0, self.y0, self.x1, self.y1]


class BlockProvenance(BaseModel):
    """Where a canonical block came from. Never optional."""

    model_config = ConfigDict(extra="forbid")

    page_number: int = Field(ge=1)
    provider_block_id: str | None = None


class CanonicalBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    type: BlockType
    text: str
    reading_order: int = Field(ge=0)
    bbox: BBox | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    parent_id: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    provenance: BlockProvenance


class CanonicalPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page_number: int = Field(ge=1)
    width: float = Field(gt=0.0)
    height: float = Field(gt=0.0)
    rotation: int = 0
    blocks: list[CanonicalBlock] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_page(self) -> Self:
        if self.rotation not in VALID_ROTATIONS:
            raise ValueError(f"rotation must be one of {VALID_ROTATIONS}, got {self.rotation}")

        seen_orders: set[int] = set()
        for block in self.blocks:
            if block.reading_order in seen_orders:
                raise ValueError(
                    f"duplicate reading_order {block.reading_order} on page {self.page_number}"
                )
            seen_orders.add(block.reading_order)

            if block.provenance.page_number != self.page_number:
                raise ValueError(
                    f"block {block.id} provenance page {block.provenance.page_number} "
                    f"does not match page {self.page_number}"
                )
        return self


class HierarchyNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    kind: HierarchyKind
    label: str
    text: str = ""
    parent_id: str | None = None
    source_block_ids: list[str] = Field(default_factory=list)
    ordinal: int | None = None


class CanonicalTable(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    page_number: int = Field(ge=1)
    block_id: str = Field(min_length=1)
    n_rows: int = Field(ge=0)
    n_cols: int = Field(ge=0)
    cells: list[list[str]] = Field(default_factory=list)
    caption: str | None = None

    @model_validator(mode="after")
    def _validate_shape(self) -> Self:
        if len(self.cells) != self.n_rows:
            raise ValueError(f"table {self.id} declares {self.n_rows} rows, has {len(self.cells)}")
        for index, row in enumerate(self.cells):
            if len(row) != self.n_cols:
                raise ValueError(
                    f"table {self.id} row {index} has {len(row)} cells, expected {self.n_cols}"
                )
        return self


class Extractor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    version: str = Field(min_length=1)


class ExtractedField(BaseModel):
    """A field derived from canonical blocks; never invented when unavailable."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    raw_value: str | None = None
    normalized_value: str | None = None
    value_type: str = "string"
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    review_status: ReviewStatus = ReviewStatus.UNREVIEWED
    source_block_ids: list[str] = Field(default_factory=list)
    source_page_numbers: list[int] = Field(default_factory=list)
    extractor: Extractor


class QualityReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    route: str
    route_confidence: float = Field(ge=0.0, le=1.0)
    text_quality_score: float | None = Field(default=None, ge=0.0, le=1.0)
    structure_quality_score: float | None = Field(default=None, ge=0.0, le=1.0)
    critical_field_warnings: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    requires_user_review: bool = False


class ParserRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    parser_name: str = Field(min_length=1)
    parser_version: str = Field(min_length=1)
    configuration_hash: str = Field(min_length=1)
    started_at: str = Field(min_length=1)
    finished_at: str = Field(min_length=1)
    device: str = "cpu"


class CanonicalDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = SCHEMA_VERSION
    document_id: str = Field(min_length=1)
    parser_run: ParserRun
    metadata: dict[str, Any] = Field(default_factory=dict)
    pages: list[CanonicalPage] = Field(default_factory=list)
    hierarchy: list[HierarchyNode] = Field(default_factory=list)
    tables: list[CanonicalTable] = Field(default_factory=list)
    extracted_fields: list[ExtractedField] = Field(default_factory=list)
    quality_report: QualityReport

    @model_validator(mode="after")
    def _validate_document(self) -> Self:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(f"unsupported schema_version {self.schema_version!r}")

        expected_page_numbers = list(range(1, len(self.pages) + 1))
        actual_page_numbers = [page.page_number for page in self.pages]
        if actual_page_numbers != expected_page_numbers:
            raise ValueError(
                f"pages must be numbered 1..n in order, got {actual_page_numbers}",
            )

        block_ids: set[str] = set()
        for page in self.pages:
            for block in page.blocks:
                if block.id in block_ids:
                    raise ValueError(f"duplicate block id {block.id}")
                block_ids.add(block.id)

        hierarchy_ids: set[str] = set()
        for node in self.hierarchy:
            if node.id in hierarchy_ids:
                raise ValueError(f"duplicate hierarchy id {node.id}")
            hierarchy_ids.add(node.id)

        known_parents = block_ids | hierarchy_ids
        for page in self.pages:
            for block in page.blocks:
                if block.parent_id is not None and block.parent_id not in known_parents:
                    raise ValueError(
                        f"block {block.id} references unknown parent {block.parent_id}"
                    )

        for node in self.hierarchy:
            if node.parent_id is not None and node.parent_id not in hierarchy_ids:
                raise ValueError(f"hierarchy {node.id} references unknown parent {node.parent_id}")
            for source_id in node.source_block_ids:
                if source_id not in block_ids:
                    raise ValueError(f"hierarchy {node.id} references unknown block {source_id}")

        page_numbers = set(actual_page_numbers)
        for table in self.tables:
            if table.page_number not in page_numbers:
                raise ValueError(f"table {table.id} references unknown page {table.page_number}")
            if table.block_id not in block_ids:
                raise ValueError(f"table {table.id} references unknown block {table.block_id}")

        for field in self.extracted_fields:
            for source_id in field.source_block_ids:
                if source_id not in block_ids:
                    raise ValueError(f"field {field.id} references unknown block {source_id}")
            for page_number in field.source_page_numbers:
                if page_number not in page_numbers:
                    raise ValueError(f"field {field.id} references unknown page {page_number}")

        return self

    def iter_blocks(self) -> list[CanonicalBlock]:
        """Every block in document reading order (page order, then reading_order)."""
        blocks: list[CanonicalBlock] = []
        for page in self.pages:
            blocks.extend(sorted(page.blocks, key=lambda block: block.reading_order))
        return blocks

    def text_by_page(self) -> dict[int, str]:
        return {
            page.page_number: "\n".join(
                block.text
                for block in sorted(page.blocks, key=lambda block: block.reading_order)
                if block.text
            )
            for page in self.pages
        }
