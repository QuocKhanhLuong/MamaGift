"""Unit tests for archive query identifier extraction and match scoring."""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from mamagift_retrieval.archive.identifiers import (
    LegalMarker,
    QueryIdentifiers,
    extract_query_identifiers,
    identifier_match_score,
)
from mamagift_retrieval.search.vi_tokenize import tokenize_vi

# ============================================================================
# 1. Pydantic Model Invariants & Constraints
# ============================================================================


def test_legal_marker_forbids_extra_fields() -> None:
    marker = LegalMarker(marker="điều", value="7", token="điều_7")
    assert marker.marker == "điều"
    assert marker.value == "7"
    assert marker.token == "điều_7"

    with pytest.raises(ValidationError):
        LegalMarker(marker="điều", value="7", token="điều_7", extra_field="forbidden")  # type: ignore[call-arg]


def test_query_identifiers_forbids_extra_fields() -> None:
    identifiers = QueryIdentifiers()
    assert identifiers.is_empty() is True

    with pytest.raises(ValidationError):
        QueryIdentifiers(extra_field="forbidden")  # type: ignore[call-arg]


def test_query_identifiers_is_empty() -> None:
    assert QueryIdentifiers().is_empty() is True
    assert (
        QueryIdentifiers(
            document_numbers=[], legal_markers=[], dates=[], raw_date_tokens=[]
        ).is_empty()
        is True
    )
    assert QueryIdentifiers(document_numbers=["19/2026/TT-BGDĐT"]).is_empty() is False
    assert (
        QueryIdentifiers(
            legal_markers=[LegalMarker(marker="điều", value="7", token="điều_7")]
        ).is_empty()
        is False
    )
    assert QueryIdentifiers(dates=[date(2026, 3, 31)]).is_empty() is False
    assert QueryIdentifiers(raw_date_tokens=["31/03/2026"]).is_empty() is False


# ============================================================================
# 2. Document Number Extraction & Normalisation
# ============================================================================


def test_document_number_survives_intact() -> None:
    query = "Thông tư 19/2026/TT-BGDĐT quy định gì?"
    result = extract_query_identifiers(query)
    assert result.document_numbers == ["19/2026/TT-BGDĐT"]


def test_document_number_spacing_variants() -> None:
    queries = [
        "19 / 2026 / TT-BGDĐT",
        " 19 / 2026 / TT - BGDĐT ",
        "19/2026/TT-BGDĐT",
        "Thông tư 19 / 2026 / TT - BGDĐT quy định về chuẩn cơ sở giáo dục",
    ]
    for q in queries:
        result = extract_query_identifiers(q)
        assert result.document_numbers == ["19/2026/TT-BGDĐT"], f"Failed on query: {q}"


def test_distinct_years_are_different_identifiers() -> None:
    """19/2025/TT-BGDĐT and 19/2026/TT-BGDĐT must be separate, different identifiers."""
    res1 = extract_query_identifiers("19/2025/TT-BGDĐT")
    res2 = extract_query_identifiers("19/2026/TT-BGDĐT")
    assert res1.document_numbers == ["19/2025/TT-BGDĐT"]
    assert res2.document_numbers == ["19/2026/TT-BGDĐT"]
    assert res1.document_numbers != res2.document_numbers

    combined = extract_query_identifiers("So sánh 19/2025/TT-BGDĐT và 19/2026/TT-BGDĐT")
    assert combined.document_numbers == ["19/2025/TT-BGDĐT", "19/2026/TT-BGDĐT"]


def test_canonical_vietnamese_document_number_formats_roundtrip() -> None:
    formats = [
        ("57/QĐ-UBND", "57/QĐ-UBND"),
        (" 57 / QĐ - UBND ", "57/QĐ-UBND"),
        ("12/KH-UBND", "12/KH-UBND"),
        (" 12 / KH - UBND ", "12/KH-UBND"),
        ("45/2026/NĐ-CP", "45/2026/NĐ-CP"),
        (" 45 / 2026 / NĐ - CP ", "45/2026/NĐ-CP"),
        ("01/TB-VP", "01/TB-VP"),
        ("15/BC-BGDĐT", "15/BC-BGDĐT"),
        ("123/QĐ-UBND", "123/QĐ-UBND"),
    ]
    for raw_input, expected_normalized in formats:
        result = extract_query_identifiers(raw_input)
        assert result.document_numbers == [expected_normalized], f"Failed for {raw_input}"


def test_deduplication_preserves_first_appearance_order() -> None:
    query = "19/2026/TT-BGDĐT và 12/KH-UBND và 19 / 2026 / TT - BGDĐT và 57/QĐ-UBND"
    result = extract_query_identifiers(query)
    assert result.document_numbers == ["19/2026/TT-BGDĐT", "12/KH-UBND", "57/QĐ-UBND"]


# ============================================================================
# 3. Legal Hierarchy Markers Extraction
# ============================================================================


def test_legal_markers_extraction_and_token_equality() -> None:
    query = "Điều 7 Khoản 2 Điểm a"
    result = extract_query_identifiers(query)

    assert len(result.legal_markers) == 3
    assert result.legal_markers[0] == LegalMarker(marker="điều", value="7", token="điều_7")
    assert result.legal_markers[1] == LegalMarker(marker="khoản", value="2", token="khoản_2")
    assert result.legal_markers[2] == LegalMarker(marker="điểm", value="a", token="điểm_a")

    # Tokens must match EXACTLY what tokenize_vi produces for the same text
    tokenize_tokens = tokenize_vi(query)
    for lm in result.legal_markers:
        assert lm.token in tokenize_tokens, (
            f"Marker token {lm.token} not found in tokenize_vi output {tokenize_tokens}"
        )


def test_legal_markers_roman_and_alphanumeric_values() -> None:
    query = "Chương I Mục 1 Điều 12a Phụ lục I"
    result = extract_query_identifiers(query)

    expected = [
        LegalMarker(marker="chương", value="i", token="chương_i"),
        LegalMarker(marker="mục", value="1", token="mục_1"),
        LegalMarker(marker="điều", value="12a", token="điều_12a"),
        LegalMarker(marker="phụ lục", value="i", token="phụ_lục_i"),
    ]
    assert result.legal_markers == expected

    tokens = tokenize_vi(query)
    for lm in result.legal_markers:
        assert lm.token in tokens


def test_standalone_phu_luc_without_number() -> None:
    query = "Xem phụ lục đính kèm"
    result = extract_query_identifiers(query)
    assert result.legal_markers == [LegalMarker(marker="phụ lục", value="", token="phụ_lục")]
    assert "phụ_lục" in tokenize_vi(query)


def test_phu_luc_with_number_does_not_duplicate_standalone() -> None:
    query = "Xem Phụ lục 2 đính kèm"
    result = extract_query_identifiers(query)
    assert result.legal_markers == [LegalMarker(marker="phụ lục", value="2", token="phụ_lục_2")]


def test_legal_markers_deduplication_preserving_order() -> None:
    query = "Điều 1 Khoản 2 Điều 1 Khoản 3"
    result = extract_query_identifiers(query)
    assert result.legal_markers == [
        LegalMarker(marker="điều", value="1", token="điều_1"),
        LegalMarker(marker="khoản", value="2", token="khoản_2"),
        LegalMarker(marker="khoản", value="3", token="khoản_3"),
    ]


# ============================================================================
# 4. Date Extraction & Validation
# ============================================================================


def test_date_extraction_both_formats() -> None:
    query1 = "Quy định ngày 31/03/2026"
    result1 = extract_query_identifiers(query1)
    assert result1.dates == [date(2026, 3, 31)]
    assert result1.raw_date_tokens == ["31/03/2026"]

    query2 = "Ban hành ngày 31 tháng 03 năm 2026"
    result2 = extract_query_identifiers(query2)
    assert result2.dates == [date(2026, 3, 31)]
    assert result2.raw_date_tokens == ["31/03/2026"]

    query3 = "Ban hành ngày 31 tháng 3 năm 2026"
    result3 = extract_query_identifiers(query3)
    assert result3.dates == [date(2026, 3, 31)]
    assert result3.raw_date_tokens == ["31/03/2026"]


def test_date_extraction_does_not_pollute_document_numbers() -> None:
    query = "Văn bản ban hành ngày 31/03/2026"
    result = extract_query_identifiers(query)
    assert result.document_numbers == []
    assert result.dates == [date(2026, 3, 31)]
    assert result.raw_date_tokens == ["31/03/2026"]


def test_impossible_date_is_skipped_in_dates_but_preserved_in_raw_tokens() -> None:
    query = "Ngày 32/13/2026 hoặc ngày 32 tháng 13 năm 2026"
    result = extract_query_identifiers(query)
    # Must NOT raise, and dates must be empty
    assert result.dates == []
    assert result.raw_date_tokens == ["32/13/2026"]


def test_leap_year_date_validation() -> None:
    # 2024 is a leap year (29 Feb valid)
    res_valid = extract_query_identifiers("29/02/2024")
    assert res_valid.dates == [date(2024, 2, 29)]

    # 2023 is not a leap year (29 Feb invalid)
    res_invalid = extract_query_identifiers("29/02/2023")
    assert res_invalid.dates == []
    assert res_invalid.raw_date_tokens == ["29/02/2023"]


def test_multiple_dates_order_and_deduplication() -> None:
    query = "Từ ngày 15/04/2025 đến ngày 31/03/2026 và ngày 15 tháng 04 năm 2025"
    result = extract_query_identifiers(query)
    assert result.dates == [date(2025, 4, 15), date(2026, 3, 31)]
    assert result.raw_date_tokens == ["15/04/2025", "31/03/2026"]


# ============================================================================
# 5. Empty and Whitespace Queries
# ============================================================================


def test_empty_and_whitespace_queries() -> None:
    for empty_input in ["", "   ", "\t\n\r", "   \n  \t  "]:
        result = extract_query_identifiers(empty_input)
        assert result.is_empty() is True
        assert result.document_numbers == []
        assert result.legal_markers == []
        assert result.dates == []
        assert result.raw_date_tokens == []


def test_determinism_extract_query_identifiers() -> None:
    query = "Thông tư 19/2026/TT-BGDĐT ban hành ngày 31/03/2026 Điều 7 Khoản 2 Điểm a"
    res1 = extract_query_identifiers(query)
    res2 = extract_query_identifiers(query)
    assert res1 == res2
    assert res1.model_dump() == res2.model_dump()


# ============================================================================
# 6. Identifier Match Score
# ============================================================================


def test_identifier_match_score_empty_identifiers() -> None:
    empty = QueryIdentifiers()
    assert identifier_match_score(empty, "Some chunk text", "19/2026/TT-BGDĐT") == 0.0
    assert identifier_match_score(empty, "", None) == 0.0


def test_identifier_match_score_exact_doc_number_hit() -> None:
    ids = extract_query_identifiers("Thông tư 19/2026/TT-BGDĐT Điều 7")
    score_exact = identifier_match_score(
        ids,
        chunk_text="Điều 7. Quy định chung",
        document_number="19/2026/TT-BGDĐT",
    )
    assert score_exact == 1.0

    # Spaced document_number variant on chunk also achieves exact hit 1.0
    score_spaced = identifier_match_score(
        ids,
        chunk_text="Điều 7. Quy định chung",
        document_number=" 19 / 2026 / TT - BGDĐT ",
    )
    assert score_spaced == 1.0


def test_identifier_match_score_different_doc_number_strictly_less() -> None:
    ids = extract_query_identifiers("Thông tư 19/2026/TT-BGDĐT Điều 7")

    # Exact doc number hit
    score_hit = identifier_match_score(
        ids,
        chunk_text="Thông tư quy định tại Điều 7",
        document_number="19/2026/TT-BGDĐT",
    )
    assert score_hit == 1.0

    # Different doc number with overlapping text/markers
    score_diff_doc = identifier_match_score(
        ids,
        chunk_text="Thông tư quy định tại Điều 7",
        document_number="19/2025/TT-BGDĐT",
    )
    assert score_diff_doc < 1.0
    assert score_diff_doc > 0.0

    # Another doc with no matching markers or doc numbers
    score_unrelated = identifier_match_score(
        ids,
        chunk_text="Kế hoạch thực hiện nhiệm vụ",
        document_number="12/KH-UBND",
    )
    assert score_unrelated == 0.0
    assert score_unrelated < score_diff_doc < score_hit


def test_identifier_match_score_legal_markers_partial_credit() -> None:
    ids = extract_query_identifiers("Điều 7 Khoản 2 Điểm a")
    assert ids.document_numbers == []

    # Chunk with all three markers
    chunk_all = "Theo quy định tại Điều 7 Khoản 2 Điểm a về tiêu chuẩn cơ sở vật chất"
    score_all = identifier_match_score(ids, chunk_all, document_number="57/QĐ-UBND")

    # Chunk with one marker
    chunk_partial = "Theo quy định tại Điều 7 về tiêu chuẩn cơ sở vật chất"
    score_partial = identifier_match_score(ids, chunk_partial, document_number="57/QĐ-UBND")

    # Chunk with no matching markers
    chunk_none = "Quy định tại Điều 8 Khoản 1 về đối tượng áp dụng"
    score_none = identifier_match_score(ids, chunk_none, document_number="57/QĐ-UBND")

    assert 0.0 < score_partial < score_all <= 1.0
    assert score_none == 0.0


def test_identifier_match_score_dates_partial_credit() -> None:
    ids = extract_query_identifiers("Văn bản ngày 31/03/2026")
    assert ids.document_numbers == []
    assert ids.raw_date_tokens == ["31/03/2026"]

    chunk_with_date = "Kế hoạch ban hành ngày 31/03/2026 của UBND thành phố"
    score_date = identifier_match_score(ids, chunk_with_date, document_number="12/KH-UBND")

    chunk_without_date = "Kế hoạch ban hành ngày 15/04/2025 của UBND thành phố"
    score_no_date = identifier_match_score(ids, chunk_without_date, document_number="12/KH-UBND")

    assert score_date > 0.0
    assert score_no_date == 0.0


def test_identifier_match_score_bounded_zero_one() -> None:
    queries = [
        "19/2026/TT-BGDĐT Điều 7 Khoản 2 Điểm a ngày 31/03/2026",
        "Điều 7 Khoản 2",
        "ngày 31/03/2026",
        "phụ lục",
        "",
        "không có định danh",
    ]
    chunks = [
        "Thông tư 19/2026/TT-BGDĐT Điều 7 Khoản 2 Điểm a ngày 31/03/2026",
        "Điều 7 Khoản 2",
        "Phụ lục đính kèm ngày 31/03/2026",
        "Nội dung không liên quan",
        "",
    ]
    doc_nums = ["19/2026/TT-BGDĐT", "19/2025/TT-BGDĐT", "57/QĐ-UBND", None, ""]

    for q in queries:
        ids = extract_query_identifiers(q)
        for c in chunks:
            for d in doc_nums:
                s = identifier_match_score(ids, c, d)
                assert 0.0 <= s <= 1.0, f"Score {s} out of bounds for q={q}, c={c}, d={d}"


def test_determinism_identifier_match_score() -> None:
    ids = extract_query_identifiers("Thông tư 19/2026/TT-BGDĐT Điều 7 ngày 31/03/2026")
    chunk = "Căn cứ Thông tư 19/2026/TT-BGDĐT Điều 7 ngày 31/03/2026"
    s1 = identifier_match_score(ids, chunk, "57/QĐ-UBND")
    s2 = identifier_match_score(ids, chunk, "57/QĐ-UBND")
    assert s1 == s2
