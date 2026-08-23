"""Vietnamese tokenisation for Phase 4 lexical (BM25) retrieval.

Handles:
- Unicode NFC normalization and diacritic sensitivity (full Vietnamese alphabet).
- Document numbers such as `12/KH-UBND`, `45/2026/NĐ-CP`, `15/BC-BGDĐT` without shattering.
- Legal hierarchy markers: `Điều`, `Khoản`, `Điểm`, `Chương`, `Mục`, `Phụ lục`.
- Date expressions: `ngày 31 tháng 03 năm 2026`, `31/03/2026`.
- General Vietnamese words, syllables, acronyms, and alphanumeric terms.
"""

from __future__ import annotations

import re
import unicodedata

# Regex for document numbers, e.g. 12/KH-UBND, 45/2026/NĐ-CP, 01/TB-VP, 123/QĐ-UBND
_DOC_NUMBER_RE = re.compile(
    r"\b\d+/(?:[a-z0-9_.\-à-ỹđ]+/?)+",
    re.IGNORECASE | re.UNICODE,
)

# Regex for full date expressions: ngày DD tháng MM năm YYYY
_FULL_DATE_RE = re.compile(
    r"\bngày\s+(\d{1,2})\s+tháng\s+(\d{1,2})\s+năm\s+(\d{4})\b",
    re.IGNORECASE | re.UNICODE,
)

# Regex for slash/dash dates: DD/MM/YYYY or DD-MM-YYYY
_SLASH_DATE_RE = re.compile(
    r"\b(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})\b",
    re.UNICODE,
)

# Regex for legal hierarchy markers:
# e.g. Điều 1, Điều 12a, Khoản 2, Điểm a, Chương I, Mục 1, Phụ lục I
_LEGAL_MARKER_RE = re.compile(
    r"\b(điều|khoản|điểm|chương|mục|phụ\s+lục)\s+([0-9]+[a-zà-ỹđ]?|[ivxlcdm]+|[a-zà-ỹđ])\b",
    re.IGNORECASE | re.UNICODE,
)

# Regex for standalone "phụ lục"
_PHU_LUC_RE = re.compile(
    r"\bphụ\s+lục\b",
    re.IGNORECASE | re.UNICODE,
)

# Regex for general Vietnamese word tokens (alphanumeric including diacritics)
_WORD_RE = re.compile(
    r"[a-zà-ỹđ0-9]+",
    re.IGNORECASE | re.UNICODE,
)


def normalize_vi_text(text: str) -> str:
    """Normalize text into Unicode NFC form and standard whitespace."""
    if not text:
        return ""
    normalized = unicodedata.normalize("NFC", text)
    # Normalize spaced slashes in potential document numbers: "12 / KH - UBND" -> "12/KH-UBND"
    normalized = re.sub(r"(\d+)\s*/\s*([A-Za-z0-9_.\-À-ỹđĐ]+)", r"\1/\2", normalized)
    return normalized


def tokenize_vi(text: str) -> list[str]:
    """Tokenize Vietnamese text for lexical BM25 retrieval.

    Extracts:
    1. Document numbers (preserved as indivisible single tokens, e.g. '12/kh-ubnd').
    2. Date expressions (both formatted compound '31/03/2026' and individual tokens).
    3. Legal hierarchy compound markers (e.g. 'điều_1', 'khoản_2', 'điểm_a', 'chương_i').
    4. General Vietnamese words/syllables and alphanumeric terms with full diacritics.

    Returns a deterministic list of lowercase tokens.
    """
    if not text or not text.strip():
        return []

    norm_text = normalize_vi_text(text).lower()
    tokens: list[str] = []

    # 1. Extract and preserve document numbers
    for match in _DOC_NUMBER_RE.finditer(norm_text):
        doc_num = match.group().strip("./-")
        if doc_num:
            tokens.append(doc_num)

    # 2. Extract full date expressions
    for match in _FULL_DATE_RE.finditer(norm_text):
        day, month, year = match.groups()
        day_fmt = f"{int(day):02d}"
        month_fmt = f"{int(month):02d}"
        tokens.append(f"{day_fmt}/{month_fmt}/{year}")
        tokens.append(f"ngày_{day_fmt}_tháng_{month_fmt}_năm_{year}")

    # 3. Extract slash dates
    for match in _SLASH_DATE_RE.finditer(norm_text):
        day, month, year = match.groups()
        day_fmt = f"{int(day):02d}"
        month_fmt = f"{int(month):02d}"
        tokens.append(f"{day_fmt}/{month_fmt}/{year}")

    # 4. Extract legal hierarchy markers (compound tokens)
    for match in _LEGAL_MARKER_RE.finditer(norm_text):
        marker, identifier = match.groups()
        marker_clean = re.sub(r"\s+", "_", marker.strip())
        compound = f"{marker_clean}_{identifier.strip()}"
        tokens.append(compound)

    # 5. Extract standalone "phụ lục"
    for _ in _PHU_LUC_RE.finditer(norm_text):
        tokens.append("phụ_lục")

    # 6. Extract individual word/syllable tokens
    for word_match in _WORD_RE.finditer(norm_text):
        w = word_match.group()
        if w:
            tokens.append(w)

    return tokens
