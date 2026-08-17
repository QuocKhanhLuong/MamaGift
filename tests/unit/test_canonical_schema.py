"""CanonicalDocument v1 schema and provenance tests."""

from __future__ import annotations

import unicodedata

import pytest
from pydantic import ValidationError

from bench_support import FIXTURES, make_block, make_page, make_provider_result
from mamagift_docpipe import (
    BBox,
    BlockProvenance,
    BlockType,
    CanonicalBlock,
    CanonicalDocument,
    CanonicalPage,
    CanonicalTable,
    Extractor,
    HierarchyKind,
    HierarchyNode,
    ParseRequest,
    ParserRun,
    QualityReport,
    ReviewStatus,
    normalize_provider_result,
    normalize_text,
)
from mamagift_docpipe.adapters import build_adapter
from mamagift_docpipe.canonical import ExtractedField

pytestmark = pytest.mark.unit


def make_document(**overrides: object) -> CanonicalDocument:
    payload: dict[str, object] = {
        "document_id": "doc_test",
        "parser_run": ParserRun(
            id="prun_test",
            parser_name="test",
            parser_version="1.0",
            configuration_hash="abc",
            started_at="2026-01-01T00:00:00+00:00",
            finished_at="2026-01-01T00:00:01+00:00",
        ),
        "pages": [
            CanonicalPage(
                page_number=1,
                width=595.0,
                height=842.0,
                blocks=[
                    CanonicalBlock(
                        id="b_1_0000",
                        type=BlockType.PARAGRAPH,
                        text="Xin chào",
                        reading_order=0,
                        provenance=BlockProvenance(page_number=1),
                    )
                ],
            )
        ],
        "quality_report": QualityReport(route="born_digital", route_confidence=1.0),
    }
    payload.update(overrides)
    return CanonicalDocument(**payload)  # type: ignore[arg-type]


# ------------------------------------------------------------------ schema rules


def test_minimal_document_validates() -> None:
    document = make_document()
    assert document.schema_version == "1.0"
    assert document.hierarchy == []
    assert document.extracted_fields == []


def test_unsupported_schema_version_is_rejected() -> None:
    with pytest.raises(ValidationError, match="unsupported schema_version"):
        make_document(schema_version="2.0")


def test_pages_must_be_numbered_from_one_in_order() -> None:
    page = CanonicalPage(page_number=2, width=1.0, height=1.0)
    with pytest.raises(ValidationError, match="numbered 1..n"):
        make_document(pages=[page])


def test_duplicate_reading_order_within_a_page_is_rejected() -> None:
    blocks = [
        CanonicalBlock(
            id=f"b_1_{index:04d}",
            type=BlockType.PARAGRAPH,
            text="x",
            reading_order=0,
            provenance=BlockProvenance(page_number=1),
        )
        for index in range(2)
    ]
    with pytest.raises(ValidationError, match="duplicate reading_order"):
        CanonicalPage(page_number=1, width=1.0, height=1.0, blocks=blocks)


def test_block_provenance_must_match_its_page() -> None:
    block = CanonicalBlock(
        id="b_1_0000",
        type=BlockType.PARAGRAPH,
        text="x",
        reading_order=0,
        provenance=BlockProvenance(page_number=7),
    )
    with pytest.raises(ValidationError, match="does not match page"):
        CanonicalPage(page_number=1, width=1.0, height=1.0, blocks=[block])


@pytest.mark.parametrize("rotation", [45, -90, 360])
def test_invalid_rotation_is_rejected(rotation: int) -> None:
    with pytest.raises(ValidationError, match="rotation must be one of"):
        CanonicalPage(page_number=1, width=1.0, height=1.0, rotation=rotation)


def test_bbox_requires_ordered_corners() -> None:
    with pytest.raises(ValidationError, match="x0 <= x1"):
        BBox(x0=10.0, y0=0.0, x1=5.0, y1=10.0)
    with pytest.raises(ValidationError):
        BBox(x0=-1.0, y0=0.0, x1=5.0, y1=10.0)

    assert BBox(x0=1.0, y0=2.0, x1=3.0, y1=4.0).as_list() == [1.0, 2.0, 3.0, 4.0]


def test_confidence_is_bounded() -> None:
    with pytest.raises(ValidationError):
        CanonicalBlock(
            id="b",
            type=BlockType.PARAGRAPH,
            text="x",
            reading_order=0,
            confidence=1.5,
            provenance=BlockProvenance(page_number=1),
        )


def test_dangling_references_are_rejected() -> None:
    with pytest.raises(ValidationError, match="unknown parent"):
        make_document(
            pages=[
                CanonicalPage(
                    page_number=1,
                    width=1.0,
                    height=1.0,
                    blocks=[
                        CanonicalBlock(
                            id="b_1_0000",
                            type=BlockType.PARAGRAPH,
                            text="x",
                            reading_order=0,
                            parent_id="h_missing",
                            provenance=BlockProvenance(page_number=1),
                        )
                    ],
                )
            ]
        )

    with pytest.raises(ValidationError, match="unknown block"):
        make_document(
            hierarchy=[
                HierarchyNode(
                    id="h_1",
                    kind=HierarchyKind.ARTICLE,
                    label="Điều 1",
                    source_block_ids=["b_missing"],
                )
            ]
        )

    with pytest.raises(ValidationError, match="unknown page"):
        make_document(
            tables=[
                CanonicalTable(
                    id="t_9_0000", page_number=9, block_id="b_1_0000", n_rows=0, n_cols=0
                )
            ]
        )


def test_table_shape_must_match_its_cells() -> None:
    with pytest.raises(ValidationError, match="declares 3 rows"):
        CanonicalTable(id="t", page_number=1, block_id="b", n_rows=3, n_cols=1, cells=[["a"]])
    with pytest.raises(ValidationError, match="row 0 has 1 cells"):
        CanonicalTable(id="t", page_number=1, block_id="b", n_rows=1, n_cols=2, cells=[["a"]])


def test_extracted_field_defaults_to_unreviewed_and_allows_null_values() -> None:
    field = ExtractedField(
        id="field_deadline_1",
        name="deadline",
        extractor=Extractor(name="test", version="1.0"),
    )
    assert field.review_status is ReviewStatus.UNREVIEWED
    assert field.raw_value is None
    assert field.normalized_value is None
    assert field.confidence is None


def test_extra_keys_are_forbidden_so_schema_drift_is_caught() -> None:
    with pytest.raises(ValidationError):
        make_document(unexpected_key="boom")


# ----------------------------------------------------------------- normalization


def test_unicode_normalization_preserves_vietnamese_diacritics() -> None:
    decomposed = unicodedata.normalize("NFD", "Ủy ban nhân dân xã Mai Giang")
    normalized = normalize_text(decomposed)

    assert normalized == "Ủy ban nhân dân xã Mai Giang"
    assert unicodedata.normalize("NFC", normalized) == normalized
    assert "ủ" in normalized.lower()


def test_whitespace_is_tidied_without_losing_content() -> None:
    assert normalize_text("  Số:  1234/UBND-VP  ") == "Số: 1234/UBND-VP"
    assert normalize_text("a\r\nb\n\n\n\nc") == "a\nb\n\nc"


def test_block_ids_are_deterministic_for_one_provider_result() -> None:
    result = make_provider_result(
        [
            make_page(
                [
                    make_block("p-0", "một", bbox=[10, 10, 100, 20], order_hint=0),
                    make_block("p-1", "hai", bbox=[10, 40, 100, 50], order_hint=1),
                ]
            )
        ]
    )

    first = normalize_provider_result(result)
    second = normalize_provider_result(result)

    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert [block.id for block in first.iter_blocks()] == ["b_1_0000", "b_1_0001"]


def test_normalization_does_not_mutate_the_provider_result() -> None:
    result = make_provider_result([make_page([make_block("p-0", "  xin  chào  ")])])
    before = result.model_dump(mode="json")

    normalize_provider_result(result)

    assert result.model_dump(mode="json") == before


def test_reading_order_prefers_provider_hints_then_geometry() -> None:
    hinted = make_provider_result(
        [
            make_page(
                [
                    make_block("p-0", "second", bbox=[10, 10, 50, 20], order_hint=1),
                    make_block("p-1", "first", bbox=[10, 40, 50, 50], order_hint=0),
                ]
            )
        ]
    )
    document = normalize_provider_result(hinted)
    assert [block.text for block in document.iter_blocks()] == ["first", "second"]
    assert document.metadata["reading_order_strategy"] == {1: "provider_order_hint"}

    geometric = make_provider_result(
        [
            make_page(
                [
                    make_block("p-0", "lower", bbox=[10, 400, 50, 420]),
                    make_block("p-1", "upper", bbox=[10, 100, 50, 120]),
                ]
            )
        ]
    )
    document = normalize_provider_result(geometric)
    assert [block.text for block in document.iter_blocks()] == ["upper", "lower"]
    assert document.metadata["reading_order_strategy"] == {1: "geometry_top_left"}


def test_provider_sequence_is_kept_when_nothing_else_is_available() -> None:
    result = make_provider_result([make_page([make_block("p-0", "a"), make_block("p-1", "b")])])
    document = normalize_provider_result(result)

    assert [block.text for block in document.iter_blocks()] == ["a", "b"]
    assert document.metadata["reading_order_strategy"] == {1: "provider_sequence"}


def test_unknown_provider_types_become_unknown_not_a_plausible_guess() -> None:
    result = make_provider_result(
        [make_page([make_block("p-0", "x", provider_type="mystery_block")])]
    )
    block = normalize_provider_result(result).iter_blocks()[0]

    assert block.type is BlockType.UNKNOWN
    assert block.attributes["provider_type"] == "mystery_block"


def test_margin_classification_is_labelled_as_normalizer_inference() -> None:
    result = make_provider_result(
        [
            make_page(
                [
                    make_block("p-0", "running header", bbox=[72, 20, 300, 40]),
                    make_block("p-1", "body", bbox=[72, 300, 500, 320]),
                    make_block("p-2", "Trang 1/2", bbox=[72, 800, 200, 820]),
                ]
            )
        ]
    )
    blocks = normalize_provider_result(result).iter_blocks()

    assert [block.type for block in blocks] == [
        BlockType.HEADER,
        BlockType.PARAGRAPH,
        BlockType.FOOTER,
    ]
    assert blocks[0].attributes["classified_by"] == "normalizer_geometry"
    assert "classified_by" not in blocks[1].attributes


def test_missing_information_stays_none_rather_than_being_invented() -> None:
    result = make_provider_result([make_page([make_block("p-0", "x")])])
    document = normalize_provider_result(result)
    block = document.iter_blocks()[0]

    assert block.bbox is None
    assert block.confidence is None
    assert block.parent_id is None
    assert document.quality_report.text_quality_score is None
    assert document.quality_report.structure_quality_score is None
    assert document.extracted_fields == []


def test_real_parse_produces_unique_reading_order_and_page_provenance() -> None:
    adapter = build_adapter("pymupdf")
    result = adapter.parse(
        ParseRequest(
            document_id="cong_van_born_digital",
            pdf_path=FIXTURES / "cong_van_born_digital.pdf",
        )
    )
    document = normalize_provider_result(result)

    assert len(document.pages) == 2
    for page in document.pages:
        orders = [block.reading_order for block in page.blocks]
        assert orders == sorted(orders)
        assert len(orders) == len(set(orders))
        assert all(block.provenance.page_number == page.page_number for block in page.blocks)

    text = "\n".join(document.text_by_page().values())
    assert "Ủy ban nhân dân" in text or "ỦY BAN NHÂN DÂN" in text
    assert unicodedata.normalize("NFC", text) == text
