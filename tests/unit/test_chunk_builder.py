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
from mamagift_retrieval.chunk import ChunkType
from mamagift_retrieval.chunking import build_chunks

pytestmark = pytest.mark.unit


def _extracted(name: str, value: str | None) -> ExtractedField:
    return ExtractedField(
        id=f"field_{name}",
        name=name,
        raw_value=value,
        normalized_value=value,
        extractor=Extractor(name="test", version="1.0"),
    )


def _parser_run(run_id: str = "run_mixed_1") -> ParserRun:
    return ParserRun(
        id=run_id,
        parser_name="pymupdf",
        parser_version="1.0",
        configuration_hash="0" * 16,
        started_at="2026-01-01T00:00:00+00:00",
        finished_at="2026-01-01T00:00:01+00:00",
    )


def _mixed_document(
    *,
    document_id: str = "doc_mixed_1",
    run_id: str = "run_mixed_1",
    include_optional_fields: bool = True,
) -> CanonicalDocument:
    article_block = CanonicalBlock(
        id="b_1_0000",
        type=BlockType.HEADING,
        text="Điều 1. Phạm vi điều chỉnh",
        reading_order=0,
        parent_id="h_article_1",
        provenance=BlockProvenance(page_number=1),
    )
    clause_block = CanonicalBlock(
        id="b_1_0001",
        type=BlockType.PARAGRAPH,
        text="Quy chế này áp dụng cho toàn bộ cơ quan đơn vị.",
        reading_order=1,
        parent_id="h_clause_1_1",
        provenance=BlockProvenance(page_number=1),
    )
    unstructured_block = CanonicalBlock(
        id="b_1_0002",
        type=BlockType.PARAGRAPH,
        text="Ghi chú tự do không thuộc điều khoản nào.",
        reading_order=2,
        provenance=BlockProvenance(page_number=2),
    )
    page_1 = CanonicalPage(
        page_number=1,
        width=595.0,
        height=842.0,
        blocks=[article_block, clause_block],
    )
    page_2 = CanonicalPage(
        page_number=2,
        width=595.0,
        height=842.0,
        blocks=[unstructured_block],
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
            text="Quy chế này áp dụng cho toàn bộ cơ quan đơn vị.",
            parent_id="h_article_1",
            source_block_ids=["b_1_0001"],
            ordinal=1,
        ),
    ]
    extracted_fields = (
        [
            _extracted("document_type", "quyet_dinh"),
            _extracted("document_number", "57/QĐ-UBND"),
            _extracted("issuer", "ỦY BAN NHÂN DÂN XÃ MAI GIANG"),
            _extracted("issue_date", "2026-03-03"),
        ]
        if include_optional_fields
        else []
    )
    return CanonicalDocument(
        document_id=document_id,
        parser_run=_parser_run(run_id),
        pages=[page_1, page_2],
        hierarchy=hierarchy,
        extracted_fields=extracted_fields,
        quality_report=QualityReport(route="born_digital", route_confidence=0.99),
    )


def _plan_document(
    *,
    document_id: str = "doc_plan_1",
    run_id: str = "run_plan_1",
    document_type: str = "ke_hoach",
) -> CanonicalDocument:
    lines = [
        "I. MỤC ĐÍCH, YÊU CẦU",
        "Bảo đảm công tác tuyển sinh diễn ra đúng quy định.",
        "II. NỘI DUNG THỰC HIỆN",
        "1. Rà soát danh sách học sinh trong độ tuổi tuyển sinh",
        "Đơn vị chủ trì: Phòng Giáo dục và Đào tạo",
        "Đơn vị phối hợp: Ủy ban nhân dân các xã, phường",
        "Thời hạn hoàn thành: trước ngày 15 tháng 08 năm 2026",
        "Thực hiện rà soát tại từng địa bàn dân cư.",
        "2. Tổ chức tiếp nhận hồ sơ tuyển sinh trực tuyến",
        "Đơn vị chủ trì: Trường Tiểu học Mai Giang",
        "Đơn vị phối hợp: Phòng Giáo dục và Đào tạo",
        "Thời hạn hoàn thành: trước ngày 30 tháng 08 năm 2026",
    ]
    blocks = [
        CanonicalBlock(
            id=f"b_p_{index:04d}",
            type=BlockType.PARAGRAPH,
            text=line,
            reading_order=index,
            provenance=BlockProvenance(page_number=1 if index < 8 else 2),
        )
        for index, line in enumerate(lines)
    ]
    page_1 = CanonicalPage(
        page_number=1,
        width=595.0,
        height=842.0,
        blocks=[b for b in blocks if b.provenance.page_number == 1],
    )
    page_2 = CanonicalPage(
        page_number=2,
        width=595.0,
        height=842.0,
        blocks=[b for b in blocks if b.provenance.page_number == 2],
    )
    return CanonicalDocument(
        document_id=document_id,
        parser_run=_parser_run(run_id),
        pages=[page_1, page_2],
        hierarchy=[],
        extracted_fields=[
            _extracted("document_type", document_type),
            _extracted("document_number", "12/KH-UBND"),
            _extracted("issuer", "ỦY BAN NHÂN DÂN HUYỆN MAI GIANG"),
            _extracted("issue_date", "2026-03-01"),
        ],
        quality_report=QualityReport(route="born_digital", route_confidence=0.99),
    )


# ---------------------------------------------------------------------------
# F1: Tree contract validation enforcement in orchestrator
# ---------------------------------------------------------------------------


def test_build_chunks_enforces_tree_validation_on_contract_violations() -> None:
    """Deleting validate_chunk_tree at builder.py:42 must cause this test to fail.

    Construct a document where a hierarchy node ID collides with a fallback chunk ID,
    producing duplicate chunk_ids in the orchestrator's combined chunk list.
    """
    article_block = CanonicalBlock(
        id="b_1_0000",
        type=BlockType.HEADING,
        text="Điều 1. Quy định chung",
        reading_order=0,
        parent_id="fallback_b_1_0001",
        provenance=BlockProvenance(page_number=1),
    )
    fallback_block = CanonicalBlock(
        id="b_1_0001",
        type=BlockType.PARAGRAPH,
        text="Đoạn văn tự do không thuộc điều khoản.",
        reading_order=1,
        provenance=BlockProvenance(page_number=1),
    )
    page = CanonicalPage(
        page_number=1, width=595.0, height=842.0, blocks=[article_block, fallback_block]
    )
    # The hierarchy node id "fallback_b_1_0001" generates chunk_id:
    # "chunk_doc_dup_run_dup_fallback_b_1_0001" via legal chunker.
    # The fallback chunker generates identical chunk_id for block "b_1_0001":
    # "chunk_doc_dup_run_dup_fallback_b_1_0001".
    hierarchy = [
        HierarchyNode(
            id="fallback_b_1_0001",
            kind=HierarchyKind.ARTICLE,
            label="Điều 1",
            text="Quy định chung",
            parent_id=None,
            source_block_ids=["b_1_0000"],
            ordinal=1,
        )
    ]
    doc = CanonicalDocument(
        document_id="doc_dup",
        parser_run=_parser_run("run_dup"),
        pages=[page],
        hierarchy=hierarchy,
        extracted_fields=[_extracted("document_type", "quyet_dinh")],
        quality_report=QualityReport(route="born_digital", route_confidence=0.99),
    )

    with pytest.raises(ValueError, match="duplicate chunk_id"):
        build_chunks(doc)


# ---------------------------------------------------------------------------
# F2: Plan document orchestration, partitioning and provenance
# ---------------------------------------------------------------------------


def test_plan_document_orchestration_produces_plan_chunks_and_fallback() -> None:
    """Replacing build_plan_chunks at builder.py:29 with [] must cause this test to fail.

    Assert that a `Kế hoạch` document produces correctly typed plan sections,
    plan tasks, task content paragraphs, and fallback chunks for unclaimed preamble text.
    """
    doc = _plan_document(document_type="ke_hoach")
    chunks = build_chunks(doc, document_version=1)

    # 1. Assert chunk types produced
    types = [chunk.chunk_type for chunk in chunks]
    assert ChunkType.PLAN_SECTION in types
    assert ChunkType.PLAN_TASK in types
    assert ChunkType.PARAGRAPH in types
    assert ChunkType.LEGAL_ARTICLE not in types
    assert ChunkType.LEGAL_CLAUSE not in types

    # 2. Assert sections and tasks
    sections = [c for c in chunks if c.chunk_type == ChunkType.PLAN_SECTION]
    tasks = [c for c in chunks if c.chunk_type == ChunkType.PLAN_TASK]
    content_chunks = [
        c
        for c in chunks
        if c.chunk_type == ChunkType.PARAGRAPH and c.metadata.get("classified_by") != "fallback"
    ]
    fallback_chunks = [
        c
        for c in chunks
        if c.chunk_type == ChunkType.PARAGRAPH and c.metadata.get("classified_by") == "fallback"
    ]

    assert len(sections) == 2
    assert len(tasks) == 2
    assert len(content_chunks) == 1
    # Block b_p_0001 ("Bảo đảm công tác tuyển sinh...") is a section preamble before task 1,
    # so fallback builder picks it up.
    assert len(fallback_chunks) == 1
    assert fallback_chunks[0].source_block_ids == ["b_p_0001"]
    assert fallback_chunks[0].text == "Bảo đảm công tác tuyển sinh diễn ra đúng quy định."

    # 3. Assert plan task provenance & scoped metadata
    task_1 = next(c for c in tasks if c.metadata["ordinal"] == "1")
    task_2 = next(c for c in tasks if c.metadata["ordinal"] == "2")

    assert task_1.text == "Rà soát danh sách học sinh trong độ tuổi tuyển sinh"
    assert task_1.metadata["owner"] == "Phòng Giáo dục và Đào tạo"
    assert task_1.metadata["coordinating_unit"] == "Ủy ban nhân dân các xã, phường"
    assert task_1.metadata["deadline"] == "2026-08-15"
    assert task_1.section_path == [
        "II. NỘI DUNG THỰC HIỆN",
        "1. Rà soát danh sách học sinh trong độ tuổi tuyển sinh",
    ]
    assert task_1.source_page_numbers == [1]

    assert task_2.text == "Tổ chức tiếp nhận hồ sơ tuyển sinh trực tuyến"
    assert task_2.metadata["owner"] == "Trường Tiểu học Mai Giang"
    assert task_2.metadata["coordinating_unit"] == "Phòng Giáo dục và Đào tạo"
    assert task_2.metadata["deadline"] == "2026-08-30"
    assert task_2.section_path == [
        "II. NỘI DUNG THỰC HIỆN",
        "2. Tổ chức tiếp nhận hồ sơ tuyển sinh trực tuyến",
    ]
    assert task_2.source_page_numbers == [2]

    # 4. Assert content chunk hierarchy relationship
    assert content_chunks[0].parent_chunk_id == task_1.chunk_id
    assert content_chunks[0].text == "Thực hiện rà soát tại từng địa bàn dân cư."
    assert content_chunks[0].source_block_ids == ["b_p_0007"]
    assert content_chunks[0].source_page_numbers == [1]

    # 5. Assert partitioning: exactly covers all 12 blocks without duplicates or omissions
    all_block_ids = [block_id for chunk in chunks for block_id in chunk.source_block_ids]
    expected_block_ids = [f"b_p_{i:04d}" for i in range(12)]
    assert sorted(all_block_ids) == expected_block_ids
    assert len(all_block_ids) == len(set(all_block_ids))


def test_plan_and_legal_partitioning_disjoint_claimed_blocks() -> None:
    """Blocks claimed by plan or legal builders must never be re-chunked by fallback."""
    doc = _plan_document(document_type="ke_hoach")
    chunks = build_chunks(doc, document_version=1)

    plan_chunks = [
        c
        for c in chunks
        if c.chunk_type in {ChunkType.PLAN_SECTION, ChunkType.PLAN_TASK}
        or (c.chunk_type == ChunkType.PARAGRAPH and c.metadata.get("classified_by") != "fallback")
    ]
    fallback_chunks = [
        c
        for c in chunks
        if c.chunk_type == ChunkType.PARAGRAPH and c.metadata.get("classified_by") == "fallback"
    ]

    plan_block_ids = {bid for c in plan_chunks for bid in c.source_block_ids}
    fallback_block_ids = {bid for c in fallback_chunks for bid in c.source_block_ids}

    assert plan_block_ids.isdisjoint(fallback_block_ids)
    assert len(plan_block_ids) == 11
    assert fallback_block_ids == {"b_p_0001"}


# ---------------------------------------------------------------------------
# F3: Detailed assertions and edge fixtures
# ---------------------------------------------------------------------------


def test_every_text_block_ends_up_in_exactly_one_chunk() -> None:
    """Removing build_legal_chunks at builder.py:28 must cause this test to fail."""
    doc = _mixed_document()
    chunks = build_chunks(doc, document_version=1)
    all_block_ids = [block_id for chunk in chunks for block_id in chunk.source_block_ids]
    assert sorted(all_block_ids) == ["b_1_0000", "b_1_0001", "b_1_0002"]
    assert len(all_block_ids) == len(set(all_block_ids))

    # Assert specific chunk types for legal + fallback combination
    chunk_types = {chunk.chunk_type for chunk in chunks}
    assert chunk_types == {
        ChunkType.LEGAL_ARTICLE,
        ChunkType.LEGAL_CLAUSE,
        ChunkType.PARAGRAPH,
    }


def test_chunk_field_assertions_page_numbers_parse_run_text_and_types() -> None:
    """Assert all Chunk fields including source_page_numbers, parse_run_id, chunk_type, text."""
    doc = _mixed_document(document_id="doc_test_1", run_id="run_test_1")
    chunks = build_chunks(doc, document_version=5)

    assert len(chunks) == 3

    # Legal article chunk
    article = next(c for c in chunks if c.chunk_type == ChunkType.LEGAL_ARTICLE)
    assert article.chunk_id == "chunk_doc_test_1_run_test_1_h_article_1"
    assert article.parent_chunk_id is None
    assert article.document_id == "doc_test_1"
    assert article.parse_run_id == "run_test_1"
    assert article.document_version == 5
    assert article.document_type == "quyet_dinh"
    assert article.document_number == "57/QĐ-UBND"
    assert article.issuer == "ỦY BAN NHÂN DÂN XÃ MAI GIANG"
    assert article.issued_date == "2026-03-03"
    assert article.section_path == ["Điều 1"]
    assert article.text == "Phạm vi điều chỉnh"
    assert article.source_block_ids == ["b_1_0000"]
    assert article.source_page_numbers == [1]
    assert article.metadata == {"hierarchy_id": "h_article_1", "hierarchy_label": "Điều 1"}

    # Legal clause chunk
    clause = next(c for c in chunks if c.chunk_type == ChunkType.LEGAL_CLAUSE)
    assert clause.chunk_id == "chunk_doc_test_1_run_test_1_h_clause_1_1"
    assert clause.parent_chunk_id == article.chunk_id
    assert clause.document_id == "doc_test_1"
    assert clause.parse_run_id == "run_test_1"
    assert clause.document_version == 5
    assert clause.document_type == "quyet_dinh"
    assert clause.document_number == "57/QĐ-UBND"
    assert clause.issuer == "ỦY BAN NHÂN DÂN XÃ MAI GIANG"
    assert clause.issued_date == "2026-03-03"
    assert clause.section_path == ["Điều 1", "Khoản 1"]
    assert clause.text == "Quy chế này áp dụng cho toàn bộ cơ quan đơn vị."
    assert clause.source_block_ids == ["b_1_0001"]
    assert clause.source_page_numbers == [1]
    assert clause.metadata == {"hierarchy_id": "h_clause_1_1", "hierarchy_label": "Khoản 1"}

    # Fallback paragraph chunk (page 2)
    fallback = next(c for c in chunks if c.chunk_type == ChunkType.PARAGRAPH)
    assert fallback.chunk_id == "chunk_doc_test_1_run_test_1_fallback_b_1_0002"
    assert fallback.parent_chunk_id is None
    assert fallback.document_id == "doc_test_1"
    assert fallback.parse_run_id == "run_test_1"
    assert fallback.document_version == 5
    assert fallback.document_type == "quyet_dinh"
    assert fallback.document_number == "57/QĐ-UBND"
    assert fallback.issuer == "ỦY BAN NHÂN DÂN XÃ MAI GIANG"
    assert fallback.issued_date == "2026-03-03"
    assert fallback.section_path == []
    assert fallback.text == "Ghi chú tự do không thuộc điều khoản nào."
    assert fallback.source_block_ids == ["b_1_0002"]
    assert fallback.source_page_numbers == [2]
    assert fallback.metadata == {"classified_by": "fallback"}


def test_empty_document_produces_zero_chunks() -> None:
    """An empty document with zero pages and zero hierarchy produces an empty chunk list."""
    doc = CanonicalDocument(
        document_id="doc_empty",
        parser_run=_parser_run("run_empty"),
        pages=[],
        hierarchy=[],
        extracted_fields=[],
        quality_report=QualityReport(route="born_digital", route_confidence=0.99),
    )
    chunks = build_chunks(doc, document_version=1)
    assert chunks == []


def test_zero_element_page_blocks_produces_zero_chunks() -> None:
    """A document with pages containing zero blocks produces an empty chunk list."""
    page = CanonicalPage(page_number=1, width=595.0, height=842.0, blocks=[])
    doc = CanonicalDocument(
        document_id="doc_zero_blocks",
        parser_run=_parser_run("run_zero"),
        pages=[page],
        hierarchy=[],
        extracted_fields=[],
        quality_report=QualityReport(route="born_digital", route_confidence=0.99),
    )
    chunks = build_chunks(doc, document_version=1)
    assert chunks == []


def test_single_element_fallback_document() -> None:
    """A document with exactly one fallback paragraph block produces one fallback chunk."""
    block = CanonicalBlock(
        id="b_single_0",
        type=BlockType.PARAGRAPH,
        text="Văn bản thông báo đơn lẻ một đoạn.",
        reading_order=0,
        provenance=BlockProvenance(page_number=1),
    )
    page = CanonicalPage(page_number=1, width=595.0, height=842.0, blocks=[block])
    doc = CanonicalDocument(
        document_id="doc_single_fb",
        parser_run=_parser_run("run_single_fb"),
        pages=[page],
        hierarchy=[],
        extracted_fields=[_extracted("document_type", "thong_bao")],
        quality_report=QualityReport(route="born_digital", route_confidence=0.99),
    )
    chunks = build_chunks(doc, document_version=1)
    assert len(chunks) == 1
    chunk = chunks[0]
    assert chunk.chunk_id == "chunk_doc_single_fb_run_single_fb_fallback_b_single_0"
    assert chunk.parent_chunk_id is None
    assert chunk.chunk_type == ChunkType.PARAGRAPH
    assert chunk.text == "Văn bản thông báo đơn lẻ một đoạn."
    assert chunk.source_block_ids == ["b_single_0"]
    assert chunk.source_page_numbers == [1]
    assert chunk.document_version == 1
    assert chunk.metadata == {"classified_by": "fallback"}


def test_single_element_legal_document() -> None:
    """A document with exactly one legal hierarchy node produces one legal chunk."""
    block = CanonicalBlock(
        id="b_single_leg",
        type=BlockType.HEADING,
        text="Điều 1. Tên gọi và trụ sở",
        reading_order=0,
        parent_id="h_art_single",
        provenance=BlockProvenance(page_number=1),
    )
    page = CanonicalPage(page_number=1, width=595.0, height=842.0, blocks=[block])
    hierarchy = [
        HierarchyNode(
            id="h_art_single",
            kind=HierarchyKind.ARTICLE,
            label="Điều 1",
            text="Tên gọi và trụ sở",
            parent_id=None,
            source_block_ids=["b_single_leg"],
            ordinal=1,
        )
    ]
    doc = CanonicalDocument(
        document_id="doc_single_leg",
        parser_run=_parser_run("run_single_leg"),
        pages=[page],
        hierarchy=hierarchy,
        extracted_fields=[_extracted("document_type", "quyet_dinh")],
        quality_report=QualityReport(route="born_digital", route_confidence=0.99),
    )
    chunks = build_chunks(doc, document_version=2)
    assert len(chunks) == 1
    chunk = chunks[0]
    assert chunk.chunk_id == "chunk_doc_single_leg_run_single_leg_h_art_single"
    assert chunk.parent_chunk_id is None
    assert chunk.chunk_type == ChunkType.LEGAL_ARTICLE
    assert chunk.text == "Tên gọi và trụ sở"
    assert chunk.source_block_ids == ["b_single_leg"]
    assert chunk.source_page_numbers == [1]
    assert chunk.document_version == 2
    assert chunk.metadata == {"hierarchy_id": "h_art_single", "hierarchy_label": "Điều 1"}


def test_none_and_missing_optional_fields_propagate_honestly() -> None:
    """When optional metadata fields are missing, chunks keep them as None."""
    doc = _mixed_document(include_optional_fields=False)
    chunks = build_chunks(doc, document_version=None)

    assert len(chunks) == 3
    for chunk in chunks:
        assert chunk.document_version is None
        assert chunk.document_type is None
        assert chunk.document_number is None
        assert chunk.issuer is None
        assert chunk.issued_date is None
        assert chunk.parse_run_id == "run_mixed_1"
        assert chunk.document_id == "doc_mixed_1"
        assert len(chunk.source_page_numbers) > 0
        assert len(chunk.text) > 0


def test_version_and_parse_run_isolation_on_same_document() -> None:
    """Same document_id with different version and parse_run must produce disjoint chunk sets."""
    doc_v1 = _mixed_document(document_id="doc_same_1", run_id="run_v1")
    doc_v2 = _mixed_document(document_id="doc_same_1", run_id="run_v2")

    chunks_v1 = build_chunks(doc_v1, document_version=1)
    chunks_v2 = build_chunks(doc_v2, document_version=2)

    ids_v1 = {chunk.chunk_id for chunk in chunks_v1}
    ids_v2 = {chunk.chunk_id for chunk in chunks_v2}

    assert ids_v1.isdisjoint(ids_v2)

    for chunk in chunks_v1:
        assert chunk.document_id == "doc_same_1"
        assert chunk.parse_run_id == "run_v1"
        assert chunk.document_version == 1
        if chunk.parent_chunk_id is not None:
            assert chunk.parent_chunk_id in ids_v1
            assert "run_v1" in chunk.parent_chunk_id

    for chunk in chunks_v2:
        assert chunk.document_id == "doc_same_1"
        assert chunk.parse_run_id == "run_v2"
        assert chunk.document_version == 2
        if chunk.parent_chunk_id is not None:
            assert chunk.parent_chunk_id in ids_v2
            assert "run_v2" in chunk.parent_chunk_id


def test_scope_leak_document_and_version_are_never_mixed_across_two_documents() -> None:
    """Chunks from distinct documents must have disjoint chunk IDs and preserve provenance."""
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


def test_chunking_is_deterministic_across_repeated_builds() -> None:
    """Repeated calls with identical document and version must produce identical chunks."""
    doc = _plan_document()
    first = build_chunks(doc, document_version=1)
    second = build_chunks(doc, document_version=1)

    assert [c.chunk_id for c in first] == [c.chunk_id for c in second]
    assert [c.text for c in first] == [c.text for c in second]
    assert [c.model_dump() for c in first] == [c.model_dump() for c in second]
