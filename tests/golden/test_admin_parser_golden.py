"""Golden tests for the Vietnamese administrative parser.

Fixtures under `tests/fixtures/admin/` are authored by hand: the input is an invented
document, and the expectations were written from that authored text, never from
parser output. Deriving expectations from the parser would make it grade itself.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mamagift_docpipe import (
    BlockProvenance,
    BlockType,
    CanonicalBlock,
    CanonicalDocument,
    CanonicalPage,
    ParserRun,
    QualityReport,
    parse_admin_document,
)

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "admin"
CASES = sorted(path.name.removesuffix(".input.json") for path in FIXTURE_DIR.glob("*.input.json"))

pytestmark = pytest.mark.golden


def _load(name: str, suffix: str) -> dict:
    return json.loads((FIXTURE_DIR / f"{name}.{suffix}.json").read_text(encoding="utf-8"))


def _canonical_from_input(payload: dict) -> CanonicalDocument:
    pages = []
    for page in payload["pages"]:
        blocks = [
            CanonicalBlock(
                id=f"b_{page['page_number']}_{index:04d}",
                type=BlockType(block["type"]),
                text=block["text"],
                reading_order=index,
                provenance=BlockProvenance(page_number=page["page_number"]),
            )
            for index, block in enumerate(page["blocks"])
        ]
        pages.append(
            CanonicalPage(page_number=page["page_number"], width=595.0, height=842.0, blocks=blocks)
        )

    return CanonicalDocument(
        document_id=payload["document_id"],
        parser_run=ParserRun(
            id="prun_golden",
            parser_name="golden-fixture",
            parser_version="1.0",
            configuration_hash="0" * 16,
            started_at="2026-01-01T00:00:00+00:00",
            finished_at="2026-01-01T00:00:01+00:00",
        ),
        pages=pages,
        quality_report=QualityReport(route="born_digital", route_confidence=1.0),
    )


@pytest.fixture(params=CASES)
def case(request: pytest.FixtureRequest) -> tuple[CanonicalDocument, dict]:
    name = request.param
    document = parse_admin_document(_canonical_from_input(_load(name, "input")))
    return document, _load(name, "expected")


def test_block_types_match_golden(case: tuple[CanonicalDocument, dict]) -> None:
    document, expected = case
    actual = {block.id: block.type.value for block in document.iter_blocks()}
    for block_id, block_type in expected["block_types"].items():
        assert actual[block_id] == block_type, block_id


def test_hierarchy_matches_golden(case: tuple[CanonicalDocument, dict]) -> None:
    document, expected = case
    actual = {node.id: node for node in document.hierarchy}

    assert [node.id for node in document.hierarchy] == [
        node["id"] for node in expected["hierarchy"]
    ]

    for node in expected["hierarchy"]:
        found = actual[node["id"]]
        assert found.kind.value == node["kind"]
        assert found.label == node["label"]
        assert found.parent_id == node["parent_id"]
        assert found.source_block_ids == node["source_block_ids"]
        if "ordinal" in node:
            assert found.ordinal == node["ordinal"]


def test_recipients_are_captured(case: tuple[CanonicalDocument, dict]) -> None:
    document, expected = case
    recipients = [
        block.text
        for block in document.iter_blocks()
        if block.attributes.get("admin_role") == "recipient"
    ]
    assert recipients == expected["recipients"]


def test_tables_preserve_grid_and_order(case: tuple[CanonicalDocument, dict]) -> None:
    document, expected = case
    actual = [
        {
            "id": table.id,
            "page_number": table.page_number,
            "block_id": table.block_id,
            "n_rows": table.n_rows,
            "n_cols": table.n_cols,
            "cells": table.cells,
        }
        for table in document.tables
    ]
    assert actual == expected["tables"]


def test_critical_fields_have_exact_values_and_provenance(
    case: tuple[CanonicalDocument, dict],
) -> None:
    document, expected = case
    fields = {field.name: field for field in document.extracted_fields}

    for name, spec in expected["fields"].items():
        field = fields[name]
        assert field.normalized_value == spec["normalized_value"], name
        assert field.source_block_ids == spec["source_block_ids"], name
        assert field.source_page_numbers == spec["source_page_numbers"], name
        assert field.confidence is not None and field.confidence >= spec["min_confidence"], name
        assert field.extractor.name == "admin-rule-v1"

    for name in expected["absent_fields"]:
        # A field that cannot be read must be absent, never a plausible guess.
        assert name not in fields


def test_quality_report_flags_match_golden(case: tuple[CanonicalDocument, dict]) -> None:
    document, expected = case
    assert document.quality_report.critical_field_warnings == expected["critical_field_warnings"]
    assert document.quality_report.structure_quality_score is not None


def test_golden_cases_cover_the_required_signals() -> None:
    """The phase requires specific signals to be covered by golden fixtures."""
    covered: set[str] = set()
    for name in CASES:
        document = parse_admin_document(_canonical_from_input(_load(name, "input")))
        field_names = {field.name for field in document.extracted_fields}
        covered |= field_names
        kinds = {node.kind.value for node in document.hierarchy}
        covered |= kinds
        if document.tables:
            covered.add("table")
        if any(block.type == BlockType.LIST_ITEM for block in document.iter_blocks()):
            covered.add("list")
        if any(block.type == BlockType.TITLE for block in document.iter_blocks()):
            covered.add("title_block")

    required = {
        "document_number",
        "document_type",
        "issuer",
        "issue_date",
        "title",
        "signer",
        "deadline",
        "chapter",
        "section",
        "article",
        "clause",
        "point",
        "appendix",
        "custom_heading",
        "table",
        "list",
        "title_block",
    }
    assert required <= covered, sorted(required - covered)
