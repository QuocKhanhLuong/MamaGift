"""MinerU adapter.

MinerU is a heavyweight layout/reading-order candidate. It is never imported at
module scope and never installed in mandatory CI; contract tests exercise this
adapter through recorded provider output instead.

The provider-format converter is a pure function over MinerU's `middle.json`, so a
recorded artifact replays through exactly the same translation code as a live run.
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

ADAPTER_NAME = "mineru"


def _span_text(line: dict[str, Any]) -> str:
    return "".join(str(span.get("content", "")) for span in line.get("spans", []))


def convert_middle_json(middle_json: dict[str, Any]) -> list[ProviderPage]:
    """Translate MinerU `middle.json` into provider-neutral pages.

    MinerU reports a top-left origin in PDF points, which is already the canonical
    coordinate space, so bounding boxes pass through unchanged.
    """
    pages: list[ProviderPage] = []
    for index, page_info in enumerate(middle_json.get("pdf_info", [])):
        size = page_info.get("page_size", [595.0, 842.0])
        width, height = float(size[0]), float(size[1])

        blocks: list[ProviderBlock] = []
        raw_blocks = page_info.get("para_blocks") or page_info.get("preproc_blocks") or []
        for block_index, raw_block in enumerate(raw_blocks):
            lines = raw_block.get("lines", [])
            text = "\n".join(_span_text(line) for line in lines)

            attributes: dict[str, Any] = {}
            if raw_block.get("type") == "table":
                cells = raw_block.get("cells")
                if isinstance(cells, list):
                    attributes["cells"] = cells

            blocks.append(
                ProviderBlock(
                    provider_block_id=f"mineru-{index + 1}-{block_index}",
                    provider_type=str(raw_block.get("type", "text")),
                    text=text,
                    bbox=[float(value) for value in raw_block.get("bbox", [])] or None,
                    confidence=raw_block.get("score"),
                    order_hint=raw_block.get("index", block_index),
                    attributes=attributes,
                )
            )

        pages.append(
            ProviderPage(
                page_number=int(page_info.get("page_idx", index)) + 1,
                width=width,
                height=height,
                rotation=0,
                blocks=blocks,
            )
        )
    return pages


class MinerUAdapter(BaseDocumentParser):
    name = ADAPTER_NAME
    adapter_version = "1.0"
    provider_package = "mineru"
    capabilities = ParserCapabilities(
        born_digital_text=True,
        ocr=True,
        layout_analysis=True,
        reading_order=True,
        tables=True,
        headings=True,
        lists=True,
        bounding_boxes=True,
        confidence_scores=True,
        requires_gpu=False,
        benefits_from_gpu=True,
    )

    def provider_version(self) -> str | None:
        try:
            from importlib.metadata import version

            return version("mineru")
        except Exception:
            return None

    def parse(self, request: ParseRequest) -> ProviderParseResult:
        version = self.provider_version()
        if version is None:
            raise ParserError(
                ParserErrorCode.PROVIDER_UNAVAILABLE,
                "mineru is not installed; run this adapter outside mandatory CI",
                parser_name=self.name,
            )

        started_at = datetime.now(UTC)
        start = time.perf_counter()

        try:
            from mineru.cli.common import do_parse, read_fn
        except Exception as exc:
            raise ParserError(
                ParserErrorCode.PROVIDER_UNAVAILABLE,
                f"mineru is installed but its API could not be imported: {exc}",
                parser_name=self.name,
                details={"exception": type(exc).__name__},
            ) from exc

        try:
            middle_json = do_parse(
                read_fn(request.pdf_path),
                backend=self.configuration.get("backend", "pipeline"),
                lang=self.configuration.get("lang", "vi"),
                **self.configuration.get("extra", {}),
            )
        except Exception as exc:
            raise ParserError(
                ParserErrorCode.PROVIDER_FAILURE,
                f"mineru failed to parse the document: {exc}",
                parser_name=self.name,
                details={"exception": type(exc).__name__},
            ) from exc

        pages = convert_middle_json(middle_json)
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
            provider_artifact={"format": "mineru.middle.json"},
        )
