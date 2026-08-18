"""Benchmark metric tests on known toy cases.

Each metric is checked against an input whose correct score can be worked out by hand,
including the "no ground truth" case, which must report unavailable rather than zero.
"""

from __future__ import annotations

import pytest
from tools.parser_bench.critical_fields import extract_critical_fields, severity_3_failures
from tools.parser_bench.manifest import GroundTruth, Heading, TableTruth
from tools.parser_bench.metrics import (
    character_accuracy,
    compare_key,
    critical_field_accuracy,
    diacritic_preservation,
    header_footer_leakage,
    heading_hierarchy_f1,
    levenshtein,
    list_preservation,
    page_attribution_accuracy,
    provenance_completeness,
    reading_order_accuracy,
    route_accuracy,
    table_structure_score,
)

from bench_support import make_block, make_page, make_provider_result
from mamagift_docpipe import normalize_provider_result
from mamagift_docpipe.canonical import CanonicalDocument

pytestmark = pytest.mark.unit


def document_from(blocks: list[tuple[str, str]], page_height: float = 842.0) -> CanonicalDocument:
    """Build a canonical document from (provider_type, text) pairs, top to bottom."""
    provider_blocks = [
        make_block(
            f"p-{index}",
            text,
            provider_type=provider_type,
            bbox=[72.0, 100.0 + index * 30.0, 500.0, 120.0 + index * 30.0],
            order_hint=index,
        )
        for index, (provider_type, text) in enumerate(blocks)
    ]
    return normalize_provider_result(
        make_provider_result([make_page(provider_blocks, height=page_height)])
    )


# ------------------------------------------------------------------- primitives


@pytest.mark.parametrize(
    ("reference", "hypothesis", "distance"),
    [
        ("", "", 0),
        ("abc", "abc", 0),
        ("abc", "abd", 1),
        ("abc", "ab", 1),
        ("abc", "", 3),
        ("ngày", "ngay", 1),
    ],
)
def test_levenshtein_known_distances(reference: str, hypothesis: str, distance: int) -> None:
    assert levenshtein(reference, hypothesis) == distance


def test_compare_key_folds_case_and_whitespace_but_keeps_diacritics() -> None:
    assert compare_key("  Số:   1234  ") == "số: 1234"
    assert compare_key("NGÀY") == compare_key("ngày")
    assert compare_key("ngày") != compare_key("ngay")


# ------------------------------------------------------------------------- text


def test_character_accuracy_on_a_hand_computable_case() -> None:
    document = document_from([("text", "ngay")])
    truth = GroundTruth(document_id="d", transcript={"1": "ngày"})

    result = character_accuracy(document, truth)

    # One substitution over a four-character reference: CER = 0.25.
    assert result.available
    assert result.detail["cer"] == pytest.approx(0.25)
    assert result.value == pytest.approx(0.75)


def test_perfect_transcription_scores_one() -> None:
    document = document_from([("text", "Số: 1234/UBND-VP")])
    truth = GroundTruth(document_id="d", transcript={"1": "Số: 1234/UBND-VP"})

    assert character_accuracy(document, truth).value == pytest.approx(1.0)


def test_dropped_diacritics_are_caught_even_when_cer_looks_acceptable() -> None:
    document = document_from([("text", "Uy ban nhan dan xa Mai Giang")])
    truth = GroundTruth(document_id="d", transcript={"1": "Ủy ban nhân dân xã Mai Giang"})

    result = diacritic_preservation(document, truth)

    assert result.available
    assert result.value == pytest.approx(0.0)
    assert result.detail["produced_marks"] == 0


def test_diacritic_metric_is_unavailable_when_the_reference_has_none() -> None:
    document = document_from([("text", "abc")])
    truth = GroundTruth(document_id="d", transcript={"1": "abc"})

    assert diacritic_preservation(document, truth).available is False


# -------------------------------------------------------------------- structure


def test_reading_order_rewards_correct_sequence() -> None:
    document = document_from([("text", "một"), ("text", "hai"), ("text", "ba")])
    truth = GroundTruth(document_id="d", reading_order=["một", "hai", "ba"])

    result = reading_order_accuracy(document, truth)

    assert result.value == pytest.approx(1.0)
    assert result.detail["block_recall"] == pytest.approx(1.0)


def test_reversed_reading_order_scores_zero() -> None:
    document = document_from([("text", "ba"), ("text", "hai"), ("text", "một")])
    truth = GroundTruth(document_id="d", reading_order=["một", "hai", "ba"])

    result = reading_order_accuracy(document, truth)

    assert result.value == pytest.approx(0.0)
    assert result.detail["pairwise_order_score"] == pytest.approx(0.0)


def test_missing_blocks_lower_reading_order_through_recall() -> None:
    document = document_from([("text", "một"), ("text", "ba")])
    truth = GroundTruth(document_id="d", reading_order=["một", "hai", "ba"])

    result = reading_order_accuracy(document, truth)

    # Order of what was found is perfect, but only 2 of 3 blocks survived.
    assert result.value == pytest.approx(2 / 3)


def test_heading_f1_penalizes_both_misses_and_false_positives() -> None:
    document = document_from(
        [("section_header", "Điều 1"), ("section_header", "Không phải tiêu đề")]
    )
    truth = GroundTruth(
        document_id="d",
        headings=[Heading(level=2, text="Điều 1"), Heading(level=2, text="Điều 2")],
    )

    result = heading_hierarchy_f1(document, truth)

    assert result.detail["precision"] == pytest.approx(0.5)
    assert result.detail["recall"] == pytest.approx(0.5)
    assert result.value == pytest.approx(0.5)


def test_parser_that_emits_no_headings_scores_zero_not_unavailable() -> None:
    document = document_from([("text", "Điều 1")])
    truth = GroundTruth(document_id="d", headings=[Heading(level=2, text="Điều 1")])

    result = heading_hierarchy_f1(document, truth)

    assert result.available is True
    assert result.value == pytest.approx(0.0)


def test_list_preservation_penalizes_reordering() -> None:
    ordered = document_from([("list_item", "1. một"), ("list_item", "2. hai")])
    shuffled = document_from([("list_item", "2. hai"), ("list_item", "1. một")])
    truth = GroundTruth(document_id="d", lists=[["1. một", "2. hai"]])

    assert list_preservation(ordered, truth).value == pytest.approx(1.0)
    assert list_preservation(shuffled, truth).value == pytest.approx(0.5)


def test_table_structure_scores_cells_and_shape() -> None:
    cells = [["STT", "Tên"], ["1", "Hồ sơ"]]
    provider_block = make_block(
        "p-0", "", provider_type="table", bbox=[72, 100, 500, 200], order_hint=0
    )
    provider_block.attributes["cells"] = cells
    document = normalize_provider_result(make_provider_result([make_page([provider_block])]))

    exact = GroundTruth(document_id="d", tables=[TableTruth(page_number=1, cells=cells)])
    assert table_structure_score(document, exact).value == pytest.approx(1.0)

    missing = GroundTruth(document_id="d", tables=[TableTruth(page_number=2, cells=cells)])
    assert table_structure_score(document, missing).value == pytest.approx(0.0)


def test_header_footer_leakage_detects_running_headers_in_body_text() -> None:
    leaking = document_from([("text", "Công văn số 1234/UBND-VP"), ("text", "Nội dung")], 842.0)
    truth = GroundTruth(document_id="d", header_footer_texts=["Công văn số 1234/UBND-VP"])

    result = header_footer_leakage(leaking, truth)

    assert result.value == pytest.approx(0.0)
    assert result.detail["leaked"] == 1


def test_header_footer_leakage_is_clean_when_margins_are_classified() -> None:
    provider_blocks = [
        make_block("p-0", "Công văn số 1234/UBND-VP", bbox=[72, 20, 300, 40], order_hint=0),
        make_block("p-1", "Nội dung", bbox=[72, 300, 500, 320], order_hint=1),
    ]
    document = normalize_provider_result(make_provider_result([make_page(provider_blocks)]))
    truth = GroundTruth(document_id="d", header_footer_texts=["Công văn số 1234/UBND-VP"])

    assert header_footer_leakage(document, truth).value == pytest.approx(1.0)


def test_provenance_is_complete_for_a_well_formed_document() -> None:
    document = document_from([("text", "a"), ("text", "b")])
    result = provenance_completeness(document, GroundTruth(document_id="d"))

    assert result.value == pytest.approx(1.0)
    assert result.detail["blocks"] == 2


def test_provenance_scores_zero_when_a_parser_produces_nothing() -> None:
    document = normalize_provider_result(make_provider_result([make_page([])]))
    result = provenance_completeness(document, GroundTruth(document_id="d"))

    assert result.value == pytest.approx(0.0)
    assert result.detail["reason"] == "parser produced no blocks"


def test_page_attribution_detects_text_landing_on_the_wrong_page() -> None:
    document = normalize_provider_result(
        make_provider_result(
            [
                make_page([make_block("p-0", "công văn tuyển sinh", order_hint=0)], page_number=1),
                make_page([make_block("p-1", "phụ lục biểu mẫu", order_hint=0)], page_number=2),
            ]
        )
    )
    correct = GroundTruth(
        document_id="d",
        transcript={"1": "công văn tuyển sinh", "2": "phụ lục biểu mẫu"},
    )
    swapped = GroundTruth(
        document_id="d",
        transcript={"1": "phụ lục biểu mẫu", "2": "công văn tuyển sinh"},
    )

    assert page_attribution_accuracy(document, correct).value == pytest.approx(1.0)
    assert page_attribution_accuracy(document, swapped).value == pytest.approx(0.0)


def test_route_accuracy_is_exact_match() -> None:
    assert route_accuracy("scanned", "scanned").value == 1.0
    assert route_accuracy("born_digital", "scanned").value == 0.0


# -------------------------------------------------------------- critical fields


def test_missing_ground_truth_layers_are_unavailable_never_zero() -> None:
    document = document_from([("text", "x")])
    empty = GroundTruth(document_id="d")

    for metric in (
        character_accuracy,
        diacritic_preservation,
        reading_order_accuracy,
        heading_hierarchy_f1,
        list_preservation,
        table_structure_score,
        header_footer_leakage,
        page_attribution_accuracy,
    ):
        result = metric(document, empty)
        assert result.available is False, metric.__name__
        assert result.value is None, metric.__name__


def test_critical_field_accuracy_reports_which_fields_were_wrong() -> None:
    truth = GroundTruth(
        document_id="d",
        critical_fields={"document_number": "1234/UBND-VP", "issue_date": "2026-08-14"},
    )
    extracted = {"document_number": "1234/UBND-VP", "issue_date": "2026-08-15"}

    metric, wrong = critical_field_accuracy(extracted, truth)

    assert metric.value == pytest.approx(0.5)
    assert wrong == ["issue_date"]
    assert severity_3_failures(truth.critical_fields, wrong) == ["issue_date"]


def test_a_field_the_extractor_could_not_find_counts_as_wrong_not_correct() -> None:
    truth = GroundTruth(document_id="d", critical_fields={"signer": "Trần Thị Bình"})
    metric, wrong = critical_field_accuracy({"signer": None}, truth)

    assert metric.value == pytest.approx(0.0)
    assert wrong == ["signer"]


def test_non_critical_field_errors_do_not_trip_the_severity_3_gate() -> None:
    truth = GroundTruth(document_id="d", critical_fields={"signer": "A", "issuer": "B"})
    assert severity_3_failures(truth.critical_fields, ["signer", "issuer"]) == []


def test_critical_field_extraction_on_an_authored_document() -> None:
    document = document_from(
        [
            ("text", "ỦY BAN NHÂN DÂN XÃ MAI GIANG"),
            ("text", "Số: 1234/UBND-VP"),
            ("text", "Mai Giang, ngày 14 tháng 8 năm 2026"),
            ("text", "V/v hướng dẫn nộp hồ sơ tuyển sinh"),
            ("text", "Báo cáo gửi về trước ngày 25 tháng 8 năm 2026."),
        ]
    )

    fields = extract_critical_fields(document)

    assert fields["document_number"] == "1234/UBND-VP"
    assert fields["issue_date"] == "2026-08-14"
    assert fields["deadline"] == "2026-08-25"
    assert fields["issuer"] == "ỦY BAN NHÂN DÂN XÃ MAI GIANG"
    assert fields["title"] == "hướng dẫn nộp hồ sơ tuyển sinh"
    assert fields["signer"] is None, "no signature block, so no signer may be invented"


def test_benchmark_deadline_before_issue_line_stays_distinct_from_issue_date() -> None:
    document = document_from(
        [
            ("text", "ỦY BAN NHÂN DÂN XÃ MAI GIANG"),
            ("text", "Số: 12/UBND-VP"),
            ("text", "Báo cáo kết quả chậm nhất là ngày 20 tháng 8 năm 2026."),
            ("text", "Mai Giang, ngày 14 tháng 8 năm 2026"),
            ("text", "V/v hướng dẫn nộp hồ sơ tuyển sinh"),
        ]
    )

    fields = extract_critical_fields(document)

    assert fields["deadline"] == "2026-08-20"
    assert fields["issue_date"] == "2026-08-14"


def test_benchmark_recognizes_abbreviated_number_label_and_rejects_invalid_date() -> None:
    document = document_from(
        [
            ("text", "ỦY BAN NHÂN DÂN XÃ MAI GIANG"),
            ("text", "SO: 45/QĐ-UBND"),
            ("text", "Mai Giang, ngày 31 tháng 4 năm 2026"),
            ("text", "V/v ban hành quy chế"),
        ]
    )

    fields = extract_critical_fields(document)

    assert fields["document_number"] == "45/QĐ-UBND"
    assert fields["issue_date"] is None, "31 April is not a valid calendar date"
