"""Marker adapter.

Marker is a born-digital conversion candidate with optional LLM-assisted repair. The
LLM path is disabled by default here: the benchmark must not acquire a hidden paid
API dependency (`docs/04_PHASE_PLAN.md` global rule 6).
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

from ..errors import ParserError, ParserErrorCode
from ..interface import (
    BaseDocumentParser,
    ParserCapabilities,
    ParseRequest,
    ProviderBlock,
    ProviderPage,
    ProviderParseResult,
)

ADAPTER_NAME = "marker"


def _polygon_to_bbox(polygon: list[list[float]] | None) -> list[float] | None:
    if not polygon:
        return None
    xs = [float(point[0]) for point in polygon]
    ys = [float(point[1]) for point in polygon]
    return [min(xs), min(ys), max(xs), max(ys)]


def convert_marker_json(rendered: dict[str, Any]) -> list[ProviderPage]:
    """Translate Marker's JSON render into provider-neutral pages.

    Marker reports geometry in rendered-image pixels with a top-left origin. When the
    page also reports its point size the boxes are scaled into PDF points; otherwise
    they are passed through and the scale is left unrecorded rather than guessed.
    """
    pages: list[ProviderPage] = []
    for index, page in enumerate(rendered.get("children", [])):
        bbox = page.get("bbox") or [0.0, 0.0, 612.0, 792.0]
        pixel_width = float(bbox[2]) - float(bbox[0]) or 1.0
        pixel_height = float(bbox[3]) - float(bbox[1]) or 1.0

        point_size = page.get("page_size")
        if point_size:
            width, height = float(point_size[0]), float(point_size[1])
            scale_x = width / pixel_width
            scale_y = height / pixel_height
        else:
            width, height = pixel_width, pixel_height
            scale_x = scale_y = 1.0

        blocks: list[ProviderBlock] = []
        for block_index, block in enumerate(page.get("children") or []):
            raw_bbox = _polygon_to_bbox(block.get("polygon")) or block.get("bbox")
            scaled = (
                [
                    float(raw_bbox[0]) * scale_x,
                    float(raw_bbox[1]) * scale_y,
                    float(raw_bbox[2]) * scale_x,
                    float(raw_bbox[3]) * scale_y,
                ]
                if raw_bbox
                else None
            )

            attributes: dict[str, Any] = {}
            if block.get("block_type", "").lower() == "table":
                cells = block.get("cells")
                if isinstance(cells, list):
                    attributes["cells"] = cells

            blocks.append(
                ProviderBlock(
                    provider_block_id=str(block.get("id") or f"marker-{index + 1}-{block_index}"),
                    provider_type=str(block.get("block_type", "text")),
                    text=str(block.get("text") or block.get("html") or ""),
                    bbox=scaled,
                    confidence=None,
                    order_hint=block_index,
                    attributes=attributes,
                )
            )

        pages.append(
            ProviderPage(
                page_number=index + 1,
                width=width,
                height=height,
                rotation=0,
                blocks=blocks,
            )
        )
    return pages


class MarkerAdapter(BaseDocumentParser):
    name = ADAPTER_NAME
    adapter_version = "1.0"
    provider_package = "marker-pdf"
    capabilities = ParserCapabilities(
        born_digital_text=True,
        ocr=True,
        layout_analysis=True,
        reading_order=True,
        tables=True,
        headings=True,
        lists=True,
        bounding_boxes=True,
        confidence_scores=False,
        requires_gpu=False,
        benefits_from_gpu=True,
    )

    def provider_version(self) -> str | None:
        try:
            from importlib.metadata import version

            return version("marker-pdf")
        except Exception:
            return None

    def parse(self, request: ParseRequest) -> ProviderParseResult:
        if self.provider_version() is None:
            raise ParserError(
                ParserErrorCode.PROVIDER_UNAVAILABLE,
                "marker-pdf is not installed; run this adapter outside mandatory CI",
                parser_name=self.name,
            )

        if self.configuration.get("use_llm"):
            raise ParserError(
                ParserErrorCode.UNSUPPORTED_INPUT,
                "marker use_llm requires an external API and is excluded from the benchmark",
                parser_name=self.name,
            )

        started_at = datetime.now(UTC)
        start = time.perf_counter()

        try:
            from marker.converters.pdf import PdfConverter
            from marker.models import create_model_dict
            from marker.output import output_from_string
        except Exception as exc:
            raise ParserError(
                ParserErrorCode.PROVIDER_UNAVAILABLE,
                f"marker-pdf is installed but its API could not be imported: {exc}",
                parser_name=self.name,
                details={"exception": type(exc).__name__},
            ) from exc

        try:
            converter = PdfConverter(
                artifact_dict=create_model_dict(),
                config={"output_format": "json", **self.configuration.get("extra", {})},
            )
            rendered = converter(str(request.pdf_path))
            payload = output_from_string(rendered)
        except Exception as exc:
            raise ParserError(
                ParserErrorCode.PROVIDER_FAILURE,
                f"marker failed to parse the document: {exc}",
                parser_name=self.name,
                details={"exception": type(exc).__name__},
            ) from exc

        pages = convert_marker_json(payload)
        duration_ms = (time.perf_counter() - start) * 1000.0

        return ProviderParseResult(
            document_id=request.document_id,
            adapter=self.metadata,
            device=self.device(),
            started_at=started_at.isoformat(),
            finished_at=datetime.now(UTC).isoformat(),
            duration_ms=duration_ms,
            pages=pages,
            warnings=[],
            errors=[],
            provider_artifact={"format": "marker.json"},
        )
