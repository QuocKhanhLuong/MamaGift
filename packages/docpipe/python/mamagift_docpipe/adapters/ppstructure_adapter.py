"""PaddleOCR / PP-StructureV3 adapter.

The OCR specialist candidate, expected to matter most on the scanned route. Its
geometry is reported in rendered-image pixels, so boxes are scaled into PDF points
whenever the page size in points is known.
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

ADAPTER_NAME = "ppstructure"


def convert_ppstructure_pages(
    raw_pages: list[dict[str, Any]],
    page_sizes: dict[int, tuple[float, float]] | None = None,
) -> list[ProviderPage]:
    """Translate PP-StructureV3 per-page results into provider-neutral pages.

    `page_sizes` maps page number to (width, height) in PDF points. When a page is
    absent the pixel geometry is kept as-is rather than scaled by a guessed DPI.
    """
    sizes = page_sizes or {}
    pages: list[ProviderPage] = []

    for index, raw_page in enumerate(raw_pages):
        page_number = int(raw_page.get("page_index", index)) + (
            0 if "page_index" not in raw_page else 1
        )
        if "page_index" not in raw_page:
            page_number = index + 1

        image_size = raw_page.get("input_img_size") or raw_page.get("image_size") or [1, 1]
        pixel_width = float(image_size[0]) or 1.0
        pixel_height = float(image_size[1]) or 1.0

        if page_number in sizes:
            width, height = sizes[page_number]
            scale_x = width / pixel_width
            scale_y = height / pixel_height
        else:
            width, height = pixel_width, pixel_height
            scale_x = scale_y = 1.0

        blocks: list[ProviderBlock] = []
        for block_index, block in enumerate(raw_page.get("parsing_res_list", [])):
            raw_bbox = block.get("block_bbox")
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
            cells = block.get("block_cells")
            if isinstance(cells, list):
                attributes["cells"] = cells

            blocks.append(
                ProviderBlock(
                    provider_block_id=f"ppstructure-{page_number}-{block_index}",
                    provider_type=str(block.get("block_label", "text")),
                    text=str(block.get("block_content", "")),
                    bbox=scaled,
                    confidence=block.get("block_score"),
                    order_hint=block_index,
                    attributes=attributes,
                )
            )

        pages.append(
            ProviderPage(
                page_number=page_number,
                width=width,
                height=height,
                rotation=0,
                blocks=blocks,
            )
        )
    return pages


class PPStructureAdapter(BaseDocumentParser):
    name = ADAPTER_NAME
    adapter_version = "1.0"
    provider_package = "paddleocr"
    capabilities = ParserCapabilities(
        born_digital_text=True,
        ocr=True,
        layout_analysis=True,
        reading_order=True,
        tables=True,
        headings=True,
        lists=False,
        bounding_boxes=True,
        confidence_scores=True,
        requires_gpu=False,
        benefits_from_gpu=True,
    )

    def provider_version(self) -> str | None:
        try:
            from importlib.metadata import version

            return version("paddleocr")
        except Exception:
            return None

    def parse(self, request: ParseRequest) -> ProviderParseResult:
        if self.provider_version() is None:
            raise ParserError(
                ParserErrorCode.PROVIDER_UNAVAILABLE,
                "paddleocr is not installed; run this adapter outside mandatory CI",
                parser_name=self.name,
            )

        started_at = datetime.now(UTC)
        start = time.perf_counter()

        try:
            from paddleocr import PPStructureV3
        except Exception as exc:
            raise ParserError(
                ParserErrorCode.PROVIDER_UNAVAILABLE,
                f"paddleocr is installed but PP-StructureV3 could not be imported: {exc}",
                parser_name=self.name,
                details={"exception": type(exc).__name__},
            ) from exc

        try:
            pipeline = PPStructureV3(
                lang=self.configuration.get("lang", "vi"),
                device=self.device(),
                **self.configuration.get("extra", {}),
            )
            output = pipeline.predict(input=str(request.pdf_path))
            raw_pages = [item.json["res"] if hasattr(item, "json") else item for item in output]
        except Exception as exc:
            raise ParserError(
                ParserErrorCode.PROVIDER_FAILURE,
                f"PP-StructureV3 failed to parse the document: {exc}",
                parser_name=self.name,
                details={"exception": type(exc).__name__},
            ) from exc

        pages = convert_ppstructure_pages(raw_pages, _page_sizes_in_points(request.pdf_path))
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
            provider_artifact={"format": "ppstructurev3.parsing_res_list"},
        )


def _page_sizes_in_points(pdf_path: Any) -> dict[int, tuple[float, float]]:
    """Read page sizes with the low-level PDF utility so OCR boxes can be rescaled."""
    try:
        import pymupdf
    except ImportError:
        return {}

    sizes: dict[int, tuple[float, float]] = {}
    with pymupdf.open(pdf_path) as document:
        for index in range(document.page_count):
            rect = document.load_page(index).rect
            sizes[index + 1] = (float(rect.width), float(rect.height))
    return sizes
