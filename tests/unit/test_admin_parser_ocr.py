"""Regression coverage for noisy OCR in Vietnamese administrative documents.

The samples are synthetic and intentionally small.  They model only the text-layer
failures under test; no private document text or PDF artifact is stored here.
"""

from __future__ import annotations

import pytest
from tools.parser_bench.critical_fields import extract_critical_fields

from mamagift_docpipe import (
    BlockProvenance,
    BlockType,
    CanonicalBlock,
    CanonicalDocument,
    CanonicalPage,
    HierarchyKind,
    ParserRun,
    QualityReport,
    ReviewStatus,
    parse_admin_document,
)
from mamagift_docpipe.admin import patterns

pytestmark = pytest.mark.unit


def make_document(*pages: list[str]) -> CanonicalDocument:
    """Build a canonical OCR document while retaining explicit source provenance."""
    canonical_pages = []
    for page_number, texts in enumerate(pages, start=1):
        blocks = [
            CanonicalBlock(
                id=f"b_{page_number}_{index:04d}",
                type=BlockType.PARAGRAPH,
                text=text,
                reading_order=index,
                provenance=BlockProvenance(
                    page_number=page_number,
                    provider_block_id=f"ocr-{page_number}-{index}",
                ),
            )
            for index, text in enumerate(texts)
        ]
        canonical_pages.append(
            CanonicalPage(
                page_number=page_number,
                width=595.0,
                height=842.0,
                blocks=blocks,
            )
        )

    return CanonicalDocument(
        document_id="synthetic_ocr_regression",
        parser_run=ParserRun(
            id="prun_ocr_regression",
            parser_name="synthetic-ocr",
            parser_version="1.0",
            configuration_hash="0" * 16,
            started_at="2026-01-01T00:00:00+00:00",
            finished_at="2026-01-01T00:00:01+00:00",
        ),
        pages=canonical_pages,
        quality_report=QualityReport(route="scanned", route_confidence=0.9),
    )


def fields_by_name(document: CanonicalDocument):
    return {field.name: field for field in document.extracted_fields}


def test_ocr_matching_key_normalizes_accents_and_spacing_without_mutating_source() -> None:
    raw = "BỘGIÁODỤCVÀĐÀOTẠO"

    assert patterns.compact_matching_key(raw) == "BOGIAODUCVADAOTAO"
    assert patterns.strip_accents_upper(raw) == "BOGIAODUCVADAOTAO"
    assert raw == "BỘGIÁODỤCVÀĐÀOTẠO"


@pytest.mark.parametrize(
    "header_line",
    [
        "Hà Nội, ngày31tháng03năm2026",
        "Hà Nội, ngày 31 tháng03 năm 2026",
    ],
)
def test_header_issue_date_beats_older_referenced_date_despite_compact_ocr_spacing(
    header_line: str,
) -> None:
    document = make_document(
        [
            "BỘ GIÁO DỤC VÀ ĐÀO TẠO",
            "Số: 1234/BGDĐT-GDTH",
            header_line,
            "V/v hướng dẫn thực hiện nhiệm vụ năm học",
            "Căn cứ Quyết định số 99/QĐ-BGDĐT ngày 30 tháng 12 năm 2024.",
        ]
    )

    parsed = parse_admin_document(document)
    issue_date = fields_by_name(parsed)["issue_date"]

    assert issue_date.normalized_value == "2026-03-31"
    assert issue_date.raw_value in header_line
    assert issue_date.source_block_ids == ["b_1_0002"]
    assert issue_date.source_page_numbers == [1]


def test_referenced_body_date_is_never_presented_as_a_high_confidence_issue_date() -> None:
    document = make_document(
        [
            "BỘ GIÁO DỤC VÀ ĐÀO TẠO",
            "Số: 1234/BGDĐT-GDTH",
            "V/v hướng dẫn thực hiện nhiệm vụ năm học",
            "Căn cứ Quyết định số 99/QĐ-BGDĐT ngày30tháng12năm2024.",
        ]
    )

    parsed = parse_admin_document(document)
    issue_date = fields_by_name(parsed).get("issue_date")

    assert parsed.quality_report.requires_user_review is True
    assert issue_date is None
    assert "issue_date: not found" in parsed.quality_report.critical_field_warnings


def test_unqualified_late_page_date_remains_review_required() -> None:
    document = make_document(
        [
            "BỘ GIÁO DỤC VÀ ĐÀO TẠO",
            "Số: 1234/BGDĐT-GDTH",
            "V/v hướng dẫn thực hiện nhiệm vụ năm học",
            "Căn cứ Luật Giáo dục ngày 30 tháng 12 năm 2024.",
        ],
        ["Hà Nội, ngày 31 tháng 03 năm 2026"],
    )

    parsed = parse_admin_document(document)
    issue_date = fields_by_name(parsed)["issue_date"]

    assert issue_date.normalized_value == "2026-03-31"
    assert issue_date.confidence is not None and issue_date.confidence < 0.75
    assert issue_date.review_status == ReviewStatus.NEEDS_REVIEW
    assert issue_date.source_page_numbers == [2]


def test_conflicting_header_dates_and_numbers_are_never_accepted_without_review() -> None:
    document = make_document(
        [
            "BỘ GIÁO DỤC VÀ ĐÀO TẠO",
            "Số: 1234/BGDĐT-GDTH",
            "S: 5678/BGDĐT-GDTH",
            "Hà Nội, ngày 31 tháng 03 năm 2026",
            "Hà Nội, ngày 30 tháng 03 năm 2026",
            "V/v hướng dẫn thực hiện nhiệm vụ năm học",
        ]
    )

    parsed = parse_admin_document(document)
    fields = fields_by_name(parsed)

    assert parsed.quality_report.requires_user_review is True

    cases = {
        "document_number": (
            {"1234/BGDĐT-GDTH", "5678/BGDĐT-GDTH"},
            [["b_1_0001"], ["b_1_0002"]],
        ),
        "issue_date": (
            {"2026-03-30", "2026-03-31"},
            [["b_1_0003"], ["b_1_0004"]],
        ),
    }
    for name, (allowed_values, allowed_sources) in cases.items():
        field = fields.get(name)
        if field is None:
            assert f"{name}: not found" in parsed.quality_report.critical_field_warnings
            continue
        assert field.normalized_value in allowed_values
        assert field.confidence is not None and field.confidence < 0.75
        assert field.review_status == ReviewStatus.NEEDS_REVIEW
        assert field.source_block_ids in allowed_sources
        assert field.source_page_numbers == [1]
        assert any(
            warning.startswith(f"{name}: low confidence")
            for warning in parsed.quality_report.critical_field_warnings
        )

    # The benchmark extractor now delegates to `parse_admin_document`, so it must
    # return exactly the same retained/omitted values as the product path above —
    # never a second, independently-computed answer for the same conflict.
    benchmark_fields = extract_critical_fields(document)
    assert benchmark_fields["document_number"] == (
        fields["document_number"].normalized_value if "document_number" in fields else None
    )
    assert benchmark_fields["issue_date"] == (
        fields["issue_date"].normalized_value if "issue_date" in fields else None
    )


@pytest.mark.parametrize("number_label", ["Số:", "S:"])
def test_document_number_issuer_and_title_tolerate_common_ocr_forms(
    number_label: str,
) -> None:
    document = make_document(
        [
            "BO GIAO DUC VA DAO TAO",
            f"{number_label} 1234/BGDĐT-GDTH",
            "Hà Nội, ngày 31 tháng 03 năm 2026",
            "Ve viec: huong dan thuc hien nhiem vu nam hoc",
        ]
    )

    parsed = parse_admin_document(document)
    fields = fields_by_name(parsed)

    expected = {
        "issuer": ("BO GIAO DUC VA DAO TAO", "b_1_0000"),
        "document_number": ("1234/BGDĐT-GDTH", "b_1_0001"),
        "title": ("huong dan thuc hien nhiem vu nam hoc", "b_1_0003"),
    }
    for name, (value, block_id) in expected.items():
        field = fields[name]
        assert field.normalized_value == value
        assert field.source_block_ids == [block_id]
        assert field.source_page_numbers == [1]


def test_compact_issuer_and_subject_labels_are_detected_without_rewriting_raw_text() -> None:
    raw = [
        "BỘGIÁODỤCVÀĐÀOTẠO",
        "S:1234/BGDĐT-GDTH",
        "Hà Nội, ngày31tháng03năm2026",
        "Veviec: huong dan thuc hien nhiem vu nam hoc",
    ]
    parsed = parse_admin_document(make_document(raw))
    fields = fields_by_name(parsed)

    assert fields["issuer"].normalized_value == raw[0]
    assert fields["document_number"].normalized_value == "1234/BGDĐT-GDTH"
    assert fields["title"].normalized_value == "huong dan thuc hien nhiem vu nam hoc"
    assert [block.text for block in parsed.iter_blocks()] == raw


def test_ocr_hierarchy_variants_keep_parentage_and_source_block_page_provenance() -> None:
    document = make_document(
        ["BỘ GIÁO DỤC VÀ ĐÀO TẠO"],
        [
            "Điu 7. Hồ sơ tuyển sinh",
            "khon 2. Thành phần hồ sơ",
            "Điểm a) Bản sao giấy khai sinh",
        ],
    )

    parsed = parse_admin_document(document)
    nodes = {node.kind: node for node in parsed.hierarchy}
    article = nodes[HierarchyKind.ARTICLE]
    clause = nodes[HierarchyKind.CLAUSE]
    point = nodes[HierarchyKind.POINT]

    assert (article.label, article.parent_id, article.source_block_ids) == (
        "Điều 7",
        None,
        ["b_2_0000"],
    )
    assert (clause.label, clause.parent_id, clause.source_block_ids) == (
        "Khoản 2",
        article.id,
        ["b_2_0001"],
    )
    assert (point.label, point.parent_id, point.source_block_ids) == (
        "Điểm a",
        clause.id,
        ["b_2_0002"],
    )

    blocks = {block.id: block for block in parsed.iter_blocks()}
    assert blocks["b_2_0000"].parent_id == article.id
    assert blocks["b_2_0001"].parent_id == clause.id
    assert blocks["b_2_0002"].parent_id == point.id
    for node in (article, clause, point):
        assert {
            blocks[source_id].provenance.page_number for source_id in node.source_block_ids
        } == {2}


def test_admin_enrichment_does_not_mutate_or_rewrite_raw_ocr_blocks() -> None:
    raw_text = [
        "BO GIAO DUC VA DAO TAO",
        "S: 1234/BGDĐT-GDTH",
        "Hà Nội, ngày31tháng03năm2026",
        "Điu 7. Hồ sơ tuyển sinh",
        "khon 2. Thành phần hồ sơ",
        "Điểm a) Bản sao giấy khai sinh",
    ]
    document = make_document(raw_text)
    before = document.model_dump()

    parsed = parse_admin_document(document)

    assert document.model_dump() == before
    assert [block.text for block in parsed.iter_blocks()] == raw_text
    assert [block.provenance.provider_block_id for block in parsed.iter_blocks()] == [
        f"ocr-1-{index}" for index in range(len(raw_text))
    ]
