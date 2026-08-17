"""PyMuPDF baseline adapter.

PyMuPDF is the documented low-level baseline and PDF utility. It is the one adapter
light enough to run end to end inside mandatory CI, so it also serves as the
lightweight smoke path. It is not a production candidate unless benchmark evidence
promotes it.
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

ADAPTER_NAME = "pymupdf"


class PyMuPDFAdapter(BaseDocumentParser):
    """Extracts the existing text layer. No OCR, no layout model."""

    name = ADAPTER_NAME
    adapter_version = "1.0"
    provider_package = "pymupdf"
    capabilities = ParserCapabilities(
        born_digital_text=True,
        ocr=False,
        layout_analysis=False,
        reading_order=False,
        tables=False,
        headings=False,
        lists=False,
        bounding_boxes=True,
        confidence_scores=False,
        requires_gpu=False,
        benefits_from_gpu=False,
    )

    def provider_version(self) -> str | None:
        try:
            import pymupdf
        except ImportError:
            return None
        # pymupdf.version is (pymupdf_version, mupdf_version, build_date).
        return f"{pymupdf.version[0]} (mupdf {pymupdf.version[1]})"

    def parse(self, request: ParseRequest) -> ProviderParseResult:
        try:
            import pymupdf
        except ImportError as exc:
            raise ParserError(
                ParserErrorCode.PROVIDER_UNAVAILABLE,
                "pymupdf is not installed",
                parser_name=self.name,
            ) from exc

        if not request.pdf_path.is_file():
            raise ParserError(
                ParserErrorCode.UNSUPPORTED_INPUT,
                f"input file not found: {request.pdf_path}",
                parser_name=self.name,
            )

        started_at = datetime.now(UTC)
        start = time.perf_counter()
        warnings: list[str] = []

        try:
            document = pymupdf.open(request.pdf_path)
        except Exception as exc:
            raise ParserError(
                ParserErrorCode.INVALID_PDF,
                f"pymupdf could not open the document: {exc}",
                parser_name=self.name,
                details={"exception": type(exc).__name__},
            ) from exc

        with document:
            if document.needs_pass:
                raise ParserError(
                    ParserErrorCode.ENCRYPTED_PDF,
                    "document is password protected",
                    parser_name=self.name,
                )

            page_count = document.page_count
            if request.page_limit is not None:
                page_count = min(page_count, request.page_limit)

            pages: list[ProviderPage] = []
            for index in range(page_count):
                page = document.load_page(index)
                rect = page.rect
                blocks: list[ProviderBlock] = []

                raw_blocks = page.get_text("dict").get("blocks", [])
                for block_index, raw_block in enumerate(raw_blocks):
                    block_type = "image" if raw_block.get("type") == 1 else "text"
                    text = _block_text(raw_block)
                    if block_type == "text" and not text.strip():
                        continue

                    bbox = [float(value) for value in raw_block.get("bbox", (0, 0, 0, 0))]
                    attributes: dict[str, Any] = {
                        "line_count": len(raw_block.get("lines", [])),
                    }
                    blocks.append(
                        ProviderBlock(
                            provider_block_id=f"pymupdf-{index + 1}-{block_index}",
                            provider_type=block_type,
                            text=text,
                            bbox=bbox,
                            confidence=None,
                            order_hint=raw_block.get("number", block_index),
                            attributes=attributes,
                        )
                    )

                if not blocks:
                    warnings.append(f"page {index + 1} produced no text blocks")

                pages.append(
                    ProviderPage(
                        page_number=index + 1,
                        width=float(rect.width),
                        height=float(rect.height),
                        rotation=int(page.rotation),
                        blocks=blocks,
                    )
                )

        duration_ms = (time.perf_counter() - start) * 1000.0
        return ProviderParseResult(
            document_id=request.document_id,
            adapter=self.metadata,
            device="cpu",
            started_at=started_at.isoformat(),
            finished_at=datetime.now(UTC).isoformat(),
            duration_ms=duration_ms,
            pages=pages,
            warnings=warnings,
            errors=[],
            provider_artifact={"extraction_mode": "dict"},
        )


def _block_text(raw_block: dict[str, Any]) -> str:
    lines: list[str] = []
    for line in raw_block.get("lines", []):
        spans = [span.get("text", "") for span in line.get("spans", [])]
        lines.append("".join(spans))
    return "\n".join(lines)
