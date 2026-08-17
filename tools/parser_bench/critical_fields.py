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

from mamagift_docpipe.admin import patterns as admin_patterns
from mamagift_docpipe.canonical import BlockType, CanonicalBlock, CanonicalDocument

EXTRACTOR_NAME = "bench-critical-fields"
EXTRACTOR_VERSION = "1.1"

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

_DOCUMENT_NUMBER = admin_patterns.NUMBER_RE
_DEADLINE = re.compile(
    r"(?:trước|chậm nhất|hạn cuối)\s{0,2}(?:ngày\s{0,1})?"
    r"(\d{1,2})\s{0,1}tháng\s{0,1}(\d{1,2})\s{0,1}năm\s{0,1}(\d{4})",
    re.IGNORECASE,
)
_SUBJECT = re.compile(
    r"^(?:V/v|V\.v|Về\s{0,2}việc|Ve\s{0,2}viec)\s*[:.]?\s*(.+)$",
    re.IGNORECASE | re.MULTILINE,
)


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text)).strip()


def _iso_date(day: str, month: str, year: str) -> str:
    return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"


def _top_score(block: CanonicalBlock, page_heights: dict[int, float]) -> float:
    if block.bbox is None:
        return 0.0
    ratio = block.bbox.y0 / page_heights.get(block.provenance.page_number, 842.0)
    return 0.16 if ratio <= 0.25 else 0.09 if ratio <= 0.40 else 0.0


def _nearby_score(block: CanonicalBlock, context_blocks: list[CanonicalBlock]) -> float:
    score = 0.0
    for context in context_blocks:
        if context.provenance.page_number != block.provenance.page_number:
            continue
        distance = abs(context.reading_order - block.reading_order)
        score = max(
            score,
            0.12 if distance <= 1 else 0.08 if distance <= 3 else 0.04 if distance <= 6 else 0.0,
        )
    return score


def _context_blocks(blocks: list[CanonicalBlock]) -> list[CanonicalBlock]:
    result: list[CanonicalBlock] = []
    for block in blocks:
        line = block.text.split("\n", 1)[0].strip()
        folded = admin_patterns.compact_matching_key(line)
        if block.type == BlockType.HEADER:
            result.append(block)
        elif admin_patterns.NUMBER_RE.match(line) or admin_patterns.NUMBER_INLINE_RE.search(line):
            result.append(block)
        elif any(
            folded.startswith(admin_patterns.compact_matching_key(prefix))
            for prefix in admin_patterns.ISSUER_PREFIXES
        ):
            result.append(block)
        elif admin_patterns.SUBJECT_RE.match(line):
            result.append(block)
    return result


def _date_marker_kind(text: str, match: admin_patterns.DateMatch) -> tuple[bool, bool]:
    before = text[max(0, match.start - 80) : match.start]
    after = text[match.end : match.end + 48]
    deadline = (
        admin_patterns.marker_position(
            before,
            admin_patterns.DEADLINE_MARKERS + admin_patterns.DEADLINE_DATE_PREFIXES,
        )
        is not None
    )
    referenced = (
        admin_patterns.marker_position(before, admin_patterns.REFERENCE_DATE_MARKERS) is not None
    )
    referenced = (
        referenced or admin_patterns.marker_position(after, ("có hiệu lực", "của")) is not None
    )
    return referenced, deadline


def _select_issue_date(document: CanonicalDocument) -> str | None:
    blocks = [
        block
        for block in document.iter_blocks()
        if block.type not in {BlockType.FOOTER, BlockType.PAGE_NUMBER}
    ]
    context = _context_blocks(blocks)
    page_heights = {page.page_number: page.height for page in document.pages}
    candidates: list[tuple[CanonicalBlock, str, bool, float]] = []
    for block in blocks:
        for match in admin_patterns.parse_vietnamese_dates(block.text):
            referenced, deadline = _date_marker_kind(block.text, match)
            if deadline:
                continue
            score = 0.54
            if block.provenance.page_number == 1:
                score += 0.14
            if block.type == BlockType.HEADER:
                score += 0.02
            score += _top_score(block, page_heights)
            score += _nearby_score(block, context)
            if any(
                item.type == BlockType.HEADER
                and item.provenance.page_number == block.provenance.page_number
                for item in context
            ):
                score += 0.03
            if "," in block.text and "NGAY" in admin_patterns.strip_accents_upper(block.text):
                score += 0.07
            if block.provenance.provider_block_id:
                score += 0.02
            if block.confidence is not None:
                score = 0.75 * score + 0.25 * block.confidence
            if referenced:
                score = min(score, 0.6)
            elif block.provenance.page_number != 1:
                score = min(score, 0.64)
            candidates.append((block, match.iso, referenced, min(score, 0.98)))
    if not candidates:
        return None
    unreferenced = [item for item in candidates if not item[2]]
    if not unreferenced:
        return None
    page_one = [item for item in unreferenced if item[0].provenance.page_number == 1]
    usable = page_one or unreferenced
    ordered = sorted(usable, key=lambda item: item[3], reverse=True)
    if len({item[1] for item in unreferenced}) > 1:
        return None
    return ordered[0][1]


def _select_document_number(document: CanonicalDocument) -> str | None:
    blocks = [
        block
        for block in document.iter_blocks()
        if block.type not in {BlockType.HEADER, BlockType.FOOTER, BlockType.PAGE_NUMBER}
    ]
    page_heights = {page.page_number: page.height for page in document.pages}
    candidates: list[tuple[str, CanonicalBlock, float]] = []
    for block in blocks:
        line = block.text.split("\n", 1)[0].strip()
        match = _DOCUMENT_NUMBER.match(line) or admin_patterns.NUMBER_INLINE_RE.search(line)
        if match is None:
            continue
        value = admin_patterns.normalize_document_number(match.group(1).strip().rstrip(".,;"))
        score = 0.64
        if block.provenance.page_number == 1:
            score += 0.14
        score += _top_score(block, page_heights)
        score += 0.06 if block.reading_order <= 5 else 0.0
        score += 0.08 if "/" in value else 0.0
        score += 0.02 if block.provenance.provider_block_id else 0.0
        if block.confidence is not None:
            score = 0.75 * score + 0.25 * block.confidence
        candidates.append((value, block, min(score, 0.98)))
    if not candidates:
        return None
    best_by_value: dict[str, tuple[CanonicalBlock, float]] = {}
    for value, block, score in candidates:
        if score > best_by_value.get(value, (block, -1.0))[1]:
            best_by_value[value] = (block, score)
    ordered = sorted(
        ((value, block, score) for value, (block, score) in best_by_value.items()),
        key=lambda item: item[2],
        reverse=True,
    )
    if len(ordered) > 1:
        return None
    return ordered[0][0]


def extract_critical_fields(document: CanonicalDocument) -> dict[str, str | None]:
    """Extract benchmark critical fields from a canonical document."""
    blocks = document.iter_blocks()
    texts = [_clean(block.text) for block in blocks if block.text.strip()]
    joined = "\n".join(texts)

    fields: dict[str, str | None] = dict.fromkeys(CRITICAL_FIELD_NAMES)

    fields["document_number"] = _select_document_number(document)

    fields["issue_date"] = _select_issue_date(document)

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
