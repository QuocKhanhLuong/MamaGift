"""Tests for the deterministic fallback paragraph chunker."""

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
from mamagift_retrieval.chunk import Chunk, ChunkType, validate_chunk_tree
from mamagift_retrieval.chunking.fallback import build_fallback_chunks

pytestmark = pytest.mark.unit


def _extracted(name: str, value: str) -> ExtractedField:
    return ExtractedField(
        id=f"field_{name}",
        name=name,
        raw_value=value,
        normalized_value=value,
        extractor=Extractor(name="test", version="1.0"),
    )


def _document() -> CanonicalDocument:
    blocks = [
        CanonicalBlock(
            id="b_1_0000",
            type=BlockType.PARAGRAPH,
            text="Đoạn văn không có cấu trúc rõ ràng.",
            reading_order=0,
            provenance=BlockProvenance(page_number=1),
        ),
        CanonicalBlock(
            id="b_1_0001",
            type=BlockType.PARAGRAPH,
            text="Đoạn văn thứ hai, cũng không có cấu trúc.",
            reading_order=1,
            provenance=BlockProvenance(page_number=1),
        ),
        CanonicalBlock(
            id="b_1_0002",
            type=BlockType.HEADER,
            text="Trang 1",
            reading_order=2,
            provenance=BlockProvenance(page_number=1),
        ),
        CanonicalBlock(
            id="b_1_0003",
            type=BlockType.PARAGRAPH,
            text="",
            reading_order=3,
            provenance=BlockProvenance(page_number=1),
        ),
    ]
    page = CanonicalPage(page_number=1, width=595.0, height=842.0, blocks=blocks)
    return CanonicalDocument(
        document_id="doc_fallback_1",
        parser_run=ParserRun(
            id="run_fallback_1",
            parser_name="pymupdf",
            parser_version="1.0",
            configuration_hash="0" * 16,
            started_at="2026-01-01T00:00:00+00:00",
            finished_at="2026-01-01T00:00:01+00:00",
        ),
        pages=[page],
        quality_report=QualityReport(route="born_digital", route_confidence=0.99),
    )


def test_claimed_blocks_are_never_re_chunked() -> None:
    chunks = build_fallback_chunks(_document(), claimed_block_ids={"b_1_0000"})
    assert [chunk.source_block_ids for chunk in chunks] == [["b_1_0001"]]


def test_furniture_and_empty_blocks_are_skipped() -> None:
    chunks = build_fallback_chunks(_document(), claimed_block_ids=set())
    block_ids = {chunk.source_block_ids[0] for chunk in chunks}
    assert "b_1_0002" not in block_ids
    assert "b_1_0003" not in block_ids


def test_fallback_chunks_are_paragraph_type() -> None:
    chunks = build_fallback_chunks(_document(), claimed_block_ids=set())
    assert all(chunk.chunk_type == ChunkType.PARAGRAPH for chunk in chunks)


def test_fallback_chunking_is_deterministic_across_repeated_builds() -> None:
    document = _document()
    first = [chunk.chunk_id for chunk in build_fallback_chunks(document, claimed_block_ids=set())]
    second = [chunk.chunk_id for chunk in build_fallback_chunks(document, claimed_block_ids=set())]
    assert first == second
    assert len(first) == len(set(first))


def test_fallback_chunks_preserve_metadata_and_parent_chunk_id() -> None:
    node = HierarchyNode(
        id="h_art_1",
        kind=HierarchyKind.ARTICLE,
        label="Điều 1",
        source_block_ids=["b_1_0000"],
    )
    custom_node = HierarchyNode(
        id="h_recip_1",
        kind=HierarchyKind.CUSTOM_HEADING,
        label="Nơi nhận:",
        source_block_ids=["b_1_0002"],
    )
    blocks = [
        CanonicalBlock(
            id="b_1_0000",
            type=BlockType.PARAGRAPH,
            text="Đoạn văn thuộc Điều 1.",
            reading_order=0,
            provenance=BlockProvenance(page_number=1),
        ),
        CanonicalBlock(
            id="b_1_0001",
            type=BlockType.PARAGRAPH,
            text="Đoạn văn có parent_id trỏ về Điều 1.",
            reading_order=1,
            parent_id="h_art_1",
            provenance=BlockProvenance(page_number=1),
        ),
        CanonicalBlock(
            id="b_1_0002",
            type=BlockType.PARAGRAPH,
            text="Đoạn văn trỏ về custom heading.",
            reading_order=2,
            parent_id="h_recip_1",
            provenance=BlockProvenance(page_number=1),
        ),
    ]
    page = CanonicalPage(page_number=1, width=595.0, height=842.0, blocks=blocks)
    doc = CanonicalDocument(
        document_id="doc_fallback_2",
        parser_run=ParserRun(
            id="run_fallback_2",
            parser_name="pymupdf",
            parser_version="1.0",
            configuration_hash="0" * 16,
            started_at="2026-01-01T00:00:00+00:00",
            finished_at="2026-01-01T00:00:01+00:00",
        ),
        pages=[page],
        hierarchy=[node, custom_node],
        extracted_fields=[
            _extracted("document_type", "QUYẾT ĐỊNH"),
            _extracted("document_number", "01/QĐ-TTg"),
            _extracted("issuer", "Thủ tướng"),
            _extracted("issue_date", "2026-01-01"),
        ],
        quality_report=QualityReport(route="born_digital", route_confidence=0.99),
    )
    chunks = build_fallback_chunks(doc, claimed_block_ids={"b_1_0000"}, document_version=2)
    assert len(chunks) == 2
    assert chunks[0].chunk_id == "chunk_doc_fallback_2_run_fallback_2_fallback_b_1_0001"
    assert chunks[0].parent_chunk_id == "chunk_doc_fallback_2_run_fallback_2_h_art_1"
    assert chunks[0].document_version == 2
    assert chunks[0].document_type == "QUYẾT ĐỊNH"
    assert chunks[0].document_number == "01/QĐ-TTg"
    assert chunks[0].issuer == "Thủ tướng"
    assert chunks[0].issued_date == "2026-01-01"
    assert chunks[0].metadata == {"classified_by": "fallback"}
    assert chunks[0].section_path == []
    assert chunks[0].source_page_numbers == [1]

    # Block with custom heading parent has parent_chunk_id as None
    assert chunks[1].parent_chunk_id is None

    article_chunk = Chunk(
        chunk_id="chunk_doc_fallback_2_run_fallback_2_h_art_1",
        document_id="doc_fallback_2",
        parse_run_id="run_fallback_2",
        document_version=2,
        chunk_type=ChunkType.LEGAL_ARTICLE,
        text="Điều 1",
        source_block_ids=["b_1_0000"],
        source_page_numbers=[1],
    )
    validate_chunk_tree([article_chunk, *chunks])
