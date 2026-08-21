"""Tests for chunking `CanonicalDocument.hierarchy` (Chương/Mục/Điều/Khoản/Điểm/Phụ lục)."""

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
from mamagift_retrieval.chunking._shared import field_value
from mamagift_retrieval.chunking.legal import build_legal_chunks

pytestmark = pytest.mark.unit


def _extracted(
    name: str,
    value: str | None = None,
    *,
    raw_value: str | None = None,
    normalized_value: str | None = None,
) -> ExtractedField:
    raw = raw_value if raw_value is not None else value
    norm = normalized_value if normalized_value is not None else value
    return ExtractedField(
        id=f"field_{name}",
        name=name,
        raw_value=raw,
        normalized_value=norm,
        extractor=Extractor(name="test", version="1.0"),
    )


def _document(
    *,
    document_id: str = "doc_legal_1",
    parse_run_id: str = "run_legal_1",
    extracted_fields: list[ExtractedField] | None = None,
) -> CanonicalDocument:
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

    fields = (
        extracted_fields
        if extracted_fields is not None
        else [
            _extracted("document_type", "quyet_dinh"),
            _extracted("document_number", "57/QĐ-UBND"),
            _extracted("issuer", "ỦY BAN NHÂN DÂN XÃ MAI GIANG"),
            _extracted("issue_date", "2026-03-03"),
        ]
    )

    return CanonicalDocument(
        document_id=document_id,
        parser_run=ParserRun(
            id=parse_run_id,
            parser_name="pymupdf",
            parser_version="1.0",
            configuration_hash="0" * 16,
            started_at="2026-01-01T00:00:00+00:00",
            finished_at="2026-01-01T00:00:01+00:00",
        ),
        pages=[page],
        hierarchy=hierarchy,
        extracted_fields=fields,
        quality_report=QualityReport(route="born_digital", route_confidence=0.99),
    )


def test_one_chunk_per_hierarchy_node() -> None:
    chunks = build_legal_chunks(_document())
    assert {chunk.chunk_type for chunk in chunks} == {
        ChunkType.LEGAL_ARTICLE,
        ChunkType.LEGAL_CLAUSE,
    }
    assert len(chunks) == 2


def test_all_hierarchy_kinds_map_to_expected_chunk_types_and_paths() -> None:
    blocks = [
        CanonicalBlock(
            id=f"b_1_{idx:04d}",
            type=BlockType.HEADING,
            text=f"Block {idx}",
            reading_order=idx,
            provenance=BlockProvenance(page_number=1),
        )
        for idx in range(6)
    ]
    page = CanonicalPage(page_number=1, width=595.0, height=842.0, blocks=blocks)

    hierarchy = [
        HierarchyNode(
            id="h_chap_1",
            kind=HierarchyKind.CHAPTER,
            label="Chương I",
            text="Quy định chung",
            parent_id=None,
            source_block_ids=["b_1_0000"],
            ordinal=1,
        ),
        HierarchyNode(
            id="h_sec_1",
            kind=HierarchyKind.SECTION,
            label="Mục 1",
            text="Phạm vi",
            parent_id="h_chap_1",
            source_block_ids=["b_1_0001"],
            ordinal=1,
        ),
        HierarchyNode(
            id="h_art_1",
            kind=HierarchyKind.ARTICLE,
            label="Điều 1",
            text="Phạm vi điều chỉnh",
            parent_id="h_sec_1",
            source_block_ids=["b_1_0002"],
            ordinal=1,
        ),
        HierarchyNode(
            id="h_cl_1",
            kind=HierarchyKind.CLAUSE,
            label="Khoản 1",
            text="Áp dụng cho cán bộ công chức",
            parent_id="h_art_1",
            source_block_ids=["b_1_0003"],
            ordinal=1,
        ),
        HierarchyNode(
            id="h_pt_a",
            kind=HierarchyKind.POINT,
            label="Điểm a",
            text="Cán bộ cấp xã",
            parent_id="h_cl_1",
            source_block_ids=["b_1_0004"],
            ordinal=1,
        ),
        HierarchyNode(
            id="h_app_1",
            kind=HierarchyKind.APPENDIX,
            label="Phụ lục I",
            text="Danh mục biểu mẫu",
            parent_id=None,
            source_block_ids=["b_1_0005"],
            ordinal=1,
        ),
    ]

    doc = CanonicalDocument(
        document_id="doc_full_hier",
        parser_run=ParserRun(
            id="run_full_hier",
            parser_name="pymupdf",
            parser_version="1.0",
            configuration_hash="0" * 16,
            started_at="2026-01-01T00:00:00+00:00",
            finished_at="2026-01-01T00:00:01+00:00",
        ),
        pages=[page],
        hierarchy=hierarchy,
        extracted_fields=[],
        quality_report=QualityReport(route="born_digital", route_confidence=0.99),
    )

    chunks = build_legal_chunks(doc, document_version=1)
    by_node = {chunk.metadata["hierarchy_id"]: chunk for chunk in chunks}

    assert by_node["h_chap_1"].chunk_type == ChunkType.LEGAL_CHAPTER
    assert by_node["h_chap_1"].parent_chunk_id is None
    assert by_node["h_chap_1"].section_path == ["Chương I"]

    assert by_node["h_sec_1"].chunk_type == ChunkType.LEGAL_SECTION
    assert by_node["h_sec_1"].parent_chunk_id == by_node["h_chap_1"].chunk_id
    assert by_node["h_sec_1"].section_path == ["Chương I", "Mục 1"]

    assert by_node["h_art_1"].chunk_type == ChunkType.LEGAL_ARTICLE
    assert by_node["h_art_1"].parent_chunk_id == by_node["h_sec_1"].chunk_id
    assert by_node["h_art_1"].section_path == ["Chương I", "Mục 1", "Điều 1"]

    assert by_node["h_cl_1"].chunk_type == ChunkType.LEGAL_CLAUSE
    assert by_node["h_cl_1"].parent_chunk_id == by_node["h_art_1"].chunk_id
    assert by_node["h_cl_1"].section_path == ["Chương I", "Mục 1", "Điều 1", "Khoản 1"]

    assert by_node["h_pt_a"].chunk_type == ChunkType.LEGAL_POINT
    assert by_node["h_pt_a"].parent_chunk_id == by_node["h_cl_1"].chunk_id
    assert by_node["h_pt_a"].section_path == [
        "Chương I",
        "Mục 1",
        "Điều 1",
        "Khoản 1",
        "Điểm a",
    ]

    assert by_node["h_app_1"].chunk_type == ChunkType.APPENDIX
    assert by_node["h_app_1"].parent_chunk_id is None
    assert by_node["h_app_1"].section_path == ["Phụ lục I"]

    validate_chunk_tree(chunks)


def test_clause_chunk_parent_is_the_article_chunk() -> None:
    chunks = {chunk.metadata["hierarchy_id"]: chunk for chunk in build_legal_chunks(_document())}
    article_chunk = chunks["h_article_1"]
    clause_chunk = chunks["h_clause_1_1"]
    assert clause_chunk.parent_chunk_id == article_chunk.chunk_id
    validate_chunk_tree(list(chunks.values()))


def test_chunk_ids_are_deterministic_across_repeated_builds() -> None:
    document = _document()
    first = [chunk.chunk_id for chunk in build_legal_chunks(document, document_version=1)]
    second = [chunk.chunk_id for chunk in build_legal_chunks(document, document_version=1)]
    assert first == second


def test_chunk_ids_include_document_version_and_isolate_versions() -> None:
    doc = _document()
    v1_chunks = build_legal_chunks(doc, document_version=1)
    v2_chunks = build_legal_chunks(doc, document_version=2)
    vnone_chunks = build_legal_chunks(doc, document_version=None)

    # Document version must propagate directly onto every chunk
    for chunk in v1_chunks:
        assert chunk.document_version == 1
    for chunk in v2_chunks:
        assert chunk.document_version == 2
    for chunk in vnone_chunks:
        assert chunk.document_version is None

    # Chunk IDs must differ across versions and include the version tag
    v1_ids = [c.chunk_id for c in v1_chunks]
    v2_ids = [c.chunk_id for c in v2_chunks]
    vnone_ids = [c.chunk_id for c in vnone_chunks]

    assert v1_ids != v2_ids
    assert v1_ids != vnone_ids
    assert v2_ids != vnone_ids

    assert all(":v1:" in cid for cid in v1_ids)
    assert all(":v2:" in cid for cid in v2_ids)
    assert all(":vnone:" in cid for cid in vnone_ids)

    # Validating trees independently must succeed
    validate_chunk_tree(v1_chunks)
    validate_chunk_tree(v2_chunks)
    validate_chunk_tree(vnone_chunks)


def test_chunk_ids_do_not_collide_when_identifiers_contain_underscores() -> None:
    doc1 = _document(document_id="doc_a", parse_run_id="run_b_c")
    doc2 = _document(document_id="doc_a_b", parse_run_id="run_c")

    chunks1 = build_legal_chunks(doc1, document_version=1)
    chunks2 = build_legal_chunks(doc2, document_version=1)

    ids1 = {c.chunk_id for c in chunks1}
    ids2 = {c.chunk_id for c in chunks2}

    # Under naive underscore joining `chunk_doc_a_b_c_...` would collide
    assert ids1.isdisjoint(ids2)


def test_chunk_ids_do_not_collide_when_identifiers_contain_colons() -> None:
    doc1 = _document(document_id="doc:v1", parse_run_id="run")
    doc2 = _document(document_id="doc", parse_run_id="v1:run")

    chunks1 = build_legal_chunks(doc1, document_version=1)
    chunks2 = build_legal_chunks(doc2, document_version=1)

    ids1 = {c.chunk_id for c in chunks1}
    ids2 = {c.chunk_id for c in chunks2}

    assert ids1.isdisjoint(ids2)


def test_chunk_carries_full_metadata_identity_and_provenance() -> None:
    chunks = {
        chunk.metadata["hierarchy_id"]: chunk
        for chunk in build_legal_chunks(_document(), document_version=1)
    }
    clause_chunk = chunks["h_clause_1_1"]
    assert clause_chunk.chunk_id == "chunk:doc_legal_1:v1:run_legal_1:h_clause_1_1"
    assert clause_chunk.parent_chunk_id == "chunk:doc_legal_1:v1:run_legal_1:h_article_1"
    assert clause_chunk.document_id == "doc_legal_1"
    assert clause_chunk.parse_run_id == "run_legal_1"
    assert clause_chunk.document_version == 1
    assert clause_chunk.document_type == "quyet_dinh"
    assert clause_chunk.document_number == "57/QĐ-UBND"
    assert clause_chunk.issuer == "ỦY BAN NHÂN DÂN XÃ MAI GIANG"
    assert clause_chunk.issued_date == "2026-03-03"
    assert clause_chunk.text == "Quy chế này áp dụng cho toàn bộ hồ sơ hành chính."
    assert clause_chunk.section_path == ["Điều 1", "Khoản 1"]
    assert clause_chunk.source_block_ids == ["b_1_0001"]
    assert clause_chunk.source_page_numbers == [1]
    assert clause_chunk.metadata == {"hierarchy_id": "h_clause_1_1", "hierarchy_label": "Khoản 1"}


def test_recipients_custom_heading_is_not_chunked_and_not_referenced_as_parent() -> None:
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
    document.hierarchy.append(
        HierarchyNode(
            id="h_clause_under_recipient",
            kind=HierarchyKind.CLAUSE,
            label="Khoản 2",
            text="Gửi các đơn vị trực thuộc.",
            parent_id="h_recipients_1",
            source_block_ids=["b_1_0001"],
            ordinal=2,
        )
    )
    chunks = build_legal_chunks(document, document_version=1)
    chunk_by_id = {chunk.metadata.get("hierarchy_id"): chunk for chunk in chunks}

    # Recipients heading itself must not be chunked
    assert "h_recipients_1" not in chunk_by_id

    # A child whose parent is the excluded custom heading must have parent_chunk_id=None
    child_chunk = chunk_by_id["h_clause_under_recipient"]
    assert child_chunk.parent_chunk_id is None

    # Chunk tree validation must succeed without dangling parent references
    validate_chunk_tree(chunks)


def test_field_value_prefers_normalized_value_over_raw_value() -> None:
    doc = _document(
        extracted_fields=[
            _extracted(
                "issue_date",
                raw_value="ngày 03 tháng 03 năm 2026",
                normalized_value="2026-03-03",
            )
        ]
    )
    assert field_value(doc, "issue_date") == "2026-03-03"


def test_field_value_falls_back_to_raw_value_when_normalized_is_none() -> None:
    doc = _document(
        extracted_fields=[
            _extracted(
                "issue_date",
                raw_value="ngày 03 tháng 03 năm 2026",
                normalized_value=None,
            )
        ]
    )
    # MUST return raw_value when normalized_value is None
    assert field_value(doc, "issue_date") == "ngày 03 tháng 03 năm 2026"
    # Returns None when field is absent
    assert field_value(doc, "non_existent_field") is None


def test_build_legal_chunks_uses_raw_value_fallback_for_extracted_fields() -> None:
    doc = _document(
        extracted_fields=[
            _extracted(
                "issue_date",
                raw_value="ngày 03 tháng 03 năm 2026",
                normalized_value=None,
            ),
            _extracted(
                "document_type",
                raw_value="Quyết định",
                normalized_value=None,
            ),
        ]
    )
    chunks = build_legal_chunks(doc, document_version=1)
    assert len(chunks) == 2
    for chunk in chunks:
        assert chunk.issued_date == "ngày 03 tháng 03 năm 2026"
        assert chunk.document_type == "Quyết định"
        assert chunk.document_number is None
        assert chunk.issuer is None


def test_build_legal_chunks_with_missing_extracted_fields() -> None:
    doc = _document(extracted_fields=[])
    chunks = build_legal_chunks(doc, document_version=1)
    assert len(chunks) == 2
    for chunk in chunks:
        assert chunk.document_type is None
        assert chunk.document_number is None
        assert chunk.issuer is None
        assert chunk.issued_date is None


def test_block_text_fallback_when_hierarchy_node_text_is_empty() -> None:
    block_1 = CanonicalBlock(
        id="b_1_0010",
        type=BlockType.PARAGRAPH,
        text="Đoạn văn 1 của điều khoản.",
        reading_order=0,
        provenance=BlockProvenance(page_number=1),
    )
    block_2 = CanonicalBlock(
        id="b_1_0011",
        type=BlockType.PARAGRAPH,
        text="Đoạn văn 2 của điều khoản.",
        reading_order=1,
        provenance=BlockProvenance(page_number=1),
    )
    page = CanonicalPage(page_number=1, width=595.0, height=842.0, blocks=[block_1, block_2])
    hierarchy = [
        HierarchyNode(
            id="h_art_empty_text",
            kind=HierarchyKind.ARTICLE,
            label="Điều 2",
            text="",  # Empty text, must fall back to block text
            parent_id=None,
            source_block_ids=["b_1_0010", "b_1_0011"],
            ordinal=2,
        )
    ]
    doc = CanonicalDocument(
        document_id="doc_fallback_text",
        parser_run=ParserRun(
            id="run_fallback_text",
            parser_name="pymupdf",
            parser_version="1.0",
            configuration_hash="0" * 16,
            started_at="2026-01-01T00:00:00+00:00",
            finished_at="2026-01-01T00:00:01+00:00",
        ),
        pages=[page],
        hierarchy=hierarchy,
        extracted_fields=[],
        quality_report=QualityReport(route="born_digital", route_confidence=0.99),
    )

    chunks = build_legal_chunks(doc, document_version=1)
    assert len(chunks) == 1
    assert chunks[0].text == "Đoạn văn 1 của điều khoản.\nĐoạn văn 2 của điều khoản."


def test_empty_hierarchy_produces_empty_chunks() -> None:
    doc = _document()
    doc.hierarchy.clear()
    assert build_legal_chunks(doc, document_version=1) == []


def test_empty_page_and_multipage_provenance() -> None:
    block_p1 = CanonicalBlock(
        id="b_1_0001",
        type=BlockType.HEADING,
        text="Phần mở đầu trên trang 1",
        reading_order=0,
        provenance=BlockProvenance(page_number=1),
    )
    block_p3 = CanonicalBlock(
        id="b_3_0001",
        type=BlockType.PARAGRAPH,
        text="Phần tiếp theo trên trang 3",
        reading_order=0,
        provenance=BlockProvenance(page_number=3),
    )

    page1 = CanonicalPage(page_number=1, width=595.0, height=842.0, blocks=[block_p1])
    page2 = CanonicalPage(page_number=2, width=595.0, height=842.0, blocks=[])  # Empty page
    page3 = CanonicalPage(page_number=3, width=595.0, height=842.0, blocks=[block_p3])

    hierarchy = [
        HierarchyNode(
            id="h_art_multipage",
            kind=HierarchyKind.ARTICLE,
            label="Điều 1",
            text="Điều khoản kéo dài qua nhiều trang",
            parent_id=None,
            source_block_ids=["b_1_0001", "b_3_0001"],
            ordinal=1,
        )
    ]

    doc = CanonicalDocument(
        document_id="doc_multipage",
        parser_run=ParserRun(
            id="run_multipage",
            parser_name="pymupdf",
            parser_version="1.0",
            configuration_hash="0" * 16,
            started_at="2026-01-01T00:00:00+00:00",
            finished_at="2026-01-01T00:00:01+00:00",
        ),
        pages=[page1, page2, page3],
        hierarchy=hierarchy,
        extracted_fields=[],
        quality_report=QualityReport(route="born_digital", route_confidence=0.99),
    )

    chunks = build_legal_chunks(doc, document_version=1)
    assert len(chunks) == 1
    assert chunks[0].source_page_numbers == [1, 3]
