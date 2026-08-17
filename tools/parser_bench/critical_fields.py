"""Minimal critical-field extraction, for benchmark scoring only.

Scope guard: full Vietnamese administrative semantic extraction is Phase 2 work. What
lives here is the smallest deterministic rule set needed to answer one benchmark
question — did the parser preserve the facts whose corruption is release-blocking?

Nothing is ever guessed. A field that cannot be located returns `None`, so a parser is
never credited for a value the extractor invented.
"""

from __future__ import annotations

import re
import unicodedata

from mamagift_docpipe.canonical import BlockType, CanonicalDocument

EXTRACTOR_NAME = "bench-critical-fields"
EXTRACTOR_VERSION = "1.0"

CRITICAL_FIELD_NAMES = (
    "document_number",
    "issue_date",
    "issuer",
    "title",
    "signer",
    "deadline",
)

# Fields where a wrong value is severity 3 in docs/05_TEST_STRATEGY.md section 8.
SEVERITY_3_FIELDS = frozenset({"document_number", "issue_date", "deadline"})

_DOCUMENT_NUMBER = re.compile(
    r"Số\s*:?\s*([0-9]+\s*/\s*[0-9A-Za-zĐ\-\.]+(?:\s*-\s*[0-9A-Za-zĐ]+)*)"
)
_DATE = re.compile(r"ngày\s+(\d{1,2})\s+tháng\s+(\d{1,2})\s+năm\s+(\d{4})", re.IGNORECASE)
_DEADLINE = re.compile(
    r"(?:trước|chậm nhất|hạn cuối)\s+(?:ngày\s+)?(\d{1,2})\s+tháng\s+(\d{1,2})\s+năm\s+(\d{4})",
    re.IGNORECASE,
)
_SUBJECT = re.compile(r"V/v\s+(.+)", re.IGNORECASE)


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text)).strip()


def _iso_date(day: str, month: str, year: str) -> str:
    return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"


def extract_critical_fields(document: CanonicalDocument) -> dict[str, str | None]:
    """Extract benchmark critical fields from a canonical document."""
    blocks = document.iter_blocks()
    texts = [_clean(block.text) for block in blocks if block.text.strip()]
    joined = "\n".join(texts)

    fields: dict[str, str | None] = dict.fromkeys(CRITICAL_FIELD_NAMES)

    number_match = _DOCUMENT_NUMBER.search(joined)
    if number_match:
        fields["document_number"] = re.sub(r"\s+", "", number_match.group(1))

    date_match = _DATE.search(joined)
    if date_match:
        fields["issue_date"] = _iso_date(*date_match.groups())

    deadline_match = _DEADLINE.search(joined)
    if deadline_match:
        fields["deadline"] = _iso_date(*deadline_match.groups())

    subject_match = _SUBJECT.search(joined)
    if subject_match:
        fields["title"] = _clean(subject_match.group(1).split("\n")[0])
    else:
        title_blocks = [block for block in blocks if block.type == BlockType.TITLE]
        if title_blocks:
            fields["title"] = _clean(title_blocks[0].text)

    # The issuing organization is conventionally the first line of page 1, above the
    # document number. Anything after that line is not treated as the issuer.
    first_page_texts = [
        _clean(block.text)
        for block in blocks
        if block.provenance.page_number == 1 and block.text.strip()
    ]
    for text in first_page_texts:
        if _DOCUMENT_NUMBER.search(text):
            break
        if text.isupper() and len(text) > 3:
            fields["issuer"] = text
            break

    signature_blocks = [block for block in blocks if block.type == BlockType.SIGNATURE]
    if signature_blocks:
        fields["signer"] = _clean(signature_blocks[-1].text)

    return fields


def severity_3_failures(expected: dict[str, str], wrong_fields: list[str]) -> list[str]:
    """Which wrong fields are release-blocking rather than merely disappointing."""
    return [name for name in wrong_fields if name in SEVERITY_3_FIELDS and name in expected]
