"""Tests for chunking `CanonicalDocument.hierarchy` (Chương/Mục/Điều/Khoản/Điểm)."""

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
from mamagift_retrieval.chunk import ChunkType, validate_chunk_tree
from mamagift_retrieval.chunking.legal import build_legal_chunks

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
    block_article = CanonicalBlock(
        id="b_1_0000",
        type=BlockType.HEADING,
        text="Điều 1. Phạm vi điều chỉnh",
        reading_order=0,
        parent_id="h_article_1",
        provenance=BlockProvenance(page_number=1),
    )
    block_clause = CanonicalBlock(
        id="b_1_0001",
        type=BlockType.PARAGRAPH,
        text="Quy chế này áp dụng cho toàn bộ hồ sơ hành chính.",
        reading_order=1,
        parent_id="h_clause_1_1",
        provenance=BlockProvenance(page_number=1),
    )
    page = CanonicalPage(
        page_number=1, width=595.0, height=842.0, blocks=[block_article, block_clause]
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
        ),
        HierarchyNode(
            id="h_clause_1_1",
            kind=HierarchyKind.CLAUSE,
            label="Khoản 1",
            text="Quy chế này áp dụng cho toàn bộ hồ sơ hành chính.",
            parent_id="h_article_1",
            source_block_ids=["b_1_0001"],
            ordinal=1,
        ),
    ]

    return CanonicalDocument(
        document_id="doc_legal_1",
        parser_run=ParserRun(
            id="run_legal_1",
            parser_name="pymupdf",
            parser_version="1.0",
            configuration_hash="0" * 16,
            started_at="2026-01-01T00:00:00+00:00",
            finished_at="2026-01-01T00:00:01+00:00",
        ),
        pages=[page],
        hierarchy=hierarchy,
        extracted_fields=[
            _extracted("document_type", "quyet_dinh"),
            _extracted("document_number", "57/QĐ-UBND"),
            _extracted("issuer", "ỦY BAN NHÂN DÂN XÃ MAI GIANG"),
            _extracted("issue_date", "2026-03-03"),
        ],
        quality_report=QualityReport(route="born_digital", route_confidence=0.99),
    )


def test_one_chunk_per_hierarchy_node() -> None:
    chunks = build_legal_chunks(_document())
    assert {chunk.chunk_type for chunk in chunks} == {
        ChunkType.LEGAL_ARTICLE,
        ChunkType.LEGAL_CLAUSE,
    }
    assert len(chunks) == 2


def test_clause_chunk_parent_is_the_article_chunk() -> None:
    chunks = {chunk.metadata["hierarchy_id"]: chunk for chunk in build_legal_chunks(_document())}
    article_chunk = chunks["h_article_1"]
    clause_chunk = chunks["h_clause_1_1"]
    assert clause_chunk.parent_chunk_id == article_chunk.chunk_id
    validate_chunk_tree(list(chunks.values()))


def test_chunk_ids_are_deterministic_across_repeated_builds() -> None:
    document = _document()
    first = [chunk.chunk_id for chunk in build_legal_chunks(document)]
    second = [chunk.chunk_id for chunk in build_legal_chunks(document)]
    assert first == second


def test_chunk_carries_document_and_section_path_metadata() -> None:
    chunks = {chunk.metadata["hierarchy_id"]: chunk for chunk in build_legal_chunks(_document())}
    clause_chunk = chunks["h_clause_1_1"]
    assert clause_chunk.document_type == "quyet_dinh"
    assert clause_chunk.document_number == "57/QĐ-UBND"
    assert clause_chunk.issuer == "ỦY BAN NHÂN DÂN XÃ MAI GIANG"
    assert clause_chunk.issued_date == "2026-03-03"
    assert clause_chunk.section_path == ["Điều 1", "Khoản 1"]
    assert clause_chunk.source_block_ids == ["b_1_0001"]
    assert clause_chunk.source_page_numbers == [1]


def test_recipients_custom_heading_is_not_chunked() -> None:
    document = _document()
    document.hierarchy.append(
        HierarchyNode(
            id="h_recipients_1",
            kind=HierarchyKind.CUSTOM_HEADING,
            label="Nơi nhận",
            text="",
            parent_id=None,
            source_block_ids=["b_1_0000"],
            ordinal=None,
        )
    )
    chunks = build_legal_chunks(document)
    assert "h_recipients_1" not in {chunk.metadata.get("hierarchy_id") for chunk in chunks}
