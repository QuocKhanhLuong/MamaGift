"""Tests for the deterministic `Kế hoạch` (plan) structure chunker.

The critical property under test is that each task's owner/coordinating-unit/
deadline metadata is scoped to that task alone: Task B's deadline must never attach
to Task A, even though both tasks share the same regex-driven parsing pass.
"""

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
    ParserRun,
    QualityReport,
)
from mamagift_retrieval.chunk import Chunk, ChunkType, validate_chunk_tree
from mamagift_retrieval.chunking.plan import build_plan_chunks

pytestmark = pytest.mark.unit


def _extracted(name: str, value: str) -> ExtractedField:
    return ExtractedField(
        id=f"field_{name}",
        name=name,
        raw_value=value,
        normalized_value=value,
        extractor=Extractor(name="test", version="1.0"),
    )


def _paragraph(
    block_id: str, text: str, reading_order: int, page_number: int = 1
) -> CanonicalBlock:
    return CanonicalBlock(
        id=block_id,
        type=BlockType.PARAGRAPH,
        text=text,
        reading_order=reading_order,
        provenance=BlockProvenance(page_number=page_number),
    )


def _plan_document(
    document_type: str | None = "ke_hoach",
    pages: list[CanonicalPage] | None = None,
) -> CanonicalDocument:
    if pages is None:
        lines = [
            "I. MỤC ĐÍCH, YÊU CẦU",
            "Bảo đảm công tác tuyển sinh diễn ra đúng quy định.",
            "II. NỘI DUNG THỰC HIỆN",
            "1. Rà soát danh sách học sinh trong độ tuổi tuyển sinh",
            "Đơn vị chủ trì: Phòng Giáo dục và Đào tạo",
            "Đơn vị phối hợp: Ủy ban nhân dân các xã, phường",
            "Thời hạn hoàn thành: trước ngày 15 tháng 08 năm 2026",
            "2. Tổ chức tiếp nhận hồ sơ tuyển sinh trực tuyến",
            "Đơn vị chủ trì: Trường Tiểu học Mai Giang",
            "Đơn vị phối hợp: Phòng Giáo dục và Đào tạo",
            "Thời hạn hoàn thành: trước ngày 30 tháng 08 năm 2026",
        ]
        blocks = [_paragraph(f"b_1_{index:04d}", line, index) for index, line in enumerate(lines)]
        pages = [CanonicalPage(page_number=1, width=595.0, height=842.0, blocks=blocks)]

    extracted_fields: list[ExtractedField] = []
    if document_type is not None:
        extracted_fields.append(_extracted("document_type", document_type))
    extracted_fields.append(_extracted("document_number", "12/KH-UBND"))

    return CanonicalDocument(
        document_id="doc_plan_1",
        parser_run=ParserRun(
            id="run_plan_1",
            parser_name="pymupdf",
            parser_version="1.0",
            configuration_hash="0" * 16,
            started_at="2026-01-01T00:00:00+00:00",
            finished_at="2026-01-01T00:00:01+00:00",
        ),
        pages=pages,
        extracted_fields=extracted_fields,
        quality_report=QualityReport(route="born_digital", route_confidence=0.99),
    )


def _tasks(chunks: list[Chunk]) -> dict[str, Chunk]:
    return {
        chunk.metadata["ordinal"]: chunk
        for chunk in chunks
        if chunk.chunk_type == ChunkType.PLAN_TASK
    }


def test_non_plan_document_produces_no_plan_chunks() -> None:
    assert build_plan_chunks(_plan_document(document_type="quyet_dinh")) == []
    assert build_plan_chunks(_plan_document(document_type=None)) == []
    assert build_plan_chunks(_plan_document(pages=[])) == []


def test_plan_with_zero_tasks_produces_only_section_chunks() -> None:
    lines = [
        "I. MỤC ĐÍCH, YÊU CẦU",
        "Bảo đảm công tác tuyển sinh diễn ra đúng quy định.",
        "II. NGUYÊN TẮC THỰC HIỆN",
        "Thực hiện công khai, minh bạch, đúng tuyến.",
    ]
    blocks = [_paragraph(f"b_0_{i:04d}", line, i) for i, line in enumerate(lines)]
    page = CanonicalPage(page_number=1, width=595.0, height=842.0, blocks=blocks)
    doc = _plan_document(pages=[page])

    chunks = build_plan_chunks(doc, document_version=1)
    sections = [c for c in chunks if c.chunk_type == ChunkType.PLAN_SECTION]
    tasks = [c for c in chunks if c.chunk_type == ChunkType.PLAN_TASK]

    assert len(sections) == 2
    assert len(tasks) == 0
    assert sections[0].metadata["ordinal"] == "I"
    assert sections[0].text == "MỤC ĐÍCH, YÊU CẦU"
    assert sections[0].document_version == 1
    assert sections[1].metadata["ordinal"] == "II"
    assert sections[1].text == "NGUYÊN TẮC THỰC HIỆN"
    assert sections[1].document_version == 1
    validate_chunk_tree(chunks)


def test_single_section_single_task_plan() -> None:
    lines = [
        "I. KẾ HOẠCH TRIỂN KHAI",
        "1. Xây dựng kế hoạch chi tiết",
        "Đơn vị chủ trì: Sở GD&ĐT",
        "Đơn vị phối hợp: Sở Tài chính",
        "Thời hạn: ngày 15/09/2026",
    ]
    blocks = [_paragraph(f"b_s_{i:04d}", line, i) for i, line in enumerate(lines)]
    page = CanonicalPage(page_number=1, width=595.0, height=842.0, blocks=blocks)
    doc = _plan_document(pages=[page])

    chunks = build_plan_chunks(doc, document_version=2)
    assert len(chunks) == 2
    section = next(c for c in chunks if c.chunk_type == ChunkType.PLAN_SECTION)
    task = next(c for c in chunks if c.chunk_type == ChunkType.PLAN_TASK)

    assert section.chunk_id == "chunk:doc_plan_1:v2:run_plan_1:plan_section_01"
    assert section.parent_chunk_id is None
    assert section.document_version == 2
    assert task.chunk_id == "chunk:doc_plan_1:v2:run_plan_1:plan_task_001"
    assert task.parent_chunk_id == section.chunk_id
    assert task.document_version == 2
    assert task.metadata["owner"] == "Sở GD&ĐT"
    assert task.metadata["coordinating_unit"] == "Sở Tài chính"
    assert task.metadata["deadline_raw"] == "ngày 15/09/2026"
    assert task.metadata["deadline"] == "2026-09-15"
    validate_chunk_tree(chunks)


def test_two_major_sections_and_two_tasks_are_found() -> None:
    chunks = build_plan_chunks(_plan_document())
    sections = [chunk for chunk in chunks if chunk.chunk_type == ChunkType.PLAN_SECTION]
    tasks = _tasks(chunks)
    assert len(sections) == 2
    assert [s.metadata["ordinal"] for s in sections] == ["I", "II"]
    assert [s.text for s in sections] == ["MỤC ĐÍCH, YÊU CẦU", "NỘI DUNG THỰC HIỆN"]
    assert set(tasks) == {"1", "2"}
    assert tasks["1"].text == "Rà soát danh sách học sinh trong độ tuổi tuyển sinh"
    assert tasks["2"].text == "Tổ chức tiếp nhận hồ sơ tuyển sinh trực tuyến"


def test_task_owner_and_deadline_never_cross_associate_and_locality_matrix() -> None:
    chunks = build_plan_chunks(_plan_document())
    tasks = _tasks(chunks)
    task_a, task_b = tasks["1"], tasks["2"]

    owner_a = "Phòng Giáo dục và Đào tạo"
    owner_b = "Trường Tiểu học Mai Giang"
    coord_a = "Ủy ban nhân dân các xã, phường"
    coord_b = "Phòng Giáo dục và Đào tạo"
    deadline_a = "2026-08-15"
    deadline_b = "2026-08-30"
    deadline_raw_a = "trước ngày 15 tháng 08 năm 2026"
    deadline_raw_b = "trước ngày 30 tháng 08 năm 2026"

    # Locality matrix: all 8 positive and negative relations must be verified
    # Positive assertions:
    assert task_a.metadata["owner"] == owner_a
    assert task_a.metadata["deadline"] == deadline_a
    assert task_b.metadata["owner"] == owner_b
    assert task_b.metadata["deadline"] == deadline_b

    # Negative assertions (cross-associations must NOT hold):
    assert task_a.metadata["owner"] != owner_b
    assert task_a.metadata["deadline"] != deadline_b
    assert task_b.metadata["owner"] != owner_a
    assert task_b.metadata["deadline"] != deadline_a

    # Coordinating unit and deadline_raw locality:
    assert task_a.metadata["coordinating_unit"] == coord_a
    assert task_a.metadata["deadline_raw"] == deadline_raw_a
    assert task_b.metadata["coordinating_unit"] == coord_b
    assert task_b.metadata["deadline_raw"] == deadline_raw_b

    assert task_a.metadata["coordinating_unit"] != coord_b
    assert task_a.metadata["deadline_raw"] != deadline_raw_b
    assert task_b.metadata["coordinating_unit"] != coord_a
    assert task_b.metadata["deadline_raw"] != deadline_raw_a


def test_missing_optional_metadata_fields_are_none_and_not_inherited() -> None:
    lines = [
        "II. NỘI DUNG THỰC HIỆN",
        "1. Nhiệm vụ đầy đủ metadata",
        "Đơn vị chủ trì: Phòng Nội vụ",
        "Đơn vị phối hợp: Phòng Tư pháp",
        "Thời hạn hoàn thành: trước ngày 01 tháng 09 năm 2026",
        "2. Nhiệm vụ không có metadata nào",
        "3. Nhiệm vụ không có đơn vị chủ trì",
        "Đơn vị phối hợp: Sở Tài chính",
        "Thời hạn hoàn thành: trước ngày 15 tháng 09 năm 2026",
        "4. Nhiệm vụ không có đơn vị phối hợp",
        "Đơn vị chủ trì: Sở Y tế",
        "Thời hạn hoàn thành: trước ngày 20 tháng 09 năm 2026",
        "5. Nhiệm vụ không có thời hạn",
        "Đơn vị chủ trì: Sở Xây dựng",
        "Đơn vị phối hợp: Sở Giao thông vận tải",
    ]
    blocks = [_paragraph(f"b_m_{i:04d}", line, i) for i, line in enumerate(lines)]
    page = CanonicalPage(page_number=1, width=595.0, height=842.0, blocks=blocks)
    doc = _plan_document(pages=[page])

    tasks = _tasks(build_plan_chunks(doc))

    # Task 1: complete metadata
    t1 = tasks["1"]
    assert t1.metadata["owner"] == "Phòng Nội vụ"
    assert t1.metadata["coordinating_unit"] == "Phòng Tư pháp"
    assert t1.metadata["deadline"] == "2026-09-01"
    assert t1.metadata["deadline_raw"] == "trước ngày 01 tháng 09 năm 2026"

    # Task 2: all missing fields MUST be None (no inheritance from Task 1)
    t2 = tasks["2"]
    assert t2.metadata["owner"] is None
    assert t2.metadata["coordinating_unit"] is None
    assert t2.metadata["deadline"] is None
    assert t2.metadata["deadline_raw"] is None

    # Task 3: missing owner
    t3 = tasks["3"]
    assert t3.metadata["owner"] is None
    assert t3.metadata["coordinating_unit"] == "Sở Tài chính"
    assert t3.metadata["deadline"] == "2026-09-15"
    assert t3.metadata["deadline_raw"] == "trước ngày 15 tháng 09 năm 2026"

    # Task 4: missing coordinating unit
    t4 = tasks["4"]
    assert t4.metadata["owner"] == "Sở Y tế"
    assert t4.metadata["coordinating_unit"] is None
    assert t4.metadata["deadline"] == "2026-09-20"
    assert t4.metadata["deadline_raw"] == "trước ngày 20 tháng 09 năm 2026"

    # Task 5: missing deadline
    t5 = tasks["5"]
    assert t5.metadata["owner"] == "Sở Xây dựng"
    assert t5.metadata["coordinating_unit"] == "Sở Giao thông vận tải"
    assert t5.metadata["deadline"] is None
    assert t5.metadata["deadline_raw"] is None


def test_invalid_date_preserves_deadline_raw_and_sets_deadline_none() -> None:
    lines = [
        "II. NỘI DUNG THỰC HIỆN",
        "1. Nhiệm vụ có hạn không xác định",
        "Đơn vị chủ trì: Phòng Nội vụ",
        "Thời hạn hoàn thành: khi có hướng dẫn của cấp trên",
    ]
    blocks = [_paragraph(f"b_d_{i:04d}", line, i) for i, line in enumerate(lines)]
    page = CanonicalPage(page_number=1, width=595.0, height=842.0, blocks=blocks)
    doc = _plan_document(pages=[page])

    tasks = _tasks(build_plan_chunks(doc))
    t1 = tasks["1"]
    assert t1.metadata["owner"] == "Phòng Nội vụ"
    assert t1.metadata["deadline_raw"] == "khi có hướng dẫn của cấp trên"
    assert t1.metadata["deadline"] is None


def test_task_chunk_parent_is_the_enclosing_section() -> None:
    chunks = build_plan_chunks(_plan_document())
    section = next(
        c
        for c in chunks
        if c.chunk_type == ChunkType.PLAN_SECTION and c.metadata["ordinal"] == "II"
    )
    tasks = _tasks(chunks)
    assert tasks["1"].parent_chunk_id == section.chunk_id
    assert tasks["2"].parent_chunk_id == section.chunk_id
    validate_chunk_tree(chunks)


def test_task_provenance_covers_all_source_blocks_and_pages() -> None:
    chunks = build_plan_chunks(_plan_document())
    sections = [c for c in chunks if c.chunk_type == ChunkType.PLAN_SECTION]
    tasks = _tasks(chunks)

    # Exact section provenance
    assert sections[0].source_block_ids == ["b_1_0000"]
    assert sections[0].source_page_numbers == [1]
    assert sections[1].source_block_ids == ["b_1_0002"]
    assert sections[1].source_page_numbers == [1]

    # Exact task provenance covering heading, owner, coordinating_unit, and deadline blocks
    assert tasks["1"].source_block_ids == ["b_1_0003", "b_1_0004", "b_1_0005", "b_1_0006"]
    assert tasks["1"].source_page_numbers == [1]
    assert tasks["2"].source_block_ids == ["b_1_0007", "b_1_0008", "b_1_0009", "b_1_0010"]
    assert tasks["2"].source_page_numbers == [1]

    # Task blocks must be strictly disjoint
    assert set(tasks["1"].source_block_ids).isdisjoint(set(tasks["2"].source_block_ids))


def test_multi_page_plan_provenance_spans_multiple_pages() -> None:
    p1_blocks = [
        _paragraph("b_p1_0", "I. KẾ HOẠCH NĂM", 0, page_number=1),
        _paragraph("b_p1_1", "1. Triển khai giai đoạn một", 1, page_number=1),
        _paragraph("b_p1_2", "Đơn vị chủ trì: Ban Quản lý dự án", 2, page_number=1),
    ]
    p2_blocks = [
        _paragraph("b_p2_0", "Đơn vị phối hợp: Nhà thầu thi công", 0, page_number=2),
        _paragraph("b_p2_1", "Thời hạn hoàn thành: ngày 10/11/2026", 1, page_number=2),
        _paragraph("b_p2_2", "Chi tiết kỹ thuật thực hiện tại hiện trường.", 2, page_number=2),
        _paragraph("b_p2_3", "2. Nghiệm thu bàn giao", 3, page_number=2),
        _paragraph("b_p2_4", "Đơn vị chủ trì: Hội đồng nghiệm thu", 4, page_number=2),
    ]
    p1 = CanonicalPage(page_number=1, width=595.0, height=842.0, blocks=p1_blocks)
    p2 = CanonicalPage(page_number=2, width=595.0, height=842.0, blocks=p2_blocks)
    doc = _plan_document(pages=[p1, p2])

    chunks = build_plan_chunks(doc, document_version=1)
    tasks = _tasks(chunks)

    t1 = tasks["1"]
    assert t1.source_block_ids == ["b_p1_1", "b_p1_2", "b_p2_0", "b_p2_1"]
    assert t1.source_page_numbers == [1, 2]
    assert t1.metadata["owner"] == "Ban Quản lý dự án"
    assert t1.metadata["coordinating_unit"] == "Nhà thầu thi công"
    assert t1.metadata["deadline"] == "2026-11-10"

    t1_content = next(
        c
        for c in chunks
        if c.chunk_type == ChunkType.PARAGRAPH and c.parent_chunk_id == t1.chunk_id
    )
    assert t1_content.source_block_ids == ["b_p2_2"]
    assert t1_content.source_page_numbers == [2]

    t2 = tasks["2"]
    assert t2.source_block_ids == ["b_p2_3", "b_p2_4"]
    assert t2.source_page_numbers == [2]

    validate_chunk_tree(chunks)


def test_document_version_propagates_to_all_chunk_types() -> None:
    lines = [
        "II. NỘI DUNG THỰC HIỆN",
        "1. Rà soát danh sách học sinh",
        "Đơn vị chủ trì: Phòng Giáo dục",
        "Thực hiện rà soát tại từng địa bàn dân cư.",
    ]
    blocks = [_paragraph(f"b_v_{i:04d}", line, i) for i, line in enumerate(lines)]
    page = CanonicalPage(page_number=1, width=595.0, height=842.0, blocks=blocks)
    doc = _plan_document(pages=[page])

    # Explicit version=5
    chunks_v5 = build_plan_chunks(doc, document_version=5)
    assert len(chunks_v5) == 3
    for chunk in chunks_v5:
        assert chunk.document_version == 5

    section_v5 = next(c for c in chunks_v5 if c.chunk_type == ChunkType.PLAN_SECTION)
    task_v5 = next(c for c in chunks_v5 if c.chunk_type == ChunkType.PLAN_TASK)
    content_v5 = next(c for c in chunks_v5 if c.chunk_type == ChunkType.PARAGRAPH)
    assert section_v5.document_version == 5
    assert task_v5.document_version == 5
    assert content_v5.document_version == 5

    # Default version=None
    chunks_none = build_plan_chunks(doc)
    for chunk in chunks_none:
        assert chunk.document_version is None


def test_multiline_canonical_block_preserves_all_lines_and_metadata() -> None:
    # A single CanonicalBlock containing task header, owner, coordinator, deadline, and body lines
    block_1_text = (
        "1. Nhiệm vụ tích hợp đa dòng\n"
        "Đơn vị chủ trì: Văn phòng UBND\n"
        "Đơn vị phối hợp: Sở Thông tin và Truyền thông\n"
        "Thời hạn hoàn thành: trước ngày 20 tháng 10 năm 2026\n"
        "Dòng nội dung thứ nhất của nhiệm vụ.\n"
        "Dòng nội dung thứ hai của nhiệm vụ."
    )
    # A second block containing multiline body lines
    block_2_text = "Dòng nội dung thứ ba.\nDòng nội dung thứ tư."
    blocks = [
        _paragraph("b_section", "I. KẾ HOẠCH TỔNG THỂ", 0),
        _paragraph("b_multi_1", block_1_text, 1),
        _paragraph("b_multi_2", block_2_text, 2),
    ]
    page = CanonicalPage(page_number=1, width=595.0, height=842.0, blocks=blocks)
    doc = _plan_document(pages=[page])

    chunks = build_plan_chunks(doc, document_version=3)
    assert len(chunks) == 3

    task_chunk = next(c for c in chunks if c.chunk_type == ChunkType.PLAN_TASK)
    content_chunk = next(c for c in chunks if c.chunk_type == ChunkType.PARAGRAPH)

    assert task_chunk.metadata["owner"] == "Văn phòng UBND"
    assert task_chunk.metadata["coordinating_unit"] == "Sở Thông tin và Truyền thông"
    assert task_chunk.metadata["deadline_raw"] == "trước ngày 20 tháng 10 năm 2026"
    assert task_chunk.metadata["deadline"] == "2026-10-20"
    assert task_chunk.source_block_ids == ["b_multi_1"]

    expected_body = (
        "Dòng nội dung thứ nhất của nhiệm vụ.\n"
        "Dòng nội dung thứ hai của nhiệm vụ.\n"
        "Dòng nội dung thứ ba.\n"
        "Dòng nội dung thứ tư."
    )
    assert content_chunk.text == expected_body
    assert content_chunk.source_block_ids == ["b_multi_1", "b_multi_2"]
    validate_chunk_tree(chunks)


def test_duplicate_task_ordinals_generate_unique_chunk_ids() -> None:
    lines = [
        "I. PHẦN MỘT",
        "1. Nhiệm vụ một",
        "II. PHẦN HAI",
        "1. Nhiệm vụ hai",
    ]
    blocks = [_paragraph(f"b_dup_{i:04d}", line, i) for i, line in enumerate(lines)]
    page = CanonicalPage(page_number=1, width=595.0, height=842.0, blocks=blocks)
    doc = _plan_document(pages=[page])

    chunks = build_plan_chunks(doc)
    tasks = [c for c in chunks if c.chunk_type == ChunkType.PLAN_TASK]
    assert len(tasks) == 2
    assert tasks[0].chunk_id != tasks[1].chunk_id
    assert tasks[0].chunk_id == "chunk:doc_plan_1:vnone:run_plan_1:plan_task_001"
    assert tasks[1].chunk_id == "chunk:doc_plan_1:vnone:run_plan_1:plan_task_002"
    validate_chunk_tree(chunks)


def test_plan_chunk_ids_include_document_version_and_isolate_versions() -> None:
    doc = _plan_document()
    v1_chunks = build_plan_chunks(doc, document_version=1)
    v2_chunks = build_plan_chunks(doc, document_version=2)
    vnone_chunks = build_plan_chunks(doc, document_version=None)

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


def test_plan_chunk_ids_do_not_collide_when_identifiers_contain_underscores() -> None:
    doc1 = _plan_document()
    doc1.document_id = "doc_a"
    doc1.parser_run.id = "run_b_c"

    doc2 = _plan_document()
    doc2.document_id = "doc_a_b"
    doc2.parser_run.id = "run_c"

    chunks1 = build_plan_chunks(doc1, document_version=1)
    chunks2 = build_plan_chunks(doc2, document_version=1)

    ids1 = {c.chunk_id for c in chunks1}
    ids2 = {c.chunk_id for c in chunks2}

    assert ids1.isdisjoint(ids2)


def test_plan_chunk_ids_do_not_collide_when_identifiers_contain_colons() -> None:
    doc1 = _plan_document()
    doc1.document_id = "doc:v1"
    doc1.parser_run.id = "run"

    doc2 = _plan_document()
    doc2.document_id = "doc"
    doc2.parser_run.id = "v1:run"

    chunks1 = build_plan_chunks(doc1, document_version=1)
    chunks2 = build_plan_chunks(doc2, document_version=1)

    ids1 = {c.chunk_id for c in chunks1}
    ids2 = {c.chunk_id for c in chunks2}

    assert ids1.isdisjoint(ids2)


def test_chunk_ids_are_deterministic_across_repeated_builds() -> None:
    document = _plan_document()
    first = [chunk.chunk_id for chunk in build_plan_chunks(document, document_version=1)]
    second = [chunk.chunk_id for chunk in build_plan_chunks(document, document_version=1)]
    assert first == second


def test_task_with_body_lines_produces_child_paragraph_chunk() -> None:
    lines = [
        "II. NỘI DUNG THỰC HIỆN",
        "1. Rà soát danh sách học sinh",
        "Đơn vị chủ trì: Phòng Giáo dục",
        "Thực hiện rà soát tại từng địa bàn dân cư.",
        "Tổng hợp số liệu báo cáo trước ngày khai giảng.",
    ]
    blocks = [_paragraph(f"b_1_{index:04d}", line, index) for index, line in enumerate(lines)]
    page = CanonicalPage(page_number=1, width=595.0, height=842.0, blocks=blocks)
    doc = CanonicalDocument(
        document_id="doc_plan_2",
        parser_run=ParserRun(
            id="run_plan_2",
            parser_name="pymupdf",
            parser_version="1.0",
            configuration_hash="0" * 16,
            started_at="2026-01-01T00:00:00+00:00",
            finished_at="2026-01-01T00:00:01+00:00",
        ),
        pages=[page],
        extracted_fields=[_extracted("document_type", "ke_hoach")],
        quality_report=QualityReport(route="born_digital", route_confidence=0.99),
    )
    chunks = build_plan_chunks(doc, document_version=2)
    assert len(chunks) == 3  # section, task, content paragraph
    task_chunk = next(c for c in chunks if c.chunk_type == ChunkType.PLAN_TASK)
    content_chunk = next(c for c in chunks if c.chunk_type == ChunkType.PARAGRAPH)
    assert content_chunk.parent_chunk_id == task_chunk.chunk_id
    assert content_chunk.document_version == 2
    assert "Thực hiện rà soát tại từng địa bàn dân cư." in content_chunk.text
    assert "Tổng hợp số liệu báo cáo trước ngày khai giảng." in content_chunk.text
    validate_chunk_tree(chunks)
