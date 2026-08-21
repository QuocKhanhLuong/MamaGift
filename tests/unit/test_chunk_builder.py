"""Tests for the chunk-builder orchestrator that combines legal, plan and fallback
chunking into one validated, partitioned chunk set."""

from __future__ import annotations

import pytest

from mamagift_docpipe import (
    BlockProvenance,
    BlockType,
    CanonicalBlock,
    CanonicalDocument,
    CanonicalPage,
    ExtractedField,
    Extractor,
    HierarchyKind,
    HierarchyNode,
    ParserRun,
    QualityReport,
)
from mamagift_retrieval.chunking import build_chunks

pytestmark = pytest.mark.unit


def _extracted(name: str, value: str) -> ExtractedField:
    return ExtractedField(
        id=f"field_{name}",
        name=name,
        raw_value=value,
        normalized_value=value,
        extractor=Extractor(name="test", version="1.0"),
    )


def _mixed_document() -> CanonicalDocument:
    article_block = CanonicalBlock(
        id="b_1_0000",
        type=BlockType.HEADING,
        text="Điều 1. Phạm vi điều chỉnh",
        reading_order=0,
        parent_id="h_article_1",
        provenance=BlockProvenance(page_number=1),
    )
    unstructured_block = CanonicalBlock(
        id="b_1_0001",
        type=BlockType.PARAGRAPH,
        text="Ghi chú tự do không thuộc điều khoản nào.",
        reading_order=1,
        provenance=BlockProvenance(page_number=1),
    )
    page = CanonicalPage(
        page_number=1, width=595.0, height=842.0, blocks=[article_block, unstructured_block]
    )
    hierarchy = [
        HierarchyNode(
            id="h_article_1",
            kind=HierarchyKind.ARTICLE,
            label="Điều 1",
            text="Phạm vi điều chỉnh",
            parent_id=None,
            source_block_ids=["b_1_0000"],
            ordinal=1,
        )
    ]
    return CanonicalDocument(
        document_id="doc_mixed_1",
        parser_run=ParserRun(
            id="run_mixed_1",
            parser_name="pymupdf",
            parser_version="1.0",
            configuration_hash="0" * 16,
            started_at="2026-01-01T00:00:00+00:00",
            finished_at="2026-01-01T00:00:01+00:00",
        ),
        pages=[page],
        hierarchy=hierarchy,
        extracted_fields=[_extracted("document_type", "quyet_dinh")],
        quality_report=QualityReport(route="born_digital", route_confidence=0.99),
    )


def test_every_text_block_ends_up_in_exactly_one_chunk() -> None:
    chunks = build_chunks(_mixed_document())
    all_block_ids = [block_id for chunk in chunks for block_id in chunk.source_block_ids]
    assert sorted(all_block_ids) == ["b_1_0000", "b_1_0001"]
    assert len(all_block_ids) == len(set(all_block_ids))


def test_combined_chunk_tree_is_valid() -> None:
    # build_chunks calls validate_chunk_tree internally; a passing call is the test.
    build_chunks(_mixed_document())


def test_document_version_propagates_to_every_chunk() -> None:
    chunks = build_chunks(_mixed_document(), document_version=3)
    assert all(chunk.document_version == 3 for chunk in chunks)


def test_scope_leak_document_and_version_are_never_mixed_across_two_documents() -> None:
    doc_a = _mixed_document()
    doc_b = _mixed_document()
    doc_b.document_id = "doc_mixed_2"

    chunks_a = build_chunks(doc_a, document_version=1)
    chunks_b = build_chunks(doc_b, document_version=2)

    ids_a = {chunk.chunk_id for chunk in chunks_a}
    ids_b = {chunk.chunk_id for chunk in chunks_b}
    assert ids_a.isdisjoint(ids_b)
    assert all(
        chunk.document_id == "doc_mixed_1" and chunk.document_version == 1 for chunk in chunks_a
    )
    assert all(
        chunk.document_id == "doc_mixed_2" and chunk.document_version == 2 for chunk in chunks_b
    )
