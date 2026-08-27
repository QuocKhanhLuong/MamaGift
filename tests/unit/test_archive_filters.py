"""Unit tests for ArchiveFilter and Vietnamese document-number normalisation."""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from mamagift_retrieval.archive.filters import ArchiveFilter, normalize_identifier

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("19/2026/TT-BGDĐT", "19/2026/TT-BGDĐT"),
        (" 19 / 2026 / TT-BGDĐT ", "19/2026/TT-BGDĐT"),
        ("19/2026/tt-bgdđt", "19/2026/TT-BGDĐT"),
        ("57/QĐ-UBND", "57/QĐ-UBND"),
        ("57 / qđ - ubnd", "57/QĐ-UBND"),
        ("12/KH-UBND", "12/KH-UBND"),
        ("45/2026/NĐ-CP", "45/2026/NĐ-CP"),
        ("Thông tư 19 / 2026", "THÔNG TƯ 19/2026"),
        ("   ", ""),
    ],
)
def test_normalize_identifier(raw: str, expected: str) -> None:
    assert normalize_identifier(raw) == expected


def test_normalize_identifier_is_idempotent() -> None:
    once = normalize_identifier(" 19 / 2026 / tt-bgdđt ")
    assert normalize_identifier(once) == once


def test_normalize_identifier_keeps_distinct_numbers_distinct() -> None:
    """A normaliser that collapsed the year would make two real documents indistinguishable."""
    assert normalize_identifier("19/2025/TT-BGDĐT") != normalize_identifier("19/2026/TT-BGDĐT")
    assert normalize_identifier("19/2026/TT-BGDĐT") != normalize_identifier("20/2026/TT-BGDĐT")


def test_normalize_identifier_rejects_non_strings() -> None:
    with pytest.raises(TypeError):
        normalize_identifier(19)  # type: ignore[arg-type]


def test_empty_list_means_match_nothing_not_match_everything() -> None:
    """The single most dangerous default in a filter API.

    A caller that computed an empty candidate set must get nothing back, never the archive.
    """
    for field in ("document_ids", "document_types", "document_numbers", "issuers"):
        assert ArchiveFilter(**{field: []}).matches_nothing() is True
        assert ArchiveFilter(**{field: ["x"]}).matches_nothing() is False


def test_no_filter_matches_everything() -> None:
    assert ArchiveFilter().matches_nothing() is False
    assert ArchiveFilter(include_requires_review=False).matches_nothing() is False


def test_reversed_date_range_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ArchiveFilter(issued_date_from=date(2026, 5, 1), issued_date_to=date(2026, 1, 1))


def test_equal_dates_are_a_valid_single_day_range() -> None:
    day = date(2026, 3, 31)
    filters = ArchiveFilter(issued_date_from=day, issued_date_to=day)
    assert filters.issued_date_from == filters.issued_date_to == day


def test_open_ended_ranges_are_allowed() -> None:
    assert ArchiveFilter(issued_date_from=date(2026, 1, 1)).issued_date_to is None
    assert ArchiveFilter(issued_date_to=date(2026, 1, 1)).issued_date_from is None


def test_normalized_document_numbers() -> None:
    assert ArchiveFilter().normalized_document_numbers() is None
    assert ArchiveFilter(document_numbers=[]).normalized_document_numbers() == []
    assert ArchiveFilter(
        document_numbers=[" 57 / qđ-ubnd ", "19/2026/TT-BGDĐT"]
    ).normalized_document_numbers() == ["57/QĐ-UBND", "19/2026/TT-BGDĐT"]


def test_unknown_field_is_rejected() -> None:
    """extra='forbid' is what stops a typo silently disabling a filter."""
    with pytest.raises(ValidationError):
        ArchiveFilter(document_type="Thông tư")  # type: ignore[call-arg]


def test_there_is_no_field_that_relaxes_current_version_isolation() -> None:
    """Current-version isolation is an invariant, not a filter.

    If someone later adds a switch for it, this test must be the thing that objects.
    """
    forbidden = {
        "include_stale_versions",
        "include_all_versions",
        "parse_run_id",
        "document_version",
        "is_current",
        "archive_scope",
    }
    assert forbidden.isdisjoint(ArchiveFilter.model_fields)
