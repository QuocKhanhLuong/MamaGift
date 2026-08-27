"""Unit tests for archive freshness semantics (TASK C4).

Guards:
1. Intent detection accuracy for NEWEST, OLDEST, DATE_WINDOW, and NONE phrases.
2. Ambiguous query resolution (conflicting NEWEST + OLDEST markers return NONE).
3. Diacritic sensitivity (non-diacritic Vietnamese queries do NOT trigger freshness).
4. Chronological and reverse-chronological ordering with exact reversal.
5. Undated documents sort last in both directions and are never returned as newest.
6. Deterministic tie-breaking on document_id ascending.
7. Input immutability.
8. Caveat generation for 2+ documents under NEWEST and OLDEST intents; None otherwise.
9. Anti-hallucination gate: supersession_claim is strictly None for all inputs.
10. Sane boundary handling for single-document and empty inputs.
"""

from __future__ import annotations

from datetime import date

import pytest

from mamagift_retrieval.archive.freshness import (
    NEWEST_CAVEAT,
    OLDEST_CAVEAT,
    FreshnessAnswer,
    FreshnessIntent,
    detect_freshness_intent,
    order_by_freshness,
    resolve_freshness,
)
from mamagift_retrieval.archive.protocol import ArchiveDocumentRef


def _make_doc(
    document_id: str,
    issued_date: date | None = None,
    title: str | None = None,
    document_number: str | None = None,
    document_type: str | None = None,
    issuer: str | None = None,
    parse_run_id: str = "prun_freshness_test",
    document_version: int = 1,
    requires_user_review: bool = False,
) -> ArchiveDocumentRef:
    """Helper to construct an ArchiveDocumentRef for testing."""
    return ArchiveDocumentRef(
        document_id=document_id,
        parse_run_id=parse_run_id,
        document_version=document_version,
        document_type=document_type,
        document_number=document_number,
        title=title,
        issuer=issuer,
        issued_date=issued_date,
        requires_user_review=requires_user_review,
    )


# ---------------------------------------------------------------------------
# 1. Intent detection mapping
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("query", "expected_intent"),
    [
        # NEWEST signals
        ("mới nhất", FreshnessIntent.NEWEST),
        ("mới nhất là", FreshnessIntent.NEWEST),
        ("Văn bản mới nhất là văn bản nào?", FreshnessIntent.NEWEST),
        ("Cho tôi xem quyết định gần đây nhất của UBND", FreshnessIntent.NEWEST),
        ("gần nhất", FreshnessIntent.NEWEST),
        ("Kế hoạch mới ban hành về tuyển sinh", FreshnessIntent.NEWEST),
        ("Quy định cập nhật nhất năm 2026", FreshnessIntent.NEWEST),
        ("văn bản mới nhất liên quan tới tuyển sinh là văn bản nào?", FreshnessIntent.NEWEST),
        # OLDEST signals
        ("cũ nhất", FreshnessIntent.OLDEST),
        ("Văn bản cũ nhất trong kho là gì?", FreshnessIntent.OLDEST),
        ("sớm nhất", FreshnessIntent.OLDEST),
        ("đầu tiên", FreshnessIntent.OLDEST),
        ("Nghị định đầu tiên về tiền lương", FreshnessIntent.OLDEST),
        ("ban hành sớm nhất", FreshnessIntent.OLDEST),
        ("Văn bản ban hành sớm nhất về bảo hiểm", FreshnessIntent.OLDEST),
        # DATE_WINDOW signals
        ("tháng này", FreshnessIntent.DATE_WINDOW),
        ("Có văn bản nào trong tháng này không?", FreshnessIntent.DATE_WINDOW),
        ("Văn bản ban hành tháng trước", FreshnessIntent.DATE_WINDOW),
        ("Quyết định ban hành trong tuần này", FreshnessIntent.DATE_WINDOW),
        ("Kế hoạch triển khai tuần tới", FreshnessIntent.DATE_WINDOW),
        ("Chỉ đạo của Sở năm nay", FreshnessIntent.DATE_WINDOW),
        ("Thông báo ban hành hôm nay", FreshnessIntent.DATE_WINDOW),
        ("Văn bản tháng sau", FreshnessIntent.DATE_WINDOW),
        ("Nhiệm vụ năm trước", FreshnessIntent.DATE_WINDOW),
        ("Dự thảo năm tới", FreshnessIntent.DATE_WINDOW),
        # Plain questions (NONE)
        ("Tuyển sinh lớp 10 năm học 2026-2027 gồm những môn thi nào?", FreshnessIntent.NONE),
        ("Quy định về định mức giáo viên tiểu học", FreshnessIntent.NONE),
        ("Cách tính lương phụ cấp ưu đãi nghề giáo viên", FreshnessIntent.NONE),
        ("", FreshnessIntent.NONE),
        ("   ", FreshnessIntent.NONE),
    ],
)
def test_detect_freshness_intent_phrases(query: str, expected_intent: FreshnessIntent) -> None:
    """Each recognised phrase maps to the expected FreshnessIntent; plain questions map to NONE."""
    assert detect_freshness_intent(query) == expected_intent


# ---------------------------------------------------------------------------
# 2. Ambiguous / contradictory queries return NONE
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "query",
    [
        "Văn bản mới nhất hay cũ nhất?",
        "So sánh văn bản mới ban hành và văn bản ban hành sớm nhất",
        "Văn bản đầu tiên và mới nhất về tuyển sinh là gì?",
        "Cũ nhất hay mới nhất?",
        "gần đây nhất hoặc sớm nhất",
    ],
)
def test_ambiguous_conflicting_intent_returns_none(query: str) -> None:
    """Queries containing both NEWEST and OLDEST markers return NONE to avoid guessing."""
    assert detect_freshness_intent(query) == FreshnessIntent.NONE


# ---------------------------------------------------------------------------
# 3. Diacritics matter
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "query",
    [
        "van ban moi nhat",
        "moi nhat",
        "moi nhat la",
        "cu nhat",
        "som nhat",
        "dau tien",
        "thang nay",
        "tuan nay",
        "nam nay",
        "hom nay",
    ],
)
def test_diacritics_matter_non_diacritic_returns_none(query: str) -> None:
    # Diacritic sensitivity is strictly intended: MamaGift operates over an authoritative
    # Vietnamese legal corpus where diacritics differentiate distinct semantic meanings.
    # Non-diacritic input is treated as unrecognised (NONE).
    assert detect_freshness_intent(query) == FreshnessIntent.NONE


# ---------------------------------------------------------------------------
# 4. Chronological and reverse-chronological ordering with exact reversal
# ---------------------------------------------------------------------------


def test_order_by_freshness_newest_and_oldest_reversal() -> None:
    """order_by_freshness orders descending for NEWEST and ascending for OLDEST."""
    doc_2024 = _make_doc("doc_2024", issued_date=date(2024, 1, 15))
    doc_2025 = _make_doc("doc_2025", issued_date=date(2025, 6, 20))
    doc_2026 = _make_doc("doc_2026", issued_date=date(2026, 3, 31))

    docs = [doc_2025, doc_2024, doc_2026]

    newest_ordered = order_by_freshness(docs, FreshnessIntent.NEWEST)
    assert newest_ordered == [doc_2026, doc_2025, doc_2024]

    oldest_ordered = order_by_freshness(docs, FreshnessIntent.OLDEST)
    assert oldest_ordered == [doc_2024, doc_2025, doc_2026]

    # Exact reversal for dated documents
    assert newest_ordered == list(reversed(oldest_ordered))

    # NONE and DATE_WINDOW preserve original sequence order
    assert order_by_freshness(docs, FreshnessIntent.NONE) == docs
    assert order_by_freshness(docs, FreshnessIntent.DATE_WINDOW) == docs


# ---------------------------------------------------------------------------
# 5. Undated documents sort last in BOTH directions & never returned as newest
# ---------------------------------------------------------------------------


def test_undated_documents_sort_last_in_both_directions() -> None:
    """Documents with issued_date=None MUST sort to the end in both NEWEST and OLDEST."""
    d_early = _make_doc("d_early", issued_date=date(2025, 1, 1))
    d_late = _make_doc("d_late", issued_date=date(2026, 12, 1))
    u1 = _make_doc("u1_no_date", issued_date=None)
    u2 = _make_doc("u2_no_date", issued_date=None)

    docs = [u1, d_early, u2, d_late]

    newest_result = order_by_freshness(docs, FreshnessIntent.NEWEST)
    assert newest_result == [d_late, d_early, u1, u2]

    oldest_result = order_by_freshness(docs, FreshnessIntent.OLDEST)
    assert oldest_result == [d_early, d_late, u1, u2]


def test_undated_documents_never_returned_as_newest() -> None:
    """An undated document is NEVER returned as `newest` in FreshnessAnswer."""
    u1 = _make_doc("u1", issued_date=None)
    u2 = _make_doc("u2", issued_date=None)

    ans = resolve_freshness([u1, u2], "Văn bản mới nhất là văn bản nào?")
    assert ans.intent == FreshnessIntent.NEWEST
    assert ans.ordered == (u1, u2)
    assert ans.undated == (u1, u2)
    # Critical invariant: newest is None when all candidate documents are undated
    assert ans.newest is None
    assert ans.newest is not u1
    assert ans.newest is not u2


def test_mixed_dated_and_undated_reports_undated_tuple() -> None:
    d1 = _make_doc("d1", issued_date=date(2026, 5, 1))
    u1 = _make_doc("u1", issued_date=None)

    ans = resolve_freshness([u1, d1], "Văn bản mới nhất")
    assert ans.ordered == (d1, u1)
    assert ans.newest == d1
    assert ans.undated == (u1,)


# ---------------------------------------------------------------------------
# 6. Equal issued_date ties break by document_id ascending
# ---------------------------------------------------------------------------


def test_tie_breaking_by_document_id_ascending() -> None:
    """When issued_date is equal, tie breaks by document_id ascending in both directions."""
    d_z = _make_doc("z_doc", issued_date=date(2026, 5, 1))
    d_a = _make_doc("a_doc", issued_date=date(2026, 5, 1))
    d_m = _make_doc("m_doc", issued_date=date(2026, 5, 1))

    d_old_y = _make_doc("y_old", issued_date=date(2024, 1, 1))
    d_old_b = _make_doc("b_old", issued_date=date(2024, 1, 1))

    docs = [d_z, d_old_y, d_m, d_old_b, d_a]

    newest_result = order_by_freshness(docs, FreshnessIntent.NEWEST)
    assert newest_result == [d_a, d_m, d_z, d_old_b, d_old_y]

    oldest_result = order_by_freshness(docs, FreshnessIntent.OLDEST)
    assert oldest_result == [d_old_b, d_old_y, d_a, d_m, d_z]


def test_undated_tie_breaking_by_document_id_ascending() -> None:
    """Undated documents also break ties deterministically by document_id ascending."""
    u_z = _make_doc("u_z", issued_date=None)
    u_a = _make_doc("u_a", issued_date=None)
    u_m = _make_doc("u_m", issued_date=None)

    docs = [u_z, u_m, u_a]
    assert order_by_freshness(docs, FreshnessIntent.NEWEST) == [u_a, u_m, u_z]
    assert order_by_freshness(docs, FreshnessIntent.OLDEST) == [u_a, u_m, u_z]


# ---------------------------------------------------------------------------
# 7. Input sequence immutability
# ---------------------------------------------------------------------------


def test_order_by_freshness_does_not_mutate_input() -> None:
    """order_by_freshness and resolve_freshness must never mutate the input sequence."""
    doc_1 = _make_doc("doc_1", issued_date=date(2026, 1, 1))
    doc_2 = _make_doc("doc_2", issued_date=date(2025, 1, 1))
    doc_3 = _make_doc("doc_3", issued_date=None)

    original_list = [doc_1, doc_2, doc_3]
    snapshot = list(original_list)

    _ = order_by_freshness(original_list, FreshnessIntent.NEWEST)
    assert original_list == snapshot

    _ = order_by_freshness(original_list, FreshnessIntent.OLDEST)
    assert original_list == snapshot

    _ = resolve_freshness(original_list, "mới nhất")
    assert original_list == snapshot


# ---------------------------------------------------------------------------
# 8. Caveat generation
# ---------------------------------------------------------------------------


def test_resolve_freshness_caveat_rules() -> None:
    """Caveat is set when intent is NEWEST/OLDEST with 2+ documents; None otherwise."""
    doc_1 = _make_doc("doc_1", issued_date=date(2026, 3, 1))
    doc_2 = _make_doc("doc_2", issued_date=date(2025, 3, 1))

    # 2 docs + NEWEST
    ans_newest = resolve_freshness([doc_1, doc_2], "văn bản mới nhất")
    assert ans_newest.caveat == NEWEST_CAVEAT
    assert ans_newest.caveat == (
        "Đây là văn bản mới nhất theo ngày ban hành, không có nghĩa là văn bản này thay thế hoặc "
        "bãi bỏ các văn bản trước đó."
    )

    # 2 docs + OLDEST
    ans_oldest = resolve_freshness([doc_1, doc_2], "văn bản cũ nhất")
    assert ans_oldest.caveat == OLDEST_CAVEAT
    assert ans_oldest.caveat == (
        "Đây là văn bản ban hành sớm nhất theo ngày ban hành, không có nghĩa là văn bản này đã hết "
        "hiệu lực hoặc bị thay thế bởi các văn bản sau đó."
    )

    # 1 doc + NEWEST -> None
    ans_single_new = resolve_freshness([doc_1], "văn bản mới nhất")
    assert ans_single_new.caveat is None

    # 1 doc + OLDEST -> None
    ans_single_old = resolve_freshness([doc_1], "văn bản cũ nhất")
    assert ans_single_old.caveat is None

    # 0 docs + NEWEST -> None
    ans_empty = resolve_freshness([], "văn bản mới nhất")
    assert ans_empty.caveat is None

    # 2 docs + NONE -> None
    ans_none = resolve_freshness([doc_1, doc_2], "quy định tuyển sinh lớp 10")
    assert ans_none.caveat is None

    # 2 docs + DATE_WINDOW -> None
    ans_date_window = resolve_freshness([doc_1, doc_2], "văn bản trong tháng này")
    assert ans_date_window.caveat is None


# ---------------------------------------------------------------------------
# 9. Anti-hallucination gate: supersession_claim is ALWAYS None
# ---------------------------------------------------------------------------


def test_supersession_claim_is_always_none() -> None:
    """supersession_claim must be None for EVERY input, even with explicit titles."""
    doc_replace = _make_doc(
        "doc_replace",
        issued_date=date(2026, 6, 1),
        title="Thông tư thay thế Quyết định số 12/2020/QĐ-UBND và bãi bỏ Thông tư 05/2019",
        document_number="19/2026/TT-BGDĐT",
    )
    doc_old = _make_doc(
        "doc_old",
        issued_date=date(2020, 1, 1),
        title="Quyết định số 12/2020/QĐ-UBND",
        document_number="12/2020/QĐ-UBND",
    )

    # Even with blatant replacement language in the document metadata, freshness resolution
    # strictly refuses to claim supersession. Legal control requires evidence-backed relations.
    ans = resolve_freshness(
        [doc_old, doc_replace],
        "Văn bản mới nhất thay thế và bãi bỏ các văn bản cũ",
    )
    assert ans.supersession_claim is None
    assert ans.newest == doc_replace

    # Also None for empty and undated inputs
    assert resolve_freshness([], "mới nhất").supersession_claim is None
    assert resolve_freshness([_make_doc("u", None)], "mới nhất").supersession_claim is None


# ---------------------------------------------------------------------------
# 10. Single-document and empty inputs behave sanely
# ---------------------------------------------------------------------------


def test_empty_and_single_document_boundary_conditions() -> None:
    """Empty and single-document inputs behave sanely without crashing."""
    # Empty input
    empty_ans = resolve_freshness([], "văn bản mới nhất")
    assert isinstance(empty_ans, FreshnessAnswer)
    assert empty_ans.intent == FreshnessIntent.NEWEST
    assert empty_ans.ordered == ()
    assert empty_ans.newest is None
    assert empty_ans.undated == ()
    assert empty_ans.supersession_claim is None
    assert empty_ans.caveat is None

    # Single dated document
    doc_dated = _make_doc("doc_d", issued_date=date(2026, 1, 10))
    single_dated_ans = resolve_freshness([doc_dated], "văn bản mới nhất")
    assert single_dated_ans.intent == FreshnessIntent.NEWEST
    assert single_dated_ans.ordered == (doc_dated,)
    assert single_dated_ans.newest == doc_dated
    assert single_dated_ans.undated == ()
    assert single_dated_ans.supersession_claim is None
    assert single_dated_ans.caveat is None

    # Single undated document
    doc_undated = _make_doc("doc_u", issued_date=None)
    single_undated_ans = resolve_freshness([doc_undated], "văn bản mới nhất")
    assert single_undated_ans.intent == FreshnessIntent.NEWEST
    assert single_undated_ans.ordered == (doc_undated,)
    assert single_undated_ans.newest is None
    assert single_undated_ans.undated == (doc_undated,)
    assert single_undated_ans.supersession_claim is None
    assert single_undated_ans.caveat is None

    # Single document with plain query
    plain_ans = resolve_freshness([doc_dated], "thủ tục hành chính")
    assert plain_ans.intent == FreshnessIntent.NONE
    assert plain_ans.ordered == (doc_dated,)
    assert plain_ans.newest is None
    assert plain_ans.undated == ()
    assert plain_ans.caveat is None
