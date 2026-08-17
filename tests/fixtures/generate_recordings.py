"""Generate synthetic provider recordings for adapter contract tests.

IMPORTANT — these are **not** benchmark evidence.

They are hand-authored payloads in each provider's own output vocabulary, used to
prove that every adapter normalizes into a valid `CanonicalDocument` with intact
provenance on a CPU-only CI runner. They say nothing about how MinerU, Marker,
Docling or PP-StructureV3 actually perform on Vietnamese documents, and no benchmark
number may ever be derived from them.

Real recordings captured from real provider runs belong in
`benchmarks/parser/recordings/`, not here.

Run with:

    uv run python tests/fixtures/generate_recordings.py
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

RECORDINGS = Path(__file__).parent / "recordings"
DOCUMENT_ID = "contract_fixture"

PAGE_WIDTH = 595.0
PAGE_HEIGHT = 842.0

# One shared logical document, expressed below in each provider's own vocabulary.
LOGICAL_BLOCKS = [
    ("header", "Công văn số 1234/UBND-VP", [72.0, 30.0, 300.0, 44.0]),
    ("title", "V/v hướng dẫn nộp hồ sơ tuyển sinh", [72.0, 110.0, 500.0, 126.0]),
    ("heading", "Điều 1. Phạm vi điều chỉnh", [72.0, 150.0, 400.0, 166.0]),
    (
        "paragraph",
        "Quyết định này quy định việc lập hồ sơ hành chính.",
        [72.0, 180.0, 520.0, 196.0],
    ),
    ("list_item", "1. Niêm yết công khai chỉ tiêu tuyển sinh.", [72.0, 210.0, 480.0, 226.0]),
    ("list_item", "2. Tiếp nhận hồ sơ trực tiếp và trực tuyến.", [72.0, 236.0, 480.0, 252.0]),
    ("table", "", [72.0, 280.0, 520.0, 360.0]),
    ("footer", "Trang 1/1", [72.0, 800.0, 200.0, 814.0]),
]

TABLE_CELLS = [
    ["STT", "Tên hồ sơ", "Thời hạn lưu"],
    ["1", "Hồ sơ tuyển sinh", "05 năm"],
    ["2", "Hồ sơ thi đua", "10 năm"],
]

# Each provider names the same concepts differently; the normalizer's alias table is
# exactly what these recordings exercise.
PROVIDER_VOCABULARY: dict[str, dict[str, str]] = {
    "mineru": {
        "header": "text",
        "title": "title",
        "heading": "title",
        "paragraph": "text",
        "list_item": "list",
        "table": "table",
        "footer": "text",
    },
    "marker": {
        "header": "PageHeader",
        "title": "Title",
        "heading": "SectionHeader",
        "paragraph": "Text",
        "list_item": "ListItem",
        "table": "Table",
        "footer": "PageFooter",
    },
    "docling": {
        "header": "page_header",
        "title": "title",
        "heading": "section_header",
        "paragraph": "text",
        "list_item": "list_item",
        "table": "table",
        "footer": "page_footer",
    },
    "ppstructure": {
        "header": "header",
        "title": "doc_title",
        "heading": "paragraph_title",
        "paragraph": "text",
        "list_item": "text",
        "table": "table",
        "footer": "footer",
    },
}

PROVIDER_PACKAGES = {
    "mineru": "mineru",
    "marker": "marker-pdf",
    "docling": "docling",
    "ppstructure": "paddleocr",
}

CAPABILITIES = {
    "born_digital_text": True,
    "ocr": True,
    "layout_analysis": True,
    "reading_order": True,
    "tables": True,
    "headings": True,
    "lists": True,
    "bounding_boxes": True,
    "confidence_scores": False,
    "requires_gpu": False,
    "benefits_from_gpu": True,
}


def build_recording(parser_name: str) -> dict[str, Any]:
    vocabulary = PROVIDER_VOCABULARY[parser_name]

    blocks: list[dict[str, Any]] = []
    for index, (kind, text, bbox) in enumerate(LOGICAL_BLOCKS):
        attributes: dict[str, Any] = {}
        if kind == "table":
            attributes["cells"] = TABLE_CELLS
        blocks.append(
            {
                "provider_block_id": f"{parser_name}-1-{index}",
                "provider_type": vocabulary[kind],
                "text": text,
                "bbox": bbox,
                "confidence": None,
                "order_hint": index,
                "attributes": attributes,
            }
        )

    return {
        "document_id": DOCUMENT_ID,
        "adapter": {
            "name": parser_name,
            "adapter_version": "1.0",
            "contract_version": "1.0",
            "provider_package": PROVIDER_PACKAGES[parser_name],
            "provider_version": None,
            "capabilities": CAPABILITIES,
            "configuration": {},
            "configuration_hash": "contractfixture",
        },
        "device": "cpu",
        "started_at": "2026-01-01T00:00:00+00:00",
        "finished_at": "2026-01-01T00:00:01+00:00",
        "duration_ms": 1000.0,
        "pages": [
            {
                "page_number": 1,
                "width": PAGE_WIDTH,
                "height": PAGE_HEIGHT,
                "rotation": 0,
                "blocks": blocks,
            }
        ],
        "warnings": [],
        "errors": [],
        "provider_artifact": {
            "synthetic_contract_fixture": True,
            "not_benchmark_evidence": True,
        },
    }


def main() -> int:
    for parser_name in PROVIDER_VOCABULARY:
        directory = RECORDINGS / parser_name
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"{DOCUMENT_ID}.json").write_text(
            json.dumps(build_recording(parser_name), ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
    print(f"Wrote {len(PROVIDER_VOCABULARY)} synthetic contract recordings to {RECORDINGS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
