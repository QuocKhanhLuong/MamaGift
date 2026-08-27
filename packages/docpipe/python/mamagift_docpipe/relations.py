"""Deterministic relation extraction for cross-document memory.

Relations are extracted deterministically from canonical block text by regex. There is NO code
path in which a language model creates a relation. Every relation carries the provenance of the
span it came from. A relation naming a document the archive does not hold is recorded with
`target_document_id=None` and a normalised `target_document_number` — a `documents` row is
NEVER created to satisfy a relation.

Cue Precedence:
When several cues touch the same target in one block, the winning relation type is chosen
according to the following strict precedence:
    SUPERSEDES > REPLACES > AMENDS > REFERENCES

Confidence Scoring Table:
+-------------------+----------------------------+-----------------------+------------+
| Cue Class         | Vietnamese Cues            | Target Well-Formed    | Confidence |
+-------------------+----------------------------+-----------------------+------------+
| SUPERSEDES        | thay thế, thay thế cho     | Yes                   | 0.90       |
| REPLACES          | bãi bỏ, hủy bỏ, ...        | Yes                   | 0.90       |
| AMENDS            | sửa đổi, bổ sung, ...      | Yes                   | 0.90       |
| REFERENCES        | căn cứ, theo, tại, ...     | Yes                   | 0.60       |
| Explicit (any)    | (supersedes/replaces/...)  | Irregular / Malformed | 0.70       |
| Reference (any)   | (references)               | Irregular / Malformed | 0.40       |
+-------------------+----------------------------+-----------------------+------------+
Confidence is never 1.0: regex extraction is not mathematical certainty.
"""

from __future__ import annotations

import re
import unicodedata
from typing import NamedTuple

from pydantic import BaseModel, ConfigDict, Field

from .canonical import CanonicalDocument

RELATION_WINDOW_CHARS: int = 120

PRECEDENCE_RANK: dict[str, int] = {
    "supersedes": 4,
    "replaces": 3,
    "amends": 2,
    "references": 1,
}

# Vietnamese cue regex patterns ordered by specificity within each class
_CUE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "supersedes",
        re.compile(
            r"\b(?:thay\s+thế\s+cho|thay\s+thế)\b",
            re.IGNORECASE | re.UNICODE,
        ),
    ),
    (
        "replaces",
        re.compile(
            r"\b(?:chấm\s+dứt\s+hiệu\s+lực|bãi\s+bỏ|hủy\s+bỏ)\b",
            re.IGNORECASE | re.UNICODE,
        ),
    ),
    (
        "amends",
        re.compile(
            r"\b(?:sửa\s+đổi[,\s]+bổ\s+sung|sửa\s+đổi\s+và\s+bổ\s+sung|sửa\s+đổi|bổ\s+sung)\b",
            re.IGNORECASE | re.UNICODE,
        ),
    ),
    (
        "references",
        re.compile(
            r"\b(?:quy\s+định\s+tại|căn\s+cứ|theo|tại)\b",
            re.IGNORECASE | re.UNICODE,
        ),
    ),
]

_DOC_NUMBER_RE = re.compile(
    r"\b(\d{1,8}(?:\s*/\s*[A-Za-z0-9_.\-À-ỹđĐ]+)+)\b",
    re.UNICODE,
)

_SLASH_DATE_RE = re.compile(
    r"^\d{1,2}/\d{1,2}/\d{4}$",
)

_WELL_FORMED_RE = re.compile(
    r"^\d{1,8}/(?:\d{4}/)?[A-ZĐa-z0-9_.\-]+$",
    re.UNICODE,
)


def normalize_identifier(value: str) -> str:
    """Normalise a Vietnamese administrative document number for exact matching.

    NFC-normalises, trims, removes whitespace around `/` and `-`, collapses remaining runs of
    whitespace, and uppercases. `" 19 / 2026 / TT-BGDĐT "` becomes `"19/2026/TT-BGDĐT"`.
    """
    if not isinstance(value, str):
        raise TypeError("identifier must be a string")
    text = unicodedata.normalize("NFC", value).strip()
    out: list[str] = []
    for index, char in enumerate(text):
        if char.isspace():
            prev = next((c for c in reversed(out) if not c.isspace()), "")
            nxt = ""
            for later in text[index + 1 :]:
                if not later.isspace():
                    nxt = later
                    break
            if prev in {"/", "-"} or nxt in {"/", "-"}:
                continue
            if out and out[-1].isspace():
                continue
            out.append(" ")
            continue
        out.append(char)
    return "".join(out).strip().upper()


class ExtractedRelation(BaseModel):
    """A deterministically extracted cross-document relationship."""

    model_config = ConfigDict(extra="forbid")

    relation_type: str
    target_document_number: str | None = None
    target_raw_text: str
    source_block_ids: list[str] = Field(min_length=1)
    page_numbers: list[int] = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)


class _CandidateMatch(NamedTuple):
    relation_type: str
    target_document_number: str
    target_raw_text: str
    cue_start: int
    doc_start: int
    confidence: float
    rank: int


def _compute_confidence(relation_type: str, normalized_target: str) -> float:
    is_well_formed = bool(
        _WELL_FORMED_RE.match(normalized_target) and any(c.isalpha() for c in normalized_target)
    )
    if relation_type in {"supersedes", "replaces", "amends"}:
        return 0.9 if is_well_formed else 0.7
    return 0.6 if is_well_formed else 0.4


def _extract_block_candidates(block_text: str) -> list[_CandidateMatch]:
    if not block_text or not block_text.strip():
        return []

    norm_text = unicodedata.normalize("NFC", block_text)

    # 1. Find all cues
    cues: list[tuple[str, int, int]] = []
    for rel_type, pattern in _CUE_PATTERNS:
        for match in pattern.finditer(norm_text):
            cues.append((rel_type, match.start(), match.end()))

    if not cues:
        return []

    # 2. Find all document number targets (excluding dates like DD/MM/YYYY and pure numbers)
    targets: list[tuple[str, int, int, str]] = []
    for match in _DOC_NUMBER_RE.finditer(norm_text):
        raw_val = match.group(1).rstrip(".,;:-/ ")
        if not raw_val:
            continue
        norm_val = normalize_identifier(raw_val)
        if not norm_val or not any(c.isalpha() for c in norm_val):
            # Must contain at least one letter (not a pure date like 03/03/2026 or ratio 1/2)
            continue
        if _SLASH_DATE_RE.match(norm_val):
            continue
        start = match.start(1)
        end = start + len(raw_val)
        targets.append((raw_val, start, end, norm_val))

    if not targets:
        return []

    # 3. Match cues with targets within window
    candidates_by_target: dict[str, list[_CandidateMatch]] = {}
    for rel_type, cue_start, cue_end in cues:
        for _raw_val, doc_start, doc_end, norm_val in targets:
            if cue_end <= doc_start and (doc_start - cue_end) <= RELATION_WINDOW_CHARS:
                verbatim_raw = block_text[cue_start:doc_end]
                conf = _compute_confidence(rel_type, norm_val)
                rank = PRECEDENCE_RANK[rel_type]
                cand = _CandidateMatch(
                    relation_type=rel_type,
                    target_document_number=norm_val,
                    target_raw_text=verbatim_raw,
                    cue_start=cue_start,
                    doc_start=doc_start,
                    confidence=conf,
                    rank=rank,
                )
                candidates_by_target.setdefault(norm_val, []).append(cand)

    # 4. Resolve precedence for each target within this block
    winning_candidates: list[_CandidateMatch] = []
    for cands in candidates_by_target.values():
        # Sort by: 1) rank descending, 2) distance ascending, 3) cue_start ascending
        cands.sort(key=lambda c: (-c.rank, c.doc_start - c.cue_start, c.cue_start))
        winning_candidates.append(cands[0])

    return winning_candidates


def extract_relations(document: CanonicalDocument) -> list[ExtractedRelation]:
    """Extract cross-document relations deterministically from canonical block text.

    - Scans canonical blocks in reading order.
    - Matches Vietnamese cues to document numbers within a bounded character window.
    - Applies precedence when multiple cues touch the same target within a block.
    - Drops self-references to the document's own document number.
    - Deduplicates identical (relation_type, target_document_number) pairs across the document,
      merging source block IDs and page numbers.
    """
    # Identify document's own document number to guard against self-references
    own_numbers: set[str] = set()
    for field in document.extracted_fields:
        if field.name == "document_number":
            val = field.normalized_value or field.raw_value
            if val:
                own_numbers.add(normalize_identifier(val))
    meta_num = document.metadata.get("document_number")
    if meta_num and isinstance(meta_num, str):
        own_numbers.add(normalize_identifier(meta_num))

    # Collect per-block candidate relations
    raw_relations: list[ExtractedRelation] = []
    for block in document.iter_blocks():
        if not block.text:
            continue
        page_num = block.provenance.page_number
        candidates = _extract_block_candidates(block.text)
        for cand in candidates:
            # Self-reference guard
            if cand.target_document_number in own_numbers:
                continue

            raw_relations.append(
                ExtractedRelation(
                    relation_type=cand.relation_type,
                    target_document_number=cand.target_document_number,
                    target_raw_text=cand.target_raw_text,
                    source_block_ids=[block.id],
                    page_numbers=[page_num],
                    confidence=cand.confidence,
                )
            )

    # Deduplicate across the whole document by (relation_type, target_document_number)
    grouped: dict[tuple[str, str | None], list[ExtractedRelation]] = {}
    for rel in raw_relations:
        key = (rel.relation_type, rel.target_document_number)
        grouped.setdefault(key, []).append(rel)

    deduplicated: list[ExtractedRelation] = []
    for (rel_type, target_num), rel_list in grouped.items():
        all_block_ids: set[str] = set()
        all_pages: set[int] = set()
        max_confidence = 0.0
        first_raw_text = rel_list[0].target_raw_text

        for rel in rel_list:
            all_block_ids.update(rel.source_block_ids)
            all_pages.update(rel.page_numbers)
            if rel.confidence > max_confidence:
                max_confidence = rel.confidence

        deduplicated.append(
            ExtractedRelation(
                relation_type=rel_type,
                target_document_number=target_num,
                target_raw_text=first_raw_text,
                source_block_ids=sorted(all_block_ids),
                page_numbers=sorted(all_pages),
                confidence=max_confidence,
            )
        )

    return deduplicated
