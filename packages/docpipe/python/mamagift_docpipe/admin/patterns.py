"""Lexical primitives for Vietnamese administrative documents.

Everything here is text-level and provider-neutral: the administrative parser reads
canonical blocks, never a provider artifact. Patterns are deliberately conservative —
an unmatched line stays a paragraph instead of being forced into a structure it may
not have.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date

# --------------------------------------------------------------------- hierarchy

CHAPTER_RE = re.compile(r"^CHƯƠNG\s+([IVXLCDM]+|\d+)\s*[.:\-–]?\s*(.*)$", re.IGNORECASE)
SECTION_RE = re.compile(r"^MỤC\s+([IVXLCDM]+|\d+)\s*[.:\-–]?\s*(.*)$", re.IGNORECASE)
ARTICLE_RE = re.compile(r"^ĐIỀU\s+(\d+)\s*[.:\-–]?\s*(.*)$", re.IGNORECASE)
APPENDIX_RE = re.compile(r"^PHỤ\s*LỤC\s*([IVXLCDM]+|\d+)?\s*[.:\-–]?\s*(.*)$", re.IGNORECASE)

# `Khoản 2. ...` written out, and the far more common bare `2. ...` inside an article.
CLAUSE_LABELLED_RE = re.compile(r"^KHOẢN\s+(\d+)\s*[.:\-–]?\s*(.*)$", re.IGNORECASE)
CLAUSE_NUMERIC_RE = re.compile(r"^(\d{1,2})\s*[.)]\s+(.+)$")

# `Điểm a) ...` written out, and the bare `a) ...` form.
POINT_LABELLED_RE = re.compile(r"^ĐIỂM\s+([a-zđăâêôơư])\s*[.:\-–)]?\s*(.*)$", re.IGNORECASE)
POINT_LETTER_RE = re.compile(r"^([a-zđăâêôơư])\s*[).]\s+(.+)$")

# --------------------------------------------------------------------------- lists

BULLET_RE = re.compile(r"^[-–—•*+]\s+(.+)$")

# ------------------------------------------------------------------- header fields

# The `\s{0,N}` bounds are load-bearing, not cosmetic: `normalize_text` collapses only
# ASCII/Unicode space separators, so runs of U+3000 or \x0c reach these patterns intact,
# and unbounded back-to-back `\s*` around a group that can fail backtracks quadratically.
NUMBER_RE = re.compile(r"^SỐ\s{0,8}[:.]?\s{0,8}([^\s;,]+)", re.IGNORECASE)
NUMBER_INLINE_RE = re.compile(r"\bSỐ\s{0,8}[:.]\s{0,8}([^\s;,]+)", re.IGNORECASE)
SUBJECT_RE = re.compile(r"^(?:V/v|V\.v|Về\s+việc)\s*[:.]?\s*(.+)$", re.IGNORECASE)
RECIPIENTS_RE = re.compile(r"^NƠI\s*NHẬN\s*[:.]?\s*(.*)$", re.IGNORECASE)
ADDRESSEE_RE = re.compile(r"^KÍNH\s*GỬI\s*[:.]?\s*(.*)$", re.IGNORECASE)

DATE_RE = re.compile(r"ngày\s+(\d{1,2})\s+tháng\s+(\d{1,2})\s+năm\s+(\d{4})", re.IGNORECASE)
NUMERIC_DATE_RE = re.compile(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b")

DEADLINE_MARKERS = (
    "trước ngày",
    "chậm nhất là ngày",
    "chậm nhất ngày",
    "chậm nhất vào ngày",
    "hạn cuối",
    "hoàn thành trước",
    "báo cáo trước",
    "nộp trước",
    "trước thời hạn",
)

# Signature-block role markers. The signer name is the line that follows them.
SIGNER_ROLE_MARKERS = (
    "TM.",
    "KT.",
    "TL.",
    "TUQ.",
    "CHỦ TỊCH",
    "PHÓ CHỦ TỊCH",
    "HIỆU TRƯỞNG",
    "PHÓ HIỆU TRƯỞNG",
    "GIÁM ĐỐC",
    "PHÓ GIÁM ĐỐC",
    "TRƯỞNG PHÒNG",
    "PHÓ TRƯỞNG PHÒNG",
    "THỦ TRƯỞNG",
    "CHÁNH VĂN PHÒNG",
    "TRƯỞNG BAN",
)

# Organisation prefixes used to recognise the issuer line, which is otherwise just
# another uppercase line near the top of page 1.
ISSUER_PREFIXES = (
    "ỦY BAN NHÂN DÂN",
    "UBND",
    "HỘI ĐỒNG NHÂN DÂN",
    "SỞ ",
    "PHÒNG ",
    "BỘ ",
    "TRƯỜNG ",
    "TRUNG TÂM",
    "BAN ",
    "CỤC ",
    "TỔNG CỤC",
    "CHI CỤC",
    "VĂN PHÒNG",
    "ĐẢNG ỦY",
    "CÔNG TY",
)

# Document-type codes as they appear in the `Số:` value, e.g. `57/QĐ-UBND`.
TYPE_CODES: dict[str, str] = {
    "QĐ": "quyet_dinh",
    "CV": "cong_van",
    "KH": "ke_hoach",
    "TB": "thong_bao",
    "BC": "bao_cao",
    "TT": "thong_tu",
    "NĐ": "nghi_dinh",
    "NQ": "nghi_quyet",
    "CT": "chi_thi",
    "HD": "huong_dan",
    "HĐ": "hop_dong",
    "GM": "giay_moi",
    "TTr": "to_trinh",
    "QC": "quy_che",
}

# Spelled-out document types printed as a standalone uppercase line.
TYPE_HEADINGS: dict[str, str] = {
    "QUYẾT ĐỊNH": "quyet_dinh",
    "CÔNG VĂN": "cong_van",
    "KẾ HOẠCH": "ke_hoach",
    "THÔNG BÁO": "thong_bao",
    "BÁO CÁO": "bao_cao",
    "THÔNG TƯ": "thong_tu",
    "NGHỊ ĐỊNH": "nghi_dinh",
    "NGHỊ QUYẾT": "nghi_quyet",
    "CHỈ THỊ": "chi_thi",
    "HƯỚNG DẪN": "huong_dan",
    "GIẤY MỜI": "giay_moi",
    "TỜ TRÌNH": "to_trinh",
    "QUY CHẾ": "quy_che",
}

ROMAN_VALUES: dict[str, int] = {
    "I": 1,
    "V": 5,
    "X": 10,
    "L": 50,
    "C": 100,
    "D": 500,
    "M": 1000,
}


def first_line(text: str) -> str:
    """Structural markers always start a block; only the first line can carry one."""
    return text.split("\n", 1)[0].strip()


def roman_to_int(value: str) -> int | None:
    """Convert a Roman numeral to an int, or return None when it is not one."""
    upper = value.upper()
    if not upper or any(char not in ROMAN_VALUES for char in upper):
        return None
    total = 0
    previous = 0
    for char in reversed(upper):
        current = ROMAN_VALUES[char]
        total += -current if current < previous else current
        previous = max(previous, current)
    return total


def ordinal_of(label: str) -> int | None:
    """Parse an ordinal written either as digits or as a Roman numeral."""
    stripped = label.strip()
    if stripped.isdigit():
        return int(stripped)
    return roman_to_int(stripped)


def parse_vietnamese_date(text: str) -> tuple[str, str] | None:
    """Return `(raw_expression, ISO date)` for the first date found, else None.

    Only real calendar dates are returned; `ngày 31 tháng 2` is not silently coerced.
    """
    match = DATE_RE.search(text)
    if match is not None:
        day, month, year = (int(group) for group in match.groups())
        iso = _iso_or_none(year, month, day)
        return (match.group(0), iso) if iso is not None else None

    numeric = NUMERIC_DATE_RE.search(text)
    if numeric is not None:
        day, month, year = (int(group) for group in numeric.groups())
        iso = _iso_or_none(year, month, day)
        return (numeric.group(0), iso) if iso is not None else None

    return None


def _iso_or_none(year: int, month: int, day: int) -> str | None:
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def strip_accents_upper(text: str) -> str:
    """Accent-insensitive uppercase form, for tolerant keyword matching only."""
    decomposed = unicodedata.normalize("NFD", text.upper())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def is_mostly_upper(text: str) -> bool:
    letters = [char for char in text if char.isalpha()]
    if not letters:
        return False
    return sum(char.isupper() for char in letters) / len(letters) >= 0.9


def looks_like_person_name(text: str) -> bool:
    """Heuristic: a Vietnamese personal name is 2-6 title-case words, no digits."""
    candidate = text.strip().rstrip(".")
    if not candidate or any(char.isdigit() for char in candidate):
        return False
    words = candidate.split()
    if not 2 <= len(words) <= 6:
        return False
    if is_mostly_upper(candidate):
        return False
    return all(word[:1].isupper() for word in words if word[:1].isalpha())


def table_row_cells(text: str) -> list[str] | None:
    """Split a pipe-delimited row into cells, or return None when it is not one."""
    line = first_line(text)
    if line.count("|") < 2:
        return None
    cells = [cell.strip() for cell in line.split("|")]
    if all(not cell for cell in cells):
        return None
    return cells
