"""Golden test: a synthetic `Kế hoạch` (plan) fixture with two nested tasks must
survive chunking with its task-owner-deadline relations intact and never
cross-associated (Task A's deadline must never attach to Task B, or vice versa).

The fixture text is authored by hand from
`tests/fixtures/eval/ke_hoach_nested_tasks.case.json`, never derived from parser
output, so this test cannot grade itself.
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
    ExtractedField,
    Extractor,
    ParserRun,
    QualityReport,
)
from mamagift_eval.metrics import (
    nested_hierarchy_f1,
    task_deadline_association_accuracy,
    task_order_accuracy,
    task_owner_association_accuracy,
    task_recall,
)
from mamagift_eval.schemas import ParserSemanticCase
from mamagift_retrieval.chunk import ChunkType
from mamagift_retrieval.chunking import build_chunks

FIXTURE_PATH = (
    Path(__file__).resolve().parents[1] / "fixtures" / "eval" / "ke_hoach_nested_tasks.case.json"
)

pytestmark = pytest.mark.golden

_LINES = [
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


def _load_case() -> ParserSemanticCase:
    return ParserSemanticCase.model_validate(json.loads(FIXTURE_PATH.read_text(encoding="utf-8")))


def _document(case: ParserSemanticCase) -> CanonicalDocument:
    blocks = [
        CanonicalBlock(
            id=f"b_1_{index:04d}",
            type=BlockType.PARAGRAPH,
            text=line,
            reading_order=index,
            provenance=BlockProvenance(page_number=1),
        )
        for index, line in enumerate(_LINES)
    ]
    page = CanonicalPage(page_number=1, width=595.0, height=842.0, blocks=blocks)
    extracted_fields = [
        ExtractedField(
            id=f"field_{name}",
            name=name,
            raw_value=value,
            normalized_value=value,
            extractor=Extractor(name="test", version="1.0"),
        )
        for name, value in case.expected_critical_fields.items()
        if value is not None
    ]
    return CanonicalDocument(
        document_id=case.document_id,
        parser_run=ParserRun(
            id="run_ke_hoach_nested_tasks_01",
            parser_name="pymupdf",
            parser_version="1.0",
            configuration_hash="0" * 16,
            started_at="2026-01-01T00:00:00+00:00",
            finished_at="2026-01-01T00:00:01+00:00",
        ),
        pages=[page],
        extracted_fields=extracted_fields,
        quality_report=QualityReport(route="born_digital", route_confidence=0.99),
    )


def test_ke_hoach_nested_tasks_chunk_metrics_are_perfect() -> None:
    case = _load_case()
    document = _document(case)
    chunks = build_chunks(document)

    assert task_recall(case.expected_task_relations, chunks) == 1.0
    assert task_order_accuracy(case.expected_task_relations, chunks) == 1.0
    assert task_owner_association_accuracy(case.expected_task_relations, chunks) == 1.0
    assert task_deadline_association_accuracy(case.expected_task_relations, chunks) == 1.0
    assert nested_hierarchy_f1(case.expected_hierarchy_labels, chunks) == 1.0


def test_two_tasks_with_different_deadlines_never_cross_associate() -> None:
    case = _load_case()
    chunks = build_chunks(_document(case))
    tasks = {
        chunk.metadata["ordinal"]: chunk
        for chunk in chunks
        if chunk.chunk_type == ChunkType.PLAN_TASK
    }

    expected_by_ordinal = {item.task_ordinal: item for item in case.expected_task_relations}
    for ordinal, expected in expected_by_ordinal.items():
        actual = tasks[ordinal]
        assert actual.metadata["owner"] == expected.owner
        assert actual.metadata["coordinating_unit"] == expected.coordinating_unit
        assert actual.metadata["deadline"] == expected.deadline

    # The regression this fixture exists to catch: swapping which task a value
    # would need to land on must be detectably different from the correct mapping.
    # 8-point locality matrix: 4 positive assertions (verified in loop above:
    # Task 1 owner/deadline and Task 2 owner/deadline) and 4 negative assertions:
    assert tasks["1"].metadata["owner"] != expected_by_ordinal["2"].owner
    assert tasks["1"].metadata["deadline"] != expected_by_ordinal["2"].deadline
    assert tasks["2"].metadata["owner"] != expected_by_ordinal["1"].owner
    assert tasks["2"].metadata["deadline"] != expected_by_ordinal["1"].deadline

    assert tasks["1"].metadata["deadline"] != tasks["2"].metadata["deadline"]
    assert tasks["1"].metadata["owner"] != tasks["2"].metadata["owner"]
