"""Exact identifier extraction and matching for Vietnamese archive queries.

Extracts administrative document numbers, legal hierarchy markers (Điều, Khoản, Điểm,
Chương, Mục, Phụ lục), and date expressions from query text for exact matching boost.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from mamagift_retrieval.archive.filters import normalize_identifier
from mamagift_retrieval.search.vi_tokenize import (
    _DOC_NUMBER_RE,
    _FULL_DATE_RE,
    _LEGAL_MARKER_RE,
    _PHU_LUC_RE,
    _SLASH_DATE_RE,
    normalize_vi_text,
    tokenize_vi,
)


class LegalMarker(BaseModel):
    """A legal hierarchy marker (e.g. Điều 7, Khoản 2, Điểm a, Phụ lục I)."""

    model_config = ConfigDict(extra="forbid")

    marker: str  # normalised lowercase: "điều" | "khoản" | "điểm" | "chương" | "mục" | "phụ lục"
    value: str  # "7", "2", "a", "i", "12a" -- as written, lowercased ("" for standalone phụ lục)
    token: str  # tokenize_vi compound form, e.g. "điều_7" or "phụ_lục"


class QueryIdentifiers(BaseModel):
    """Structured identifiers extracted from an archive query."""

    model_config = ConfigDict(extra="forbid")

    document_numbers: list[str] = Field(default_factory=list)
    legal_markers: list[LegalMarker] = Field(default_factory=list)
    dates: list[date] = Field(default_factory=list)
    raw_date_tokens: list[str] = Field(default_factory=list)

    def is_empty(self) -> bool:
        """Whether this query identifier set contains no extracted signals."""
        return not (
            self.document_numbers or self.legal_markers or self.dates or self.raw_date_tokens
        )


def _clean_for_doc_numbers(text: str) -> str:
    """NFC normalise and collapse whitespace around `/` and `-` for document numbers."""
    t = unicodedata.normalize("NFC", text)
    t = re.sub(r"\s*/\s*", "/", t)
    t = re.sub(r"(?<=[A-Za-z0-9_.\-À-ỹđĐ])\s*-\s*(?=[A-Za-z0-9_.\-À-ỹđĐ])", "-", t)
    return t


def extract_query_identifiers(query: str) -> QueryIdentifiers:
    """Extract structured administrative identifiers, legal markers, and dates from a query.

    Lists are deduplicated while preserving first appearance order.
    """
    if not query or not query.strip():
        return QueryIdentifiers()

    # 1. Extract document numbers (e.g. 19/2026/TT-BGDĐT, 57/QĐ-UBND, 12/KH-UBND, 45/2026/NĐ-CP)
    cleaned_doc_query = _clean_for_doc_numbers(query)
    doc_numbers: list[str] = []
    seen_doc_numbers: set[str] = set()
    for match in _DOC_NUMBER_RE.finditer(cleaned_doc_query):
        raw = match.group().strip("./-")
        if not raw or _SLASH_DATE_RE.fullmatch(raw):
            continue
        try:
            norm = normalize_identifier(raw)
        except (TypeError, ValueError):
            continue
        if norm and norm not in seen_doc_numbers:
            seen_doc_numbers.add(norm)
            doc_numbers.append(norm)

    # 2. Extract legal hierarchy markers
    norm_text = normalize_vi_text(query).lower()
    marker_matches: list[tuple[int, int, LegalMarker]] = []

    for m in _LEGAL_MARKER_RE.finditer(norm_text):
        raw_marker, raw_val = m.groups()
        marker_norm = " ".join(raw_marker.strip().split())
        marker_clean = re.sub(r"\s+", "_", raw_marker.strip())
        val_clean = raw_val.strip().lower()
        token = f"{marker_clean}_{val_clean}"
        marker_matches.append(
            (m.start(), m.end(), LegalMarker(marker=marker_norm, value=val_clean, token=token))
        )

    # Standalone 'phụ lục'
    for m in _PHU_LUC_RE.finditer(norm_text):
        if any(start <= m.start() < end for start, end, _ in marker_matches):
            continue
        marker_matches.append(
            (m.start(), m.end(), LegalMarker(marker="phụ lục", value="", token="phụ_lục"))
        )

    marker_matches.sort(key=lambda x: x[0])
    legal_markers: list[LegalMarker] = []
    seen_marker_tokens: set[str] = set()
    for _, _, lm in marker_matches:
        if lm.token not in seen_marker_tokens:
            seen_marker_tokens.add(lm.token)
            legal_markers.append(lm)

    # 3. Extract date expressions
    date_matches: list[tuple[int, str, str, str]] = []
    for m in _FULL_DATE_RE.finditer(norm_text):
        d_str, m_str, y_str = m.groups()
        date_matches.append((m.start(), d_str, m_str, y_str))

    cleaned_slash_query = re.sub(r"\s*/\s*", "/", norm_text)
    for m in _SLASH_DATE_RE.finditer(cleaned_slash_query):
        d_str, m_str, y_str = m.groups()
        date_matches.append((m.start(), d_str, m_str, y_str))

    date_matches.sort(key=lambda x: x[0])
    dates: list[date] = []
    seen_dates: set[date] = set()
    raw_date_tokens: list[str] = []
    seen_raw_date_tokens: set[str] = set()

    for _, d_str, m_str, y_str in date_matches:
        d_int = int(d_str)
        m_int = int(m_str)
        y_int = int(y_str)
        raw_token = f"{d_int:02d}/{m_int:02d}/{y_int:04d}"
        if raw_token not in seen_raw_date_tokens:
            seen_raw_date_tokens.add(raw_token)
            raw_date_tokens.append(raw_token)
        try:
            d_obj = date(y_int, m_int, d_int)
            if d_obj not in seen_dates:
                seen_dates.add(d_obj)
                dates.append(d_obj)
        except (ValueError, OverflowError):
            pass

    return QueryIdentifiers(
        document_numbers=doc_numbers,
        legal_markers=legal_markers,
        dates=dates,
        raw_date_tokens=raw_date_tokens,
    )


def identifier_match_score(
    identifiers: QueryIdentifiers,
    chunk_text: str,
    document_number: str | None,
) -> float:
    """Compute a bounded [0.0, 1.0] exact identifier boost signal.

    Weighting policy:
    1. Returns 0.0 if `identifiers.is_empty()` or no identifiers match.
    2. Returns 1.0 if the query has document_numbers and chunk's normalised `document_number`
       matches one of them.
    3. If query has document_numbers but document_number does not match:
       Score is strictly bounded below 1.0 (max 0.80):
       score = 0.35 * doc_text_ratio + 0.25 * marker_ratio + 0.20 * date_ratio
    4. If query has NO document_numbers:
       Partial credit for legal markers and dates found in `chunk_text` via tokenize_vi:
       - Both markers and dates: 0.50 * marker_ratio + 0.30 * date_ratio (max 0.80)
       - Only markers: 0.70 * marker_ratio (max 0.70)
       - Only dates: 0.50 * date_ratio (max 0.50)
    """
    if identifiers.is_empty():
        return 0.0

    norm_chunk_doc: str | None = None
    if document_number and document_number.strip():
        try:
            norm_chunk_doc = normalize_identifier(document_number)
        except (TypeError, ValueError):
            norm_chunk_doc = None

    if identifiers.document_numbers and norm_chunk_doc is not None:
        if norm_chunk_doc in identifiers.document_numbers:
            return 1.0

    chunk_tokens = set(tokenize_vi(chunk_text)) if chunk_text else set()

    marker_ratio = 0.0
    if identifiers.legal_markers:
        matched_markers = sum(1 for lm in identifiers.legal_markers if lm.token in chunk_tokens)
        marker_ratio = matched_markers / len(identifiers.legal_markers)

    date_ratio = 0.0
    if identifiers.raw_date_tokens:
        matched_dates = sum(1 for dt in identifiers.raw_date_tokens if dt in chunk_tokens)
        date_ratio = matched_dates / len(identifiers.raw_date_tokens)

    doc_text_ratio = 0.0
    if identifiers.document_numbers:
        matched_doc_tokens = sum(
            1 for dn in identifiers.document_numbers if dn.lower() in chunk_tokens
        )
        doc_text_ratio = matched_doc_tokens / len(identifiers.document_numbers)

    if identifiers.document_numbers:
        score = 0.35 * doc_text_ratio + 0.25 * marker_ratio + 0.20 * date_ratio
    else:
        if identifiers.legal_markers and identifiers.raw_date_tokens:
            score = 0.5 * marker_ratio + 0.3 * date_ratio
        elif identifiers.legal_markers:
            score = 0.7 * marker_ratio
        elif identifiers.raw_date_tokens:
            score = 0.5 * date_ratio
        else:
            score = 0.0

    return min(1.0, max(0.0, float(score)))


__all__ = [
    "LegalMarker",
    "QueryIdentifiers",
    "extract_query_identifiers",
    "identifier_match_score",
]
