"""Router unit tests.

The router is measured on both the label it produces and the diagnostic signals that
justify it, so a wrong label can be explained rather than merely observed
(`docs/03_DOCUMENT_PIPELINE.md` section 10).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from bench_support import FIXTURES
from mamagift_docpipe import ParserError, Route, inspect_pdf
from mamagift_docpipe.router import PageClass, _suspicious_char_ratio

pytestmark = pytest.mark.unit


def route_of(name: str) -> tuple[Route, list[PageClass]]:
    report = inspect_pdf(FIXTURES / f"{name}.pdf", name)
    return report.route, [page.classification for page in report.pages]


def test_good_text_layer_routes_to_born_digital() -> None:
    report = inspect_pdf(FIXTURES / "cong_van_born_digital.pdf")

    assert report.route is Route.BORN_DIGITAL
    assert report.page_count == 2
    assert all(page.classification is PageClass.TEXT for page in report.pages)
    assert report.signals["text_page_ratio"] == 1.0
    assert report.signals["image_page_ratio"] == 0.0
    assert report.signals["pages_with_diacritics"] == 2
    assert report.recommended_parser_capability() == "born_digital_text"


def test_scanned_pdf_routes_to_scanned_with_image_signals() -> None:
    report = inspect_pdf(FIXTURES / "scan_khong_co_text.pdf")

    assert report.route is Route.SCANNED
    assert all(page.classification is PageClass.IMAGE_ONLY for page in report.pages)
    assert report.signals["image_page_ratio"] == 1.0
    assert report.signals["mean_chars_per_page"] == 0
    assert all(page.image_area_ratio >= 0.45 for page in report.pages)
    assert report.recommended_parser_capability() == "ocr"


def test_garbled_text_layer_is_detected_and_sent_to_ocr() -> None:
    report = inspect_pdf(FIXTURES / "text_layer_hong.pdf")

    assert report.route is Route.GARBLED_TEXT_LAYER
    assert report.pages[0].classification is PageClass.GARBLED
    assert report.pages[0].garbled_char_ratio > 0.2
    assert report.pages[0].char_count > 0, "the page does have a text layer; it is just wrong"
    assert report.recommended_parser_capability() == "ocr"
    assert any("suspicious text layer" in warning for warning in report.warnings)


def test_mixed_pdf_reports_both_page_classes() -> None:
    report = inspect_pdf(FIXTURES / "ho_so_hon_hop.pdf")

    assert report.route is Route.MIXED
    assert report.pages[0].classification is PageClass.TEXT
    assert report.pages[1].classification is PageClass.IMAGE_ONLY
    assert report.signals["text_page_ratio"] == 0.5
    assert report.signals["image_page_ratio"] == 0.5
    assert report.recommended_parser_capability() == "ocr_and_text"


def test_rotated_page_is_reported_without_changing_the_route() -> None:
    report = inspect_pdf(FIXTURES / "trang_xoay.pdf")

    assert report.route is Route.BORN_DIGITAL
    assert report.pages[0].rotation == 90
    assert report.signals["rotated_page_numbers"] == [1]
    assert report.signals["rotated_page_count"] == 1
    assert any("rotated pages detected" in warning for warning in report.warnings)


def test_encrypted_pdf_is_reported_not_raised() -> None:
    report = inspect_pdf(FIXTURES / "tai_lieu_ma_hoa.pdf")

    assert report.route is Route.ENCRYPTED
    assert report.encrypted is True
    assert report.needs_password is True
    assert report.pages == []
    assert report.recommended_parser_capability() == "none"


def test_malformed_pdf_is_reported_as_unsupported() -> None:
    report = inspect_pdf(FIXTURES / "tep_khong_hop_le.pdf")

    assert report.route is Route.UNSUPPORTED
    assert report.page_count == 0
    assert report.signals["open_error"]
    assert any("could not open document" in warning for warning in report.warnings)


def test_missing_file_raises_a_structured_error() -> None:
    with pytest.raises(ParserError) as excinfo:
        inspect_pdf(Path("benchmarks/parser/fixtures/khong-ton-tai.pdf"))

    assert excinfo.value.code.value == "unsupported_input"
    assert excinfo.value.retryable is False


def test_every_fixture_route_matches_its_manifest_label() -> None:
    expected = {
        "cong_van_born_digital": Route.BORN_DIGITAL,
        "quyet_dinh_dieu_khoan": Route.BORN_DIGITAL,
        "trang_xoay": Route.BORN_DIGITAL,
        "text_layer_hong": Route.GARBLED_TEXT_LAYER,
        "scan_khong_co_text": Route.SCANNED,
        "ho_so_hon_hop": Route.MIXED,
        "tai_lieu_ma_hoa": Route.ENCRYPTED,
        "tep_khong_hop_le": Route.UNSUPPORTED,
    }
    actual = {name: inspect_pdf(FIXTURES / f"{name}.pdf").route for name in expected}
    assert actual == expected


def test_real_vietnamese_text_is_never_suspicious() -> None:
    text = "Ủy ban nhân dân xã Mai Giang — Số: 1234/UBND-VP, ngày 14 tháng 8 năm 2026."
    assert _suspicious_char_ratio(text) == 0.0


def test_wrong_but_real_latin_letters_are_suspicious() -> None:
    """A broken CID map yields plausible letters, not replacement characters."""
    assert _suspicious_char_ratio("ȼȼȼȼ ban ȼȼȼȼ dan") > 0.2
    assert _suspicious_char_ratio("\ufffd\ufffd\ufffd") == 1.0
