"""Shared paths and builders for the Phase 1 parser test suites."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mamagift_docpipe.interface import (
    AdapterMetadata,
    ParserCapabilities,
    ProviderBlock,
    ProviderPage,
    ProviderParseResult,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = REPO_ROOT / "benchmarks/parser/fixtures"
GROUND_TRUTH = REPO_ROOT / "benchmarks/parser/ground_truth"
MANIFEST = REPO_ROOT / "benchmarks/parser/manifest.jsonl"
RECORDINGS = Path(__file__).parent / "fixtures/recordings"

RECORDED_PARSERS = ("mineru", "marker", "docling", "ppstructure")
ALL_PARSERS = ("pymupdf", *RECORDED_PARSERS)


def make_adapter_metadata(name: str = "fake", **overrides: Any) -> AdapterMetadata:
    payload: dict[str, Any] = {
        "name": name,
        "adapter_version": "1.0",
        "provider_package": None,
        "provider_version": "0.0.0",
        "capabilities": ParserCapabilities(born_digital_text=True),
        "configuration": {},
        "configuration_hash": "testhash",
    }
    payload.update(overrides)
    return AdapterMetadata(**payload)


def make_provider_result(
    pages: list[ProviderPage],
    document_id: str = "doc_test",
    **overrides: Any,
) -> ProviderParseResult:
    payload: dict[str, Any] = {
        "document_id": document_id,
        "adapter": make_adapter_metadata(),
        "device": "cpu",
        "started_at": "2026-01-01T00:00:00+00:00",
        "finished_at": "2026-01-01T00:00:01+00:00",
        "duration_ms": 1000.0,
        "pages": pages,
        "warnings": [],
        "errors": [],
        "provider_artifact": {},
    }
    payload.update(overrides)
    return ProviderParseResult(**payload)


def make_block(
    block_id: str,
    text: str,
    provider_type: str = "text",
    bbox: list[float] | None = None,
    order_hint: int | None = None,
    **overrides: Any,
) -> ProviderBlock:
    payload: dict[str, Any] = {
        "provider_block_id": block_id,
        "provider_type": provider_type,
        "text": text,
        "bbox": bbox,
        "order_hint": order_hint,
    }
    payload.update(overrides)
    return ProviderBlock(**payload)


def make_page(
    blocks: list[ProviderBlock],
    page_number: int = 1,
    width: float = 595.0,
    height: float = 842.0,
    rotation: int = 0,
) -> ProviderPage:
    return ProviderPage(
        page_number=page_number,
        width=width,
        height=height,
        rotation=rotation,
        blocks=blocks,
    )
