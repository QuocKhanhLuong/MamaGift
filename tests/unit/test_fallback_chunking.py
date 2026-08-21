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


def _extracted(name: str, value: str | None) -> ExtractedField:
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
    assert len(chunks) == 1
    assert chunks[0].chunk_id == "chunk:doc_fallback_1:vnone:run_fallback_1:fallback_b_1_0001"
    assert chunks[0].source_block_ids == ["b_1_0001"]
    assert chunks[0].source_page_numbers == [1]
    assert chunks[0].text == "Đoạn văn thứ hai, cũng không có cấu trúc."
    assert chunks[0].chunk_type == ChunkType.PARAGRAPH


def test_furniture_and_empty_blocks_are_skipped() -> None:
    chunks = build_fallback_chunks(_document(), claimed_block_ids=set())
    assert len(chunks) == 2
    assert [chunk.source_block_ids for chunk in chunks] == [["b_1_0000"], ["b_1_0001"]]
    assert [chunk.text for chunk in chunks] == [
        "Đoạn văn không có cấu trúc rõ ràng.",
        "Đoạn văn thứ hai, cũng không có cấu trúc.",
    ]
    block_ids = {chunk.source_block_ids[0] for chunk in chunks}
    assert block_ids == {"b_1_0000", "b_1_0001"}
    assert "b_1_0002" not in block_ids
    assert "b_1_0003" not in block_ids


def test_fallback_chunks_are_paragraph_type() -> None:
    chunks = build_fallback_chunks(_document(), claimed_block_ids=set())
    assert len(chunks) == 2
    assert [chunk.chunk_type for chunk in chunks] == [
        ChunkType.PARAGRAPH,
        ChunkType.PARAGRAPH,
    ]
    assert [chunk.source_block_ids for chunk in chunks] == [["b_1_0000"], ["b_1_0001"]]


def test_fallback_chunking_is_deterministic_across_repeated_builds() -> None:
    document = _document()
    first = build_fallback_chunks(document, claimed_block_ids=set(), document_version=1)
    second = build_fallback_chunks(document, claimed_block_ids=set(), document_version=1)
    assert len(first) == 2
    assert [chunk.chunk_id for chunk in first] == [
        "chunk:doc_fallback_1:v1:run_fallback_1:fallback_b_1_0000",
        "chunk:doc_fallback_1:v1:run_fallback_1:fallback_b_1_0001",
    ]
    assert [chunk.chunk_id for chunk in first] == [chunk.chunk_id for chunk in second]
    assert [chunk.text for chunk in first] == [chunk.text for chunk in second]
    assert [chunk.source_block_ids for chunk in first] == [
        chunk.source_block_ids for chunk in second
    ]
    assert [chunk.model_dump() for chunk in first] == [chunk.model_dump() for chunk in second]


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
    assert chunks[0].chunk_id == "chunk:doc_fallback_2:v2:run_fallback_2:fallback_b_1_0001"
    assert chunks[0].parent_chunk_id == "chunk:doc_fallback_2:v2:run_fallback_2:h_art_1"
    assert chunks[0].document_version == 2
    assert chunks[0].document_type == "QUYẾT ĐỊNH"
    assert chunks[0].document_number == "01/QĐ-TTg"
    assert chunks[0].issuer == "Thủ tướng"
    assert chunks[0].issued_date == "2026-01-01"
    assert chunks[0].metadata == {"classified_by": "fallback"}
    assert chunks[0].section_path == []
    assert chunks[0].source_page_numbers == [1]
    assert chunks[0].source_block_ids == ["b_1_0001"]
    assert chunks[0].text == "Đoạn văn có parent_id trỏ về Điều 1."
    assert chunks[0].chunk_type == ChunkType.PARAGRAPH

    # Block with custom heading parent has parent_chunk_id as None
    assert chunks[1].chunk_id == "chunk:doc_fallback_2:v2:run_fallback_2:fallback_b_1_0002"
    assert chunks[1].parent_chunk_id is None
    assert chunks[1].document_version == 2
    assert chunks[1].document_type == "QUYẾT ĐỊNH"
    assert chunks[1].document_number == "01/QĐ-TTg"
    assert chunks[1].issuer == "Thủ tướng"
    assert chunks[1].issued_date == "2026-01-01"
    assert chunks[1].metadata == {"classified_by": "fallback"}
    assert chunks[1].section_path == []
    assert chunks[1].source_page_numbers == [1]
    assert chunks[1].source_block_ids == ["b_1_0002"]
    assert chunks[1].text == "Đoạn văn trỏ về custom heading."
    assert chunks[1].chunk_type == ChunkType.PARAGRAPH

    article_chunk = Chunk(
        chunk_id="chunk:doc_fallback_2:v2:run_fallback_2:h_art_1",
        document_id="doc_fallback_2",
        parse_run_id="run_fallback_2",
        document_version=2,
        chunk_type=ChunkType.LEGAL_ARTICLE,
        text="Điều 1",
        source_block_ids=["b_1_0000"],
        source_page_numbers=[1],
    )
    validate_chunk_tree([article_chunk, *chunks])


def test_document_with_zero_blocks() -> None:
    page = CanonicalPage(page_number=1, width=595.0, height=842.0, blocks=[])
    doc = CanonicalDocument(
        document_id="doc_zero_blocks",
        parser_run=ParserRun(
            id="run_zero_1",
            parser_name="pymupdf",
            parser_version="1.0",
            configuration_hash="0" * 16,
            started_at="2026-01-01T00:00:00+00:00",
            finished_at="2026-01-01T00:00:01+00:00",
        ),
        pages=[page],
        quality_report=QualityReport(route="born_digital", route_confidence=0.99),
    )
    assert build_fallback_chunks(doc, claimed_block_ids=set()) == []

    doc_empty_pages = CanonicalDocument(
        document_id="doc_empty_pages",
        parser_run=ParserRun(
            id="run_zero_2",
            parser_name="pymupdf",
            parser_version="1.0",
            configuration_hash="0" * 16,
            started_at="2026-01-01T00:00:00+00:00",
            finished_at="2026-01-01T00:00:01+00:00",
        ),
        pages=[],
        quality_report=QualityReport(route="born_digital", route_confidence=0.99),
    )
    assert build_fallback_chunks(doc_empty_pages, claimed_block_ids=set()) == []


def test_block_with_blank_or_whitespace_text_is_skipped() -> None:
    blocks = [
        CanonicalBlock(
            id="b_blank_1",
            type=BlockType.PARAGRAPH,
            text="",
            reading_order=0,
            provenance=BlockProvenance(page_number=1),
        ),
        CanonicalBlock(
            id="b_blank_2",
            type=BlockType.PARAGRAPH,
            text="   \t\n  ",
            reading_order=1,
            provenance=BlockProvenance(page_number=1),
        ),
        CanonicalBlock(
            id="b_valid_1",
            type=BlockType.PARAGRAPH,
            text="Nội dung hợp lệ.",
            reading_order=2,
            provenance=BlockProvenance(page_number=1),
        ),
    ]
    page = CanonicalPage(page_number=1, width=595.0, height=842.0, blocks=blocks)
    doc = CanonicalDocument(
        document_id="doc_blank_test",
        parser_run=ParserRun(
            id="run_blank_1",
            parser_name="pymupdf",
            parser_version="1.0",
            configuration_hash="0" * 16,
            started_at="2026-01-01T00:00:00+00:00",
            finished_at="2026-01-01T00:00:01+00:00",
        ),
        pages=[page],
        quality_report=QualityReport(route="born_digital", route_confidence=0.99),
    )
    chunks = build_fallback_chunks(doc, claimed_block_ids=set())
    assert len(chunks) == 1
    assert chunks[0].chunk_id == "chunk:doc_blank_test:vnone:run_blank_1:fallback_b_valid_1"
    assert chunks[0].text == "Nội dung hợp lệ."
    assert chunks[0].source_block_ids == ["b_valid_1"]
    assert chunks[0].chunk_type == ChunkType.PARAGRAPH


def test_single_block_document() -> None:
    blocks = [
        CanonicalBlock(
            id="b_single_1",
            type=BlockType.PARAGRAPH,
            text="Văn bản chỉ có duy nhất một đoạn văn này.",
            reading_order=0,
            provenance=BlockProvenance(page_number=1),
        ),
    ]
    page = CanonicalPage(page_number=1, width=595.0, height=842.0, blocks=blocks)
    doc = CanonicalDocument(
        document_id="doc_single_block",
        parser_run=ParserRun(
            id="run_single_1",
            parser_name="pymupdf",
            parser_version="1.0",
            configuration_hash="0" * 16,
            started_at="2026-01-01T00:00:00+00:00",
            finished_at="2026-01-01T00:00:01+00:00",
        ),
        pages=[page],
        quality_report=QualityReport(route="born_digital", route_confidence=0.99),
    )
    chunks = build_fallback_chunks(doc, claimed_block_ids=set(), document_version=1)
    assert len(chunks) == 1
    assert chunks[0].chunk_id == "chunk:doc_single_block:v1:run_single_1:fallback_b_single_1"
    assert chunks[0].parent_chunk_id is None
    assert chunks[0].document_id == "doc_single_block"
    assert chunks[0].parse_run_id == "run_single_1"
    assert chunks[0].document_version == 1
    assert chunks[0].chunk_type == ChunkType.PARAGRAPH
    assert chunks[0].text == "Văn bản chỉ có duy nhất một đoạn văn này."
    assert chunks[0].source_block_ids == ["b_single_1"]
    assert chunks[0].source_page_numbers == [1]
    assert chunks[0].metadata == {"classified_by": "fallback"}
    assert chunks[0].section_path == []


def test_claimed_block_ids_with_nonexistent_id() -> None:
    doc = _document()
    chunks = build_fallback_chunks(
        doc,
        claimed_block_ids={"non_existent_block_999", "b_1_0000"},
    )
    assert len(chunks) == 1
    assert chunks[0].chunk_id == "chunk:doc_fallback_1:vnone:run_fallback_1:fallback_b_1_0001"
    assert chunks[0].source_block_ids == ["b_1_0001"]
    assert chunks[0].source_page_numbers == [1]
    assert chunks[0].text == "Đoạn văn thứ hai, cũng không có cấu trúc."


def test_multi_page_document_preserves_reading_order_and_pages() -> None:
    page_1_blocks = [
        CanonicalBlock(
            id="b_1_0000",
            type=BlockType.PARAGRAPH,
            text="Đoạn văn trang 1, khối 0.",
            reading_order=0,
            provenance=BlockProvenance(page_number=1),
        ),
        CanonicalBlock(
            id="b_1_0001",
            type=BlockType.PARAGRAPH,
            text="Đoạn văn trang 1, khối 1.",
            reading_order=1,
            provenance=BlockProvenance(page_number=1),
        ),
    ]
    page_2_blocks = [
        CanonicalBlock(
            id="b_2_0000",
            type=BlockType.PARAGRAPH,
            text="Đoạn văn trang 2, khối 0.",
            reading_order=0,
            provenance=BlockProvenance(page_number=2),
        ),
        CanonicalBlock(
            id="b_2_0001",
            type=BlockType.PARAGRAPH,
            text="Đoạn văn trang 2, khối 1.",
            reading_order=1,
            provenance=BlockProvenance(page_number=2),
        ),
    ]
    p1 = CanonicalPage(page_number=1, width=595.0, height=842.0, blocks=page_1_blocks)
    p2 = CanonicalPage(page_number=2, width=595.0, height=842.0, blocks=page_2_blocks)
    doc = CanonicalDocument(
        document_id="doc_multipage",
        parser_run=ParserRun(
            id="run_mp_1",
            parser_name="pymupdf",
            parser_version="1.0",
            configuration_hash="0" * 16,
            started_at="2026-01-01T00:00:00+00:00",
            finished_at="2026-01-01T00:00:01+00:00",
        ),
        pages=[p1, p2],
        quality_report=QualityReport(route="born_digital", route_confidence=0.99),
    )
    chunks = build_fallback_chunks(doc, claimed_block_ids={"b_1_0000"}, document_version=3)
    assert len(chunks) == 3
    assert [c.chunk_id for c in chunks] == [
        "chunk:doc_multipage:v3:run_mp_1:fallback_b_1_0001",
        "chunk:doc_multipage:v3:run_mp_1:fallback_b_2_0000",
        "chunk:doc_multipage:v3:run_mp_1:fallback_b_2_0001",
    ]
    assert [c.source_block_ids for c in chunks] == [["b_1_0001"], ["b_2_0000"], ["b_2_0001"]]
    assert [c.source_page_numbers for c in chunks] == [[1], [2], [2]]
    assert [c.text for c in chunks] == [
        "Đoạn văn trang 1, khối 1.",
        "Đoạn văn trang 2, khối 0.",
        "Đoạn văn trang 2, khối 1.",
    ]
    assert all(c.document_version == 3 for c in chunks)
    assert all(c.document_id == "doc_multipage" for c in chunks)
    assert all(c.parse_run_id == "run_mp_1" for c in chunks)


def test_fallback_chunk_ids_include_document_version_and_isolate_versions() -> None:
    doc = _document()
    v1_chunks = build_fallback_chunks(doc, claimed_block_ids=set(), document_version=1)
    v2_chunks = build_fallback_chunks(doc, claimed_block_ids=set(), document_version=2)
    vnone_chunks = build_fallback_chunks(doc, claimed_block_ids=set(), document_version=None)

    for chunk in v1_chunks:
        assert chunk.document_version == 1
    for chunk in v2_chunks:
        assert chunk.document_version == 2
    for chunk in vnone_chunks:
        assert chunk.document_version is None

    v1_ids = [c.chunk_id for c in v1_chunks]
    v2_ids = [c.chunk_id for c in v2_chunks]
    vnone_ids = [c.chunk_id for c in vnone_chunks]

    assert v1_ids != v2_ids
    assert v1_ids != vnone_ids
    assert v2_ids != vnone_ids

    assert all(":v1:" in cid for cid in v1_ids)
    assert all(":v2:" in cid for cid in v2_ids)
    assert all(":vnone:" in cid for cid in vnone_ids)

    validate_chunk_tree(v1_chunks)
    validate_chunk_tree(v2_chunks)
    validate_chunk_tree(vnone_chunks)


def test_fallback_chunk_ids_do_not_collide_when_identifiers_contain_underscores() -> None:
    doc1 = CanonicalDocument(
        document_id="doc_a",
        parser_run=ParserRun(
            id="run_b_c",
            parser_name="pymupdf",
            parser_version="1.0",
            configuration_hash="0" * 16,
            started_at="2026-01-01T00:00:00+00:00",
            finished_at="2026-01-01T00:00:01+00:00",
        ),
        pages=_document().pages,
        quality_report=QualityReport(route="born_digital", route_confidence=0.99),
    )
    doc2 = CanonicalDocument(
        document_id="doc_a_b",
        parser_run=ParserRun(
            id="run_c",
            parser_name="pymupdf",
            parser_version="1.0",
            configuration_hash="0" * 16,
            started_at="2026-01-01T00:00:00+00:00",
            finished_at="2026-01-01T00:00:01+00:00",
        ),
        pages=_document().pages,
        quality_report=QualityReport(route="born_digital", route_confidence=0.99),
    )

    chunks1 = build_fallback_chunks(doc1, claimed_block_ids=set(), document_version=1)
    chunks2 = build_fallback_chunks(doc2, claimed_block_ids=set(), document_version=1)

    ids1 = {c.chunk_id for c in chunks1}
    ids2 = {c.chunk_id for c in chunks2}

    assert ids1.isdisjoint(ids2)


def test_fallback_chunk_ids_do_not_collide_when_identifiers_contain_colons() -> None:
    doc1 = CanonicalDocument(
        document_id="doc:v1",
        parser_run=ParserRun(
            id="run",
            parser_name="pymupdf",
            parser_version="1.0",
            configuration_hash="0" * 16,
            started_at="2026-01-01T00:00:00+00:00",
            finished_at="2026-01-01T00:00:01+00:00",
        ),
        pages=_document().pages,
        quality_report=QualityReport(route="born_digital", route_confidence=0.99),
    )
    doc2 = CanonicalDocument(
        document_id="doc",
        parser_run=ParserRun(
            id="v1:run",
            parser_name="pymupdf",
            parser_version="1.0",
            configuration_hash="0" * 16,
            started_at="2026-01-01T00:00:00+00:00",
            finished_at="2026-01-01T00:00:01+00:00",
        ),
        pages=_document().pages,
        quality_report=QualityReport(route="born_digital", route_confidence=0.99),
    )

    chunks1 = build_fallback_chunks(doc1, claimed_block_ids=set(), document_version=1)
    chunks2 = build_fallback_chunks(doc2, claimed_block_ids=set(), document_version=1)

    ids1 = {c.chunk_id for c in chunks1}
    ids2 = {c.chunk_id for c in chunks2}

    assert ids1.isdisjoint(ids2)


def test_missing_and_none_extracted_fields() -> None:
    blocks = [
        CanonicalBlock(
            id="b_1_0000",
            type=BlockType.PARAGRAPH,
            text="Đoạn văn không có metadata.",
            reading_order=0,
            provenance=BlockProvenance(page_number=1),
        ),
    ]
    page = CanonicalPage(page_number=1, width=595.0, height=842.0, blocks=blocks)
    doc = CanonicalDocument(
        document_id="doc_no_meta",
        parser_run=ParserRun(
            id="run_no_meta_1",
            parser_name="pymupdf",
            parser_version="1.0",
            configuration_hash="0" * 16,
            started_at="2026-01-01T00:00:00+00:00",
            finished_at="2026-01-01T00:00:01+00:00",
        ),
        pages=[page],
        extracted_fields=[
            ExtractedField(
                id="f_doc_num",
                name="document_number",
                raw_value=None,
                normalized_value=None,
                extractor=Extractor(name="test", version="1.0"),
            ),
        ],
        quality_report=QualityReport(route="born_digital", route_confidence=0.99),
    )
    chunks = build_fallback_chunks(doc, claimed_block_ids=set())
    assert len(chunks) == 1
    assert chunks[0].document_type is None
    assert chunks[0].document_number is None
    assert chunks[0].issuer is None
    assert chunks[0].issued_date is None
    assert chunks[0].text == "Đoạn văn không có metadata."
