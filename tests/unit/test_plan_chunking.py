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


def _plan_document(document_type: str = "ke_hoach") -> CanonicalDocument:
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
    page = CanonicalPage(page_number=1, width=595.0, height=842.0, blocks=blocks)
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
        pages=[page],
        extracted_fields=[
            _extracted("document_type", document_type),
            _extracted("document_number", "12/KH-UBND"),
        ],
        quality_report=QualityReport(route="born_digital", route_confidence=0.99),
    )


def _tasks(chunks: list[Chunk]) -> dict[str, Chunk]:
    return {
        chunk.metadata["ordinal"]: chunk
        for chunk in chunks
        if chunk.chunk_type == ChunkType.PLAN_TASK
    }


def test_non_plan_document_produces_no_plan_chunks() -> None:
    document = _plan_document(document_type="quyet_dinh")
    assert build_plan_chunks(document) == []


def test_two_major_sections_and_two_tasks_are_found() -> None:
    chunks = build_plan_chunks(_plan_document())
    sections = [chunk for chunk in chunks if chunk.chunk_type == ChunkType.PLAN_SECTION]
    tasks = _tasks(chunks)
    assert len(sections) == 2
    assert set(tasks) == {"1", "2"}


def test_task_owner_and_deadline_never_cross_associate() -> None:
    tasks = _tasks(build_plan_chunks(_plan_document()))

    task_1, task_2 = tasks["1"], tasks["2"]
    assert task_1.metadata["owner"] == "Phòng Giáo dục và Đào tạo"
    assert task_1.metadata["deadline"] == "2026-08-15"
    assert task_2.metadata["owner"] == "Trường Tiểu học Mai Giang"
    assert task_2.metadata["deadline"] == "2026-08-30"

    # The specific failure this module exists to prevent: Task 2's values must never
    # equal Task 1's, and neither task's deadline may leak into the other.
    assert task_1.metadata["deadline"] != task_2.metadata["deadline"]
    assert task_1.metadata["owner"] != task_2.metadata["owner"]


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


def test_task_provenance_covers_its_own_lines_only() -> None:
    tasks = _tasks(build_plan_chunks(_plan_document()))
    task_1_blocks = set(tasks["1"].source_block_ids)
    task_2_blocks = set(tasks["2"].source_block_ids)
    assert task_1_blocks.isdisjoint(task_2_blocks)


def test_chunk_ids_are_deterministic_across_repeated_builds() -> None:
    document = _plan_document()
    first = [chunk.chunk_id for chunk in build_plan_chunks(document)]
    second = [chunk.chunk_id for chunk in build_plan_chunks(document)]
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
    validate_chunk_tree(chunks)
