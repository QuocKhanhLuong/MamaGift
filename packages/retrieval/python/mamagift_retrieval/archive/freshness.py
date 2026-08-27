"""Freshness semantics for archive-scoped retrieval.

MamaGift must answer queries like "Văn bản mới nhất liên quan tới tuyển sinh là văn bản nào?"
by ranking candidate documents by issued_date, but a newer document does NOT automatically
supersede an older one. Legal supersession or repeal requires an explicit, evidence-backed
relation from `document_relations`, never inferred from temporal recency.

This module provides deterministic freshness intent detection, recency-based ordering, and
Vietnamese legal caveats that prevent users from interpreting date ordering as a legal conclusion.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from mamagift_retrieval.archive.protocol import ArchiveDocumentRef

NEWEST_CAVEAT: str = (
    "Đây là văn bản mới nhất theo ngày ban hành, không có nghĩa là văn bản này thay thế hoặc "
    "bãi bỏ các văn bản trước đó."
)
"""Vietnamese caveat applied when ordering documents by NEWEST intent.

States clearly that date recency does not imply legal supersession or repeal.
"""

OLDEST_CAVEAT: str = (
    "Đây là văn bản ban hành sớm nhất theo ngày ban hành, không có nghĩa là văn bản này đã hết "
    "hiệu lực hoặc bị thay thế bởi các văn bản sau đó."
)
"""Vietnamese caveat applied when ordering documents by OLDEST intent.

States clearly that being the earliest document does not imply invalidity or supersession.
"""

_NEWEST_PHRASES: tuple[str, ...] = (
    "mới nhất là",
    "mới nhất",
    "gần đây nhất",
    "gần nhất",
    "mới ban hành",
    "cập nhật nhất",
)

_OLDEST_PHRASES: tuple[str, ...] = (
    "ban hành sớm nhất",
    "cũ nhất",
    "sớm nhất",
    "đầu tiên",
)

_DATE_WINDOW_PHRASES: tuple[str, ...] = (
    "tháng này",
    "tháng trước",
    "tháng sau",
    "tuần này",
    "tuần trước",
    "tuần tới",
    "năm nay",
    "năm trước",
    "năm tới",
    "hôm nay",
)


class FreshnessIntent(StrEnum):
    """Temporal freshness intent detected from a user query."""

    NONE = "none"  # no freshness signal in the query
    NEWEST = "newest"  # "mới nhất", "gần đây nhất", "mới ban hành", "cập nhật nhất"
    OLDEST = "oldest"  # "cũ nhất", "sớm nhất", "đầu tiên", "ban hành sớm nhất"
    DATE_WINDOW = "date_window"  # "tháng này", "trong tuần này", "năm nay", "hôm nay"


def _contains_phrase(text: str, phrase: str) -> bool:
    """Check if phrase occurs in normalized text with word boundary semantics."""
    pattern = r"(?:\b|^)" + re.escape(phrase) + r"(?:\b|$)"
    return bool(re.search(pattern, text))


def detect_freshness_intent(query: str) -> FreshnessIntent:
    """Detect the temporal freshness intent from a query string.

    Diacritic-sensitive, NFC-normalized, case-insensitive.
    Requires Vietnamese diacritics: non-diacritic text like 'moi nhat' will NOT match
    because the authoritative corpus is diacritic-correct Vietnamese.

    An ambiguous query containing both a NEWEST marker and an OLDEST marker returns
    `FreshnessIntent.NONE` because guessing between contradictory intents would be worse
    than declining.
    """
    if not query or not query.strip():
        return FreshnessIntent.NONE

    norm_text = " ".join(unicodedata.normalize("NFC", query).lower().split())

    has_newest = any(_contains_phrase(norm_text, p) for p in _NEWEST_PHRASES)
    has_oldest = any(_contains_phrase(norm_text, p) for p in _OLDEST_PHRASES)
    has_date_window = any(_contains_phrase(norm_text, p) for p in _DATE_WINDOW_PHRASES)

    # Contradictory signals: declining is safer than guessing.
    if has_newest and has_oldest:
        return FreshnessIntent.NONE

    if has_newest:
        return FreshnessIntent.NEWEST
    if has_oldest:
        return FreshnessIntent.OLDEST
    if has_date_window:
        return FreshnessIntent.DATE_WINDOW

    return FreshnessIntent.NONE


def _dated_sort_key_newest(doc: ArchiveDocumentRef) -> tuple[int, str]:
    assert doc.issued_date is not None
    return (-doc.issued_date.toordinal(), doc.document_id)


def _dated_sort_key_oldest(doc: ArchiveDocumentRef) -> tuple[int, str]:
    assert doc.issued_date is not None
    return (doc.issued_date.toordinal(), doc.document_id)


def order_by_freshness(
    documents: Sequence[ArchiveDocumentRef],
    intent: FreshnessIntent,
) -> list[ArchiveDocumentRef]:
    """Order documents by issued_date according to freshness intent.

    Rules:
    - NEWEST: descending `issued_date`.
    - OLDEST: ascending `issued_date`.
    - NONE / DATE_WINDOW: input order preserved.
    - Documents with `issued_date is None` are NEVER ranked as newest or oldest.
      They sort to the END in both directions, because an unknown date is not a
      late date and not an early one. This is a correctness rule, not a convenience.
    - Deterministic tie-break for equal dates: `document_id` ascending.
      (Both among dated documents on the same date and among undated documents).
    - Never mutates the input sequence.
    """
    if intent not in (FreshnessIntent.NEWEST, FreshnessIntent.OLDEST):
        return list(documents)

    dated: list[ArchiveDocumentRef] = []
    undated: list[ArchiveDocumentRef] = []
    for doc in documents:
        if doc.issued_date is not None:
            dated.append(doc)
        else:
            undated.append(doc)

    sorted_undated = sorted(undated, key=lambda d: d.document_id)

    if intent == FreshnessIntent.NEWEST:
        sorted_dated = sorted(dated, key=_dated_sort_key_newest)
    else:
        sorted_dated = sorted(dated, key=_dated_sort_key_oldest)

    return sorted_dated + sorted_undated


@dataclass(frozen=True)
class FreshnessAnswer:
    """The structured result of freshness resolution over candidate documents.

    `supersession_claim` is typed `None` and is ALWAYS `None`. It exists as an explicit,
    greppable statement that this module cannot express supersession: recency ordering is not a
    legal relation, and any supersedes/replaces/amends claim must come from an evidence-backed
    `document_relations` row, never inferred here.
    """

    intent: FreshnessIntent
    ordered: tuple[ArchiveDocumentRef, ...]
    newest: ArchiveDocumentRef | None
    undated: tuple[ArchiveDocumentRef, ...]
    supersession_claim: None
    caveat: str | None


def resolve_freshness(
    documents: Sequence[ArchiveDocumentRef],
    query: str,
) -> FreshnessAnswer:
    """Resolve freshness intent, ordering, newest document, and legal caveats.

    Args:
        documents: The candidate documents to order.
        query: The user query to inspect for freshness intent.

    Returns:
        FreshnessAnswer containing:
        - `intent`: detected FreshnessIntent
        - `ordered`: documents ordered by date (undated docs at the end)
        - `newest`: the newest dated document if intent is NEWEST, else None
        - `undated`: tuple of documents lacking an issued_date
        - `supersession_claim`: ALWAYS None (anti-hallucination guarantee)
        - `caveat`: Vietnamese legal disclaimer when intent is NEWEST/OLDEST with 2+ docs
    """
    intent = detect_freshness_intent(query)
    ordered_list = order_by_freshness(documents, intent)
    ordered = tuple(ordered_list)

    undated = tuple(doc for doc in ordered_list if doc.issued_date is None)

    newest: ArchiveDocumentRef | None = None
    if intent == FreshnessIntent.NEWEST:
        for doc in ordered_list:
            if doc.issued_date is not None:
                newest = doc
                break

    caveat: str | None = None
    if len(ordered) >= 2:
        if intent == FreshnessIntent.NEWEST:
            caveat = NEWEST_CAVEAT
        elif intent == FreshnessIntent.OLDEST:
            caveat = OLDEST_CAVEAT

    return FreshnessAnswer(
        intent=intent,
        ordered=ordered,
        newest=newest,
        undated=undated,
        supersession_claim=None,
        caveat=caveat,
    )


__all__ = [
    "NEWEST_CAVEAT",
    "OLDEST_CAVEAT",
    "FreshnessAnswer",
    "FreshnessIntent",
    "detect_freshness_intent",
    "order_by_freshness",
    "resolve_freshness",
]
