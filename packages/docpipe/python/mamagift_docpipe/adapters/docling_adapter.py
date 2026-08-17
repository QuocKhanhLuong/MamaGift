"""Docling adapter.

Docling reports geometry with a bottom-left origin, so this adapter flips the y axis
into the canonical top-left space before handing anything to the normalizer.
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

ADAPTER_NAME = "docling"


def _bbox_to_top_left(bbox: dict[str, Any], page_height: float) -> list[float]:
    """Convert a Docling bbox into the canonical top-left point space."""
    left = float(bbox["l"])
    right = float(bbox["r"])
    top = float(bbox["t"])
    bottom = float(bbox["b"])

    if str(bbox.get("coord_origin", "BOTTOMLEFT")).upper() == "TOPLEFT":
        return [left, min(top, bottom), right, max(top, bottom)]

    # Bottom-left origin: y grows upward, so the canonical top is height - max(y).
    return [left, page_height - max(top, bottom), right, page_height - min(top, bottom)]


def convert_docling_dict(payload: dict[str, Any]) -> list[ProviderPage]:
    """Translate a `DoclingDocument.export_to_dict()` payload into neutral pages."""
    raw_pages = payload.get("pages", {})
    page_sizes: dict[int, tuple[float, float]] = {}
    for key, page in raw_pages.items():
        size = page.get("size", {})
        page_no = int(page.get("page_no", key))
        page_sizes[page_no] = (float(size.get("width", 595.0)), float(size.get("height", 842.0)))

    items: dict[int, list[ProviderBlock]] = {number: [] for number in page_sizes}

    def add_item(item: dict[str, Any], kind: str, counter: int) -> None:
        for prov in item.get("prov", []):
            page_no = int(prov.get("page_no", 1))
            _, height = page_sizes.get(page_no, (595.0, 842.0))
            items.setdefault(page_no, [])

            attributes: dict[str, Any] = {}
            if kind == "table":
                grid = item.get("data", {}).get("grid")
                if isinstance(grid, list):
                    attributes["cells"] = [
                        [str(cell.get("text", "")) for cell in row] for row in grid
                    ]

            items[page_no].append(
                ProviderBlock(
                    provider_block_id=str(item.get("self_ref") or f"docling-{kind}-{counter}"),
                    provider_type=str(item.get("label", kind)),
                    text=str(item.get("text", "")),
                    bbox=_bbox_to_top_left(prov["bbox"], height) if prov.get("bbox") else None,
                    confidence=None,
                    order_hint=int(prov.get("charspan", [counter])[0])
                    if prov.get("charspan")
                    else counter,
                    attributes=attributes,
                )
            )

    for counter, item in enumerate(payload.get("texts", [])):
        add_item(item, "text", counter)
    for counter, item in enumerate(payload.get("tables", [])):
        add_item(item, "table", counter)
    for counter, item in enumerate(payload.get("pictures", [])):
        add_item(item, "picture", counter)

    pages: list[ProviderPage] = []
    for page_no in sorted(items):
        width, height = page_sizes.get(page_no, (595.0, 842.0))
        pages.append(
            ProviderPage(
                page_number=page_no,
                width=width,
                height=height,
                rotation=0,
                blocks=items[page_no],
            )
        )
    return pages


class DoclingAdapter(BaseDocumentParser):
    name = ADAPTER_NAME
    adapter_version = "1.0"
    provider_package = "docling"
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

            return version("docling")
        except Exception:
            return None

    def parse(self, request: ParseRequest) -> ProviderParseResult:
        if self.provider_version() is None:
            raise ParserError(
                ParserErrorCode.PROVIDER_UNAVAILABLE,
                "docling is not installed; run this adapter outside mandatory CI",
                parser_name=self.name,
            )

        started_at = datetime.now(UTC)
        start = time.perf_counter()

        try:
            from docling.document_converter import (
                DocumentConverter,
            )
        except Exception as exc:
            raise ParserError(
                ParserErrorCode.PROVIDER_UNAVAILABLE,
                f"docling is installed but its API could not be imported: {exc}",
                parser_name=self.name,
                details={"exception": type(exc).__name__},
            ) from exc

        try:
            converter = DocumentConverter()
            result = converter.convert(str(request.pdf_path))
            payload = result.document.export_to_dict()
        except Exception as exc:
            raise ParserError(
                ParserErrorCode.PROVIDER_FAILURE,
                f"docling failed to parse the document: {exc}",
                parser_name=self.name,
                details={"exception": type(exc).__name__},
            ) from exc

        pages = convert_docling_dict(payload)
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
            provider_artifact={"format": "docling.document.dict"},
        )
