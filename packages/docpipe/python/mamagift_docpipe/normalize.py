"""Normalize a raw `ProviderParseResult` into `CanonicalDocument` v1.

Normalization is a separate layer: it reads the raw provider artifact and produces a
new canonical object. It never mutates its input, never invents values, and marks
unavailable information as `None` rather than guessing
(`docs/03_DOCUMENT_PIPELINE.md` section 9).
"""

from __future__ import annotations

import re
import unicodedata

from pydantic import BaseModel, ConfigDict, Field

from .canonical import (
    SCHEMA_VERSION,
    BBox,
    BlockProvenance,
    BlockType,
    CanonicalBlock,
    CanonicalDocument,
    CanonicalPage,
    CanonicalTable,
    ParserRun,
    QualityReport,
)
from .errors import ParserError, ParserErrorCode
from .interface import ProviderBlock, ProviderPage, ProviderParseResult
from .router import InspectionReport, Route

NORMALIZER_VERSION = "1.0"

# Provider vocabularies differ; this is the shared alias table. Anything unmapped
# becomes `unknown` rather than being force-fitted into a plausible-looking type.
BLOCK_TYPE_ALIASES: dict[str, BlockType] = {
    "title": BlockType.TITLE,
    "doc_title": BlockType.TITLE,
    "document_title": BlockType.TITLE,
    "heading": BlockType.HEADING,
    "section_header": BlockType.HEADING,
    "section-header": BlockType.HEADING,
    "sectionheader": BlockType.HEADING,
    "sectionheading": BlockType.HEADING,
    "header_text": BlockType.HEADING,
    "paragraph_title": BlockType.HEADING,
    "sub_paragraph_title": BlockType.HEADING,
    "paragraph": BlockType.PARAGRAPH,
    "text": BlockType.PARAGRAPH,
    "plain_text": BlockType.PARAGRAPH,
    "body": BlockType.PARAGRAPH,
    "list_item": BlockType.LIST_ITEM,
    "list-item": BlockType.LIST_ITEM,
    "listitem": BlockType.LIST_ITEM,
    "list": BlockType.LIST_ITEM,
    "table": BlockType.TABLE,
    "table_body": BlockType.TABLE,
    "table_cell": BlockType.TABLE_CELL,
    "caption": BlockType.CAPTION,
    "table_caption": BlockType.CAPTION,
    "figure_caption": BlockType.CAPTION,
    "header": BlockType.HEADER,
    "page_header": BlockType.HEADER,
    "pageheader": BlockType.HEADER,
    "footer": BlockType.FOOTER,
    "page_footer": BlockType.FOOTER,
    "pagefooter": BlockType.FOOTER,
    "page_number": BlockType.PAGE_NUMBER,
    "pagenumber": BlockType.PAGE_NUMBER,
    "number": BlockType.PAGE_NUMBER,
    "signature": BlockType.SIGNATURE,
    "stamp": BlockType.STAMP_REGION,
    "stamp_region": BlockType.STAMP_REGION,
    "seal": BlockType.STAMP_REGION,
    "image": BlockType.IMAGE,
    "figure": BlockType.IMAGE,
    "picture": BlockType.IMAGE,
    "formula": BlockType.FORMULA,
    "equation": BlockType.FORMULA,
    "isolate_formula": BlockType.FORMULA,
}

_WHITESPACE_RUN = re.compile(r"[ \t  - ]+")
_BLANK_LINES = re.compile(r"\n{3,}")


class NormalizationOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Fraction of page height treated as the header/footer margin band when the
    # provider does not report header/footer types itself.
    margin_band_ratio: float = Field(default=0.07, ge=0.0, le=0.4)

    # Geometric header/footer classification is semantic cleanup, not raw provider
    # output, so it is opt-in and always recorded in block attributes.
    classify_margins: bool = True

    type_aliases: dict[str, BlockType] = Field(default_factory=dict)


def normalize_text(raw: str) -> str:
    """NFC-normalize and tidy whitespace without destroying source characters.

    Vietnamese diacritics survive: NFC composes them onto their base letters and no
    character class is ever stripped.
    """
    text = unicodedata.normalize("NFC", raw)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _WHITESPACE_RUN.sub(" ", text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    text = _BLANK_LINES.sub("\n\n", text)
    return text.strip()


def _map_block_type(
    provider_type: str,
    options: NormalizationOptions,
) -> BlockType:
    key = provider_type.strip().lower().replace(" ", "_")
    if key in options.type_aliases:
        return options.type_aliases[key]
    return BLOCK_TYPE_ALIASES.get(key, BlockType.UNKNOWN)


def _normalize_bbox(raw: list[float] | None) -> BBox | None:
    if raw is None:
        return None
    if len(raw) != 4:
        raise ParserError(
            ParserErrorCode.NORMALIZATION_FAILURE,
            f"bbox must have 4 values, got {len(raw)}",
            parser_name="normalizer",
        )
    x0, y0, x1, y1 = (float(value) for value in raw)
    return BBox(
        x0=max(0.0, min(x0, x1)),
        y0=max(0.0, min(y0, y1)),
        x1=max(0.0, max(x0, x1)),
        y1=max(0.0, max(y0, y1)),
    )


def _ordered_blocks(page: ProviderPage) -> tuple[list[ProviderBlock], str]:
    """Return blocks in reading order plus the strategy used to get there."""
    blocks = list(page.blocks)
    hints = [block.order_hint for block in blocks]
    if blocks and all(hint is not None for hint in hints) and len(set(hints)) == len(hints):
        return sorted(blocks, key=lambda block: block.order_hint or 0), "provider_order_hint"

    if blocks and all(block.bbox is not None and len(block.bbox) == 4 for block in blocks):
        return (
            sorted(
                blocks,
                key=lambda block: (
                    round((block.bbox or [0, 0, 0, 0])[1], 1),
                    round((block.bbox or [0, 0, 0, 0])[0], 1),
                ),
            ),
            "geometry_top_left",
        )

    return blocks, "provider_sequence"


def _margin_type(
    bbox: BBox | None,
    page_height: float,
    options: NormalizationOptions,
) -> BlockType | None:
    if bbox is None or not options.classify_margins or page_height <= 0:
        return None
    band = page_height * options.margin_band_ratio
    if bbox.y1 <= band:
        return BlockType.HEADER
    if bbox.y0 >= page_height - band:
        return BlockType.FOOTER
    return None


def _build_table(
    block: ProviderBlock,
    block_id: str,
    page_number: int,
    table_index: int,
) -> CanonicalTable | None:
    raw_cells = block.attributes.get("cells")
    if not isinstance(raw_cells, list):
        return None

    cells: list[list[str]] = []
    for row in raw_cells:
        if not isinstance(row, list):
            return None
        cells.append([normalize_text(str(cell)) for cell in row])

    n_cols = max((len(row) for row in cells), default=0)
    for row in cells:
        row.extend([""] * (n_cols - len(row)))

    caption = block.attributes.get("caption")
    return CanonicalTable(
        id=f"t_{page_number}_{table_index:04d}",
        page_number=page_number,
        block_id=block_id,
        n_rows=len(cells),
        n_cols=n_cols,
        cells=cells,
        caption=normalize_text(str(caption)) if isinstance(caption, str) else None,
    )


def normalize_provider_result(
    result: ProviderParseResult,
    inspection: InspectionReport | None = None,
    options: NormalizationOptions | None = None,
) -> CanonicalDocument:
    """Convert a raw provider artifact into `CanonicalDocument` v1.

    Block IDs are deterministic for a given provider result: `b_<page>_<index>`, where
    the index follows the resolved reading order. Two runs over identical provider
    output therefore produce byte-identical canonical documents apart from the parser
    run timestamps that the provider itself reported.
    """
    opts = options or NormalizationOptions()

    pages: list[CanonicalPage] = []
    tables: list[CanonicalTable] = []
    order_strategies: dict[int, str] = {}

    for provider_page in sorted(result.pages, key=lambda page: page.page_number):
        ordered, strategy = _ordered_blocks(provider_page)
        order_strategies[provider_page.page_number] = strategy

        blocks: list[CanonicalBlock] = []
        table_index = 0

        for index, provider_block in enumerate(ordered):
            block_id = f"b_{provider_page.page_number}_{index:04d}"
            bbox = _normalize_bbox(provider_block.bbox)
            block_type = _map_block_type(provider_block.provider_type, opts)

            attributes = dict(provider_block.attributes)
            attributes["provider_type"] = provider_block.provider_type

            if block_type in (BlockType.PARAGRAPH, BlockType.UNKNOWN):
                margin_type = _margin_type(bbox, provider_page.height, opts)
                if margin_type is not None:
                    block_type = margin_type
                    attributes["classified_by"] = "normalizer_geometry"

            confidence = provider_block.confidence
            if confidence is not None:
                confidence = min(1.0, max(0.0, float(confidence)))

            block = CanonicalBlock(
                id=block_id,
                type=block_type,
                text=normalize_text(provider_block.text),
                reading_order=index,
                bbox=bbox,
                confidence=confidence,
                parent_id=None,
                attributes=attributes,
                provenance=BlockProvenance(
                    page_number=provider_page.page_number,
                    provider_block_id=provider_block.provider_block_id,
                ),
            )
            blocks.append(block)

            if block_type == BlockType.TABLE:
                table = _build_table(
                    provider_block, block_id, provider_page.page_number, table_index
                )
                if table is not None:
                    tables.append(table)
                    table_index += 1

        pages.append(
            CanonicalPage(
                page_number=provider_page.page_number,
                width=provider_page.width,
                height=provider_page.height,
                rotation=provider_page.rotation,
                blocks=blocks,
            )
        )

    parser_run = ParserRun(
        id=f"prun_{result.adapter.name}_{result.adapter.configuration_hash}",
        parser_name=result.adapter.name,
        parser_version=result.adapter.provider_version or result.adapter.adapter_version,
        configuration_hash=result.adapter.configuration_hash,
        started_at=result.started_at,
        finished_at=result.finished_at,
        device=result.device,
    )

    warnings = list(result.warnings)
    if inspection is not None:
        warnings.extend(inspection.warnings)

    quality_report = QualityReport(
        route=inspection.route.value if inspection is not None else Route.BORN_DIGITAL.value,
        route_confidence=inspection.route_confidence if inspection is not None else 0.0,
        text_quality_score=None,
        structure_quality_score=None,
        critical_field_warnings=[],
        warnings=warnings,
        requires_user_review=bool(result.errors) or bool(warnings),
    )

    return CanonicalDocument(
        schema_version=SCHEMA_VERSION,
        document_id=result.document_id,
        parser_run=parser_run,
        metadata={
            "normalizer_version": NORMALIZER_VERSION,
            "adapter": result.adapter.model_dump(mode="json"),
            "reading_order_strategy": order_strategies,
            "provider_duration_ms": result.duration_ms,
            "router": None if inspection is None else inspection.model_dump(mode="json"),
        },
        pages=pages,
        hierarchy=[],
        tables=tables,
        extracted_fields=[],
        quality_report=quality_report,
    )
