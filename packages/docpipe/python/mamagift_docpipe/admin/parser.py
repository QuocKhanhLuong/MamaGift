"""Vietnamese administrative structure parser.

Input is a `CanonicalDocument` produced by normalization; output is a new
`CanonicalDocument` with the same blocks plus:

- `Chương / Mục / Điều / Khoản / Điểm` and `Phụ lục` hierarchy nodes;
- list, table, title, signature and `Nơi nhận` block classification;
- critical fields with per-field confidence and page/block provenance;
- a structure quality report that marks untrustworthy fields for review.

The parser never edits its input and never invents a value: an unrecognised line
stays a paragraph, and a field that cannot be read is absent rather than guessed
(`docs/09_CODEX_EXECUTION.md` sections 5 and 8).
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dataclass_field
from typing import Any

from ..canonical import (
    BlockType,
    CanonicalBlock,
    CanonicalDocument,
    CanonicalPage,
    CanonicalTable,
    ExtractedField,
    Extractor,
    HierarchyKind,
    HierarchyNode,
    QualityReport,
    ReviewStatus,
)
from . import patterns as pat

ADMIN_PARSER_VERSION = "1.1"
EXTRACTOR_NAME = "admin-rule-v1"

# Fields the product treats as critical. A missing one is a review flag, not an error.
REQUIRED_FIELDS = ("document_number", "issuer", "issue_date", "title")

# Below this, a field is surfaced but explicitly marked for human review.
REVIEW_CONFIDENCE_THRESHOLD = 0.75

# Deadlines are only emitted when the expression is explicit; see `_extract_deadline`.
DEADLINE_MIN_CONFIDENCE = 0.7

# Blocks that carry running page furniture, never document structure.
FURNITURE_TYPES = frozenset({BlockType.HEADER, BlockType.FOOTER, BlockType.PAGE_NUMBER})


@dataclass
class _BlockUpdate:
    block_type: BlockType | None = None
    parent_id: str | None = None
    attributes: dict[str, Any] = dataclass_field(default_factory=dict)


@dataclass
class _StructureState:
    hierarchy: list[HierarchyNode] = dataclass_field(default_factory=list)
    updates: dict[str, _BlockUpdate] = dataclass_field(default_factory=dict)
    tables: list[CanonicalTable] = dataclass_field(default_factory=list)
    chapter_id: str | None = None
    section_id: str | None = None
    article_id: str | None = None
    clause_id: str | None = None
    point_id: str | None = None
    recipients_id: str | None = None
    counters: dict[str, int] = dataclass_field(default_factory=dict)

    def deepest_id(self) -> str | None:
        return (
            self.point_id or self.clause_id or self.article_id or self.section_id or self.chapter_id
        )

    def next_index(self, key: str) -> int:
        self.counters[key] = self.counters.get(key, 0) + 1
        return self.counters[key]


def _update(state: _StructureState, block_id: str) -> _BlockUpdate:
    return state.updates.setdefault(block_id, _BlockUpdate())


def _add_node(
    state: _StructureState,
    node_id: str,
    kind: HierarchyKind,
    label: str,
    text: str,
    parent_id: str | None,
    ordinal: int | None,
    block_id: str,
) -> HierarchyNode:
    node = HierarchyNode(
        id=node_id,
        kind=kind,
        label=label,
        text=text,
        parent_id=parent_id,
        source_block_ids=[block_id],
        ordinal=ordinal,
    )
    state.hierarchy.append(node)
    return node


def _attach(state: _StructureState, node_id: str, block_id: str) -> None:
    for node in state.hierarchy:
        if node.id == node_id:
            if block_id not in node.source_block_ids:
                node.source_block_ids.append(block_id)
            return


# --------------------------------------------------------------------- structure


def _flush_table(
    state: _StructureState,
    rows: list[tuple[str, list[str]]],
    page_number: int,
) -> None:
    """Turn a run of pipe-delimited row blocks into one canonical table."""
    if not rows:
        return

    if len(rows) < 2:
        # A single delimited line is more likely a sentence than a table.
        rows.clear()
        return

    table_index = state.next_index("table")
    table_id = f"t_admin_{page_number}_{table_index:04d}"
    n_cols = max(len(cells) for _, cells in rows)
    grid = [cells + [""] * (n_cols - len(cells)) for _, cells in rows]

    first_block_id = rows[0][0]
    owner_id = state.deepest_id()
    for row_index, (block_id, _) in enumerate(rows):
        update = _update(state, block_id)
        update.block_type = BlockType.TABLE if row_index == 0 else BlockType.TABLE_CELL
        if owner_id is not None:
            update.parent_id = owner_id
            _attach(state, owner_id, block_id)
        update.attributes.update(
            {
                "table_id": table_id,
                "table_row_index": row_index,
                "classified_by": "admin_parser_table",
            }
        )

    state.tables.append(
        CanonicalTable(
            id=table_id,
            page_number=page_number,
            block_id=first_block_id,
            n_rows=len(grid),
            n_cols=n_cols,
            cells=grid,
            caption=None,
        )
    )
    rows.clear()


def _classify_structure(document: CanonicalDocument) -> _StructureState:
    state = _StructureState()
    pending_rows: list[tuple[str, list[str]]] = []
    pending_page = 1

    for page in document.pages:
        for block in sorted(page.blocks, key=lambda item: item.reading_order):
            if block.type in FURNITURE_TYPES or not block.text:
                _flush_table(state, pending_rows, pending_page)
                continue

            cells = pat.table_row_cells(block.text)
            if cells is not None:
                if pending_rows and pending_page != page.page_number:
                    _flush_table(state, pending_rows, pending_page)
                pending_page = page.page_number
                pending_rows.append((block.id, cells))
                continue
            _flush_table(state, pending_rows, pending_page)

            _classify_block(state, block)

        _flush_table(state, pending_rows, pending_page)

    return state


def _classify_block(state: _StructureState, block: CanonicalBlock) -> None:
    line = pat.first_line(block.text)
    update = _update(state, block.id)

    chapter = pat.CHAPTER_RE.match(line)
    if chapter is not None:
        label_value, rest = chapter.group(1), chapter.group(2).strip()
        node_id = f"h_chapter_{state.next_index('chapter')}"
        _add_node(
            state,
            node_id,
            HierarchyKind.CHAPTER,
            f"Chương {label_value}",
            rest,
            None,
            pat.ordinal_of(label_value),
            block.id,
        )
        state.chapter_id = node_id
        state.section_id = state.article_id = state.clause_id = state.point_id = None
        update.block_type = BlockType.HEADING
        update.parent_id = node_id
        return

    section = pat.SECTION_RE.match(line)
    if section is not None:
        label_value, rest = section.group(1), section.group(2).strip()
        node_id = f"h_section_{state.next_index('section')}"
        _add_node(
            state,
            node_id,
            HierarchyKind.SECTION,
            f"Mục {label_value}",
            rest,
            state.chapter_id,
            pat.ordinal_of(label_value),
            block.id,
        )
        state.section_id = node_id
        state.article_id = state.clause_id = state.point_id = None
        update.block_type = BlockType.HEADING
        update.parent_id = node_id
        return

    article = pat.ARTICLE_RE.match(line)
    if article is not None:
        label_value, rest = article.group(1), article.group(2).strip()
        node_id = f"h_article_{label_value}"
        while any(node.id == node_id for node in state.hierarchy):
            node_id = f"{node_id}_{state.next_index('article_dup')}"
        _add_node(
            state,
            node_id,
            HierarchyKind.ARTICLE,
            f"Điều {label_value}",
            rest,
            state.section_id or state.chapter_id,
            pat.ordinal_of(label_value),
            block.id,
        )
        state.article_id = node_id
        state.clause_id = state.point_id = None
        update.block_type = BlockType.HEADING
        update.parent_id = node_id
        return

    appendix = pat.APPENDIX_RE.match(line)
    if appendix is not None:
        label_value = (appendix.group(1) or "").strip()
        rest = appendix.group(2).strip()
        index = state.next_index("appendix")
        node_id = f"h_appendix_{index}"
        label = f"Phụ lục {label_value}".strip()
        _add_node(
            state,
            node_id,
            HierarchyKind.APPENDIX,
            label,
            rest,
            None,
            pat.ordinal_of(label_value) if label_value else index,
            block.id,
        )
        state.chapter_id = node_id
        state.section_id = state.article_id = state.clause_id = state.point_id = None
        state.recipients_id = None
        update.block_type = BlockType.HEADING
        update.parent_id = node_id
        return

    recipients = pat.RECIPIENTS_RE.match(line)
    if recipients is not None:
        node_id = f"h_recipients_{state.next_index('recipients')}"
        _add_node(
            state,
            node_id,
            HierarchyKind.CUSTOM_HEADING,
            "Nơi nhận",
            recipients.group(1).strip(),
            None,
            None,
            block.id,
        )
        state.recipients_id = node_id
        state.article_id = state.clause_id = state.point_id = None
        update.block_type = BlockType.HEADING
        update.parent_id = node_id
        update.attributes["admin_role"] = "recipients_heading"
        return

    if state.recipients_id is not None and pat.BULLET_RE.match(line):
        update.block_type = BlockType.LIST_ITEM
        update.parent_id = state.recipients_id
        update.attributes["admin_role"] = "recipient"
        _attach(state, state.recipients_id, block.id)
        return

    normalized_line = pat.strip_accents_upper(line)
    if any(
        normalized_line.startswith(pat.strip_accents_upper(marker))
        for marker in pat.SIGNER_ROLE_MARKERS
    ):
        # The signature block closes the document body: nothing after it belongs to
        # an article, an appendix or the recipients list.
        state.chapter_id = None
        state.section_id = state.article_id = state.clause_id = state.point_id = None
        state.recipients_id = None
        update.attributes["admin_role"] = "signature_role"
        return

    clause = pat.CLAUSE_LABELLED_RE.match(line) or pat.CLAUSE_NUMERIC_RE.match(line)
    if clause is not None:
        label_value, rest = clause.group(1), clause.group(2).strip()
        if state.article_id is not None:
            node_id = f"h_clause_{state.article_id.removeprefix('h_article_')}_{label_value}"
            while any(node.id == node_id for node in state.hierarchy):
                node_id = f"{node_id}_{state.next_index('clause_dup')}"
            _add_node(
                state,
                node_id,
                HierarchyKind.CLAUSE,
                f"Khoản {label_value}",
                rest,
                state.article_id,
                pat.ordinal_of(label_value),
                block.id,
            )
            state.clause_id = node_id
            state.point_id = None
            update.block_type = BlockType.LIST_ITEM
            update.parent_id = node_id
            update.attributes["admin_role"] = "clause"
            return

        update.block_type = BlockType.LIST_ITEM
        update.parent_id = state.deepest_id()
        update.attributes["admin_role"] = "ordered_list_item"
        return

    point = pat.POINT_LABELLED_RE.match(line) or pat.POINT_LETTER_RE.match(line)
    if point is not None:
        label_value, rest = point.group(1), point.group(2).strip()
        if state.clause_id is not None:
            node_id = f"h_point_{state.clause_id.removeprefix('h_clause_')}_{label_value}"
            while any(node.id == node_id for node in state.hierarchy):
                node_id = f"{node_id}_{state.next_index('point_dup')}"
            _add_node(
                state,
                node_id,
                HierarchyKind.POINT,
                f"Điểm {label_value}",
                rest,
                state.clause_id,
                None,
                block.id,
            )
            state.point_id = node_id
            update.block_type = BlockType.LIST_ITEM
            update.parent_id = node_id
            update.attributes["admin_role"] = "point"
            return

        update.block_type = BlockType.LIST_ITEM
        update.parent_id = state.deepest_id()
        update.attributes["admin_role"] = "lettered_list_item"
        return

    if pat.BULLET_RE.match(line):
        update.block_type = BlockType.LIST_ITEM
        update.parent_id = state.deepest_id()
        update.attributes["admin_role"] = "bullet_list_item"
        return

    if pat.SUBJECT_RE.match(line):
        update.block_type = BlockType.TITLE
        update.attributes["admin_role"] = "subject"
        return

    if pat.compact_matching_key(line) in {pat.compact_matching_key(k) for k in pat.TYPE_HEADINGS}:
        update.block_type = BlockType.TITLE
        update.attributes["admin_role"] = "document_type_heading"
        return

    parent_id = state.deepest_id()
    if parent_id is not None:
        update.parent_id = parent_id
        _attach(state, parent_id, block.id)
    if block.type in (BlockType.UNKNOWN,):
        update.block_type = BlockType.PARAGRAPH


# ------------------------------------------------------------------------ fields


@dataclass
class _FieldCandidate:
    name: str
    raw_value: str
    normalized_value: str
    value_type: str
    confidence: float
    block_ids: list[str]
    page_numbers: list[int]


@dataclass(frozen=True)
class _DateEvidence:
    block: CanonicalBlock
    raw: str
    normalized_value: str
    referenced: bool
    deadline: bool
    score: float


def _top_score(block: CanonicalBlock, page_heights: dict[int, float]) -> float:
    """Score only reliable layout evidence; absent boxes do not become guesses."""
    if block.bbox is None:
        return 0.0
    height = page_heights.get(block.provenance.page_number, 842.0)
    ratio = block.bbox.y0 / height
    if ratio <= 0.25:
        return 0.16
    if ratio <= 0.40:
        return 0.09
    return 0.0


def _nearby_score(block: CanonicalBlock, context_blocks: list[CanonicalBlock]) -> float:
    score = 0.0
    for context in context_blocks:
        if context.provenance.page_number != block.provenance.page_number:
            continue
        distance = abs(context.reading_order - block.reading_order)
        if distance <= 1:
            score = max(score, 0.12)
        elif distance <= 3:
            score = max(score, 0.08)
        elif distance <= 6:
            score = max(score, 0.04)
    return score


def _context_blocks(blocks: list[CanonicalBlock]) -> list[CanonicalBlock]:
    result: list[CanonicalBlock] = []
    for block in blocks:
        line = pat.first_line(block.text)
        normalized = pat.strip_accents_upper(line)
        compact = pat.compact_matching_key(line)
        if block.type == BlockType.HEADER:
            result.append(block)
            continue
        if pat.NUMBER_RE.match(line) or pat.NUMBER_INLINE_RE.search(line):
            result.append(block)
            continue
        if any(
            normalized.startswith(pat.strip_accents_upper(prefix))
            or compact.startswith(pat.compact_matching_key(prefix))
            for prefix in pat.ISSUER_PREFIXES
        ):
            result.append(block)
            continue
        if pat.SUBJECT_RE.match(line) or compact in {
            pat.compact_matching_key(heading) for heading in pat.TYPE_HEADINGS
        }:
            result.append(block)
    return result


def _date_marker_kind(text: str, match: pat.DateMatch) -> tuple[bool, bool]:
    before = text[max(0, match.start - 80) : match.start]
    after = text[match.end : match.end + 48]
    deadline = (
        pat.marker_position(before, pat.DEADLINE_MARKERS + pat.DEADLINE_DATE_PREFIXES) is not None
    )
    referenced = pat.marker_position(before, pat.REFERENCE_DATE_MARKERS) is not None
    referenced = referenced or pat.marker_position(after, ("có hiệu lực", "của")) is not None
    return referenced, deadline


def _make_field(candidate: _FieldCandidate, index: int) -> ExtractedField:
    needs_review = candidate.confidence < REVIEW_CONFIDENCE_THRESHOLD
    return ExtractedField(
        id=f"field_{candidate.name}_{index}",
        name=candidate.name,
        raw_value=candidate.raw_value,
        normalized_value=candidate.normalized_value,
        value_type=candidate.value_type,
        confidence=round(candidate.confidence, 3),
        review_status=ReviewStatus.NEEDS_REVIEW if needs_review else ReviewStatus.UNREVIEWED,
        source_block_ids=candidate.block_ids,
        source_page_numbers=candidate.page_numbers,
        extractor=Extractor(name=EXTRACTOR_NAME, version=ADMIN_PARSER_VERSION),
    )


def _body_blocks(document: CanonicalDocument) -> list[CanonicalBlock]:
    return [block for block in document.iter_blocks() if block.type not in FURNITURE_TYPES]


def _extract_number(
    blocks: list[CanonicalBlock],
    page_heights: dict[int, float] | None = None,
) -> _FieldCandidate | None:
    page_heights = page_heights or {}
    candidates: list[tuple[_FieldCandidate, float]] = []
    for block in blocks:
        line = pat.first_line(block.text)
        match = pat.NUMBER_RE.match(line) or pat.NUMBER_INLINE_RE.search(line)
        if match is None:
            continue
        value = pat.normalize_document_number(match.group(1).strip().rstrip(".,;"))
        if not value:
            continue
        candidate = _FieldCandidate(
            name="document_number",
            raw_value=line,
            normalized_value=value,
            value_type="string",
            confidence=0.0,
            block_ids=[block.id],
            page_numbers=[block.provenance.page_number],
        )
        score = 0.64
        if block.provenance.page_number == 1:
            score += 0.14
        score += _top_score(block, page_heights)
        score += 0.06 if block.reading_order <= 5 else 0.0
        score += 0.08 if "/" in value else 0.0
        score += 0.02 if block.provenance.provider_block_id else 0.0
        if block.confidence is not None:
            score = 0.75 * score + 0.25 * block.confidence
        candidates.append((candidate, min(score, 0.98)))

    if not candidates:
        return None
    by_value: dict[str, tuple[_FieldCandidate, float]] = {}
    for candidate, score in candidates:
        if score > by_value.get(candidate.normalized_value, (candidate, -1.0))[1]:
            by_value[candidate.normalized_value] = (candidate, score)
    ordered = sorted(by_value.values(), key=lambda item: item[1], reverse=True)
    if len(ordered) > 1:
        if ordered[0][1] - ordered[1][1] < 0.08:
            selected, score = ordered[0]
            selected.confidence = min(score, 0.6)
            return selected
        selected, score = ordered[0]
        selected.confidence = min(score, 0.65)
        return selected
    selected, score = ordered[0]
    selected.confidence = score
    return selected


def _extract_document_type(
    blocks: list[CanonicalBlock],
    number: _FieldCandidate | None,
) -> _FieldCandidate | None:
    for block in blocks[:25]:
        line = pat.first_line(block.text)
        normalized = pat.compact_matching_key(line)
        for heading, type_name in pat.TYPE_HEADINGS.items():
            if normalized == pat.compact_matching_key(heading):
                return _FieldCandidate(
                    name="document_type",
                    raw_value=line,
                    normalized_value=type_name,
                    value_type="string",
                    confidence=0.9,
                    block_ids=[block.id],
                    page_numbers=[block.provenance.page_number],
                )

    if number is not None and "/" in number.normalized_value:
        tail = number.normalized_value.split("/", 1)[1]
        code = tail.split("-", 1)[0].strip()
        for known_code, type_name in pat.TYPE_CODES.items():
            if code.upper() == known_code.upper():
                return _FieldCandidate(
                    name="document_type",
                    raw_value=number.normalized_value,
                    normalized_value=type_name,
                    value_type="string",
                    confidence=0.8,
                    block_ids=list(number.block_ids),
                    page_numbers=list(number.page_numbers),
                )
    return None


def _extract_issuer(blocks: list[CanonicalBlock]) -> _FieldCandidate | None:
    for block in blocks[:15]:
        line = pat.first_line(block.text)
        normalized = pat.strip_accents_upper(line)
        compact = pat.compact_matching_key(line)
        if not any(
            normalized.startswith(pat.strip_accents_upper(prefix))
            or compact.startswith(pat.compact_matching_key(prefix))
            for prefix in pat.ISSUER_PREFIXES
        ):
            continue
        if pat.NUMBER_RE.match(line):
            continue
        confidence = 0.85 if pat.is_mostly_upper(line) else 0.65
        return _FieldCandidate(
            name="issuer",
            raw_value=line,
            normalized_value=line.rstrip(":.,"),
            value_type="string",
            confidence=confidence,
            block_ids=[block.id],
            page_numbers=[block.provenance.page_number],
        )
    return None


def _extract_issue_date(
    blocks: list[CanonicalBlock],
    context_blocks: list[CanonicalBlock] | None = None,
    page_heights: dict[int, float] | None = None,
    date_blocks: list[CanonicalBlock] | None = None,
) -> _FieldCandidate | None:
    context_blocks = context_blocks or []
    page_heights = page_heights or {}
    evidence: list[_DateEvidence] = []
    for block in date_blocks or blocks:
        for match in pat.parse_vietnamese_dates(block.text):
            referenced, deadline = _date_marker_kind(block.text, match)
            if deadline:
                continue
            score = 0.54
            if block.provenance.page_number == 1:
                score += 0.14
            if block.type == BlockType.HEADER:
                score += 0.02
            score += _top_score(block, page_heights)
            score += _nearby_score(block, context_blocks)
            if any(
                item.provenance.page_number == block.provenance.page_number
                and item.type == BlockType.HEADER
                for item in context_blocks
            ):
                score += 0.03
            if "," in block.text and "NGAY" in pat.strip_accents_upper(block.text):
                score += 0.07
            if block.provenance.provider_block_id:
                score += 0.02
            if block.confidence is not None:
                score = 0.75 * score + 0.25 * block.confidence
            if referenced:
                score = min(score, 0.6)
            elif block.provenance.page_number != 1:
                # A later-page date may be useful evidence for a reviewer, but it
                # cannot become an unreviewed issue date without page-one heading
                # support.
                score = min(score, 0.64)
            evidence.append(
                _DateEvidence(block, match.raw, match.iso, referenced, deadline, min(score, 0.98))
            )

    if not evidence:
        return None
    unreferenced = [item for item in evidence if not item.referenced]
    # A reference date is useful review context, but it is not evidence that the
    # current document was issued on that date.  Do not surface it as issue_date
    # when no unqualified header candidate exists.
    if not unreferenced:
        return None
    distinct_dates = {item.normalized_value for item in unreferenced}
    ordered = sorted(unreferenced, key=lambda item: item.score, reverse=True)
    if len(distinct_dates) > 1:
        if len(ordered) > 1 and ordered[0].score - ordered[1].score < 0.05:
            selected = ordered[0]
            confidence = min(selected.score, 0.6)
        else:
            selected = ordered[0]
            confidence = min(selected.score, 0.65)
    else:
        selected = ordered[0]
        confidence = selected.score
    return _FieldCandidate(
        name="issue_date",
        raw_value=selected.raw,
        normalized_value=selected.normalized_value,
        value_type="date",
        confidence=confidence,
        block_ids=[selected.block.id],
        page_numbers=[selected.block.provenance.page_number],
    )


def _extract_title(blocks: list[CanonicalBlock]) -> _FieldCandidate | None:
    for block in blocks[:30]:
        line = pat.first_line(block.text)
        match = pat.SUBJECT_RE.match(line)
        if match is not None:
            value = match.group(1).strip().rstrip(".")
            if value:
                return _FieldCandidate(
                    name="title",
                    raw_value=line,
                    normalized_value=value,
                    value_type="string",
                    confidence=0.9,
                    block_ids=[block.id],
                    page_numbers=[block.provenance.page_number],
                )

    # Fallback: the uppercase line right after a spelled-out document-type heading.
    type_headings = {pat.compact_matching_key(key) for key in pat.TYPE_HEADINGS}
    for index, block in enumerate(blocks[:30]):
        if pat.compact_matching_key(pat.first_line(block.text)) not in type_headings:
            continue
        for follower in blocks[index + 1 : index + 4]:
            line = pat.first_line(follower.text)
            if not line or pat.NUMBER_RE.match(line):
                continue
            return _FieldCandidate(
                name="title",
                raw_value=line,
                normalized_value=line.rstrip("."),
                value_type="string",
                confidence=0.6,
                block_ids=[follower.id],
                page_numbers=[follower.provenance.page_number],
            )
    return None


def _extract_signer(blocks: list[CanonicalBlock]) -> tuple[_FieldCandidate | None, str | None]:
    """Return the signer field and the block id to mark as the signature block."""
    markers = [pat.strip_accents_upper(marker) for marker in pat.SIGNER_ROLE_MARKERS]
    tail = blocks[-15:]
    role_seen = False
    for index, block in enumerate(tail):
        line = pat.first_line(block.text)
        normalized = pat.strip_accents_upper(line)
        if any(normalized.startswith(marker) for marker in markers):
            role_seen = True
            for follower in tail[index + 1 :]:
                candidate_line = pat.first_line(follower.text)
                if not candidate_line:
                    continue
                if any(
                    pat.strip_accents_upper(candidate_line).startswith(marker) for marker in markers
                ):
                    continue
                if pat.looks_like_person_name(candidate_line):
                    return (
                        _FieldCandidate(
                            name="signer",
                            raw_value=candidate_line,
                            normalized_value=candidate_line.strip(),
                            value_type="string",
                            confidence=0.8,
                            block_ids=[follower.id],
                            page_numbers=[follower.provenance.page_number],
                        ),
                        follower.id,
                    )
                break
    if role_seen:
        return None, None
    return None, None


def _extract_deadline(blocks: list[CanonicalBlock]) -> _FieldCandidate | None:
    """Only explicit, dated deadline expressions are returned."""
    for block in blocks:
        text = block.text
        for match in pat.parse_vietnamese_dates(text):
            marker = pat.marker_position(
                text[: match.start], pat.DEADLINE_MARKERS + pat.DEADLINE_DATE_PREFIXES
            )
            if marker is None:
                continue
            marker_start, _ = marker
            marker_text = text[marker_start : match.end]
            confidence = 0.9 if "ngày" in marker_text.lower() else 0.75
            if confidence < DEADLINE_MIN_CONFIDENCE:
                continue
            return _FieldCandidate(
                name="deadline",
                raw_value=marker_text,
                normalized_value=match.iso,
                value_type="date",
                confidence=confidence,
                block_ids=[block.id],
                page_numbers=[block.provenance.page_number],
            )
    return None


def _extract_fields(
    document: CanonicalDocument,
) -> tuple[list[ExtractedField], str | None]:
    blocks = _body_blocks(document)
    context_blocks = _context_blocks(
        [
            block
            for block in document.iter_blocks()
            if block.type not in {BlockType.FOOTER, BlockType.PAGE_NUMBER}
        ]
    )
    page_heights = {page.page_number: page.height for page in document.pages}
    candidates: list[_FieldCandidate] = []

    number = _extract_number(blocks, page_heights)
    if number is not None:
        candidates.append(number)

    document_type = _extract_document_type(blocks, number)
    if document_type is not None:
        candidates.append(document_type)

    issuer = _extract_issuer(blocks)
    if issuer is not None:
        candidates.append(issuer)

    date_blocks = [
        block
        for block in document.iter_blocks()
        if block.type not in {BlockType.FOOTER, BlockType.PAGE_NUMBER}
    ]
    issue_date = _extract_issue_date(blocks, context_blocks, page_heights, date_blocks)
    if issue_date is not None:
        candidates.append(issue_date)

    title = _extract_title(blocks)
    if title is not None:
        candidates.append(title)

    signer, signature_block_id = _extract_signer(blocks)
    if signer is not None:
        candidates.append(signer)

    deadline = _extract_deadline(blocks)
    if deadline is not None:
        candidates.append(deadline)

    fields = [_make_field(candidate, index + 1) for index, candidate in enumerate(candidates)]
    return fields, signature_block_id


# ----------------------------------------------------------------------- assembly


def _quality(
    document: CanonicalDocument,
    fields: list[ExtractedField],
    hierarchy: list[HierarchyNode],
    list_item_count: int,
) -> QualityReport:
    by_name = {field.name: field for field in fields}
    warnings: list[str] = []

    for name in REQUIRED_FIELDS:
        found = by_name.get(name)
        if found is None:
            warnings.append(f"{name}: not found")
        elif found.review_status == ReviewStatus.NEEDS_REVIEW:
            warnings.append(f"{name}: low confidence ({found.confidence})")

    coverage = sum(1 for name in REQUIRED_FIELDS if name in by_name) / len(REQUIRED_FIELDS)
    if hierarchy:
        structure_signal = 1.0
    elif list_item_count:
        structure_signal = 0.7
    elif any(block.text for block in document.iter_blocks()):
        structure_signal = 0.5
    else:
        structure_signal = 0.0

    previous = document.quality_report
    return QualityReport(
        route=previous.route,
        route_confidence=previous.route_confidence,
        text_quality_score=previous.text_quality_score,
        structure_quality_score=round(0.6 * coverage + 0.4 * structure_signal, 3),
        critical_field_warnings=warnings,
        warnings=previous.warnings,
        requires_user_review=bool(warnings) or previous.requires_user_review,
    )


def parse_admin_document(document: CanonicalDocument) -> CanonicalDocument:
    """Return a new `CanonicalDocument` enriched with administrative structure."""
    state = _classify_structure(document)
    fields, signature_block_id = _extract_fields(document)

    if signature_block_id is not None:
        update = _update(state, signature_block_id)
        update.block_type = BlockType.SIGNATURE
        update.attributes["admin_role"] = "signer_name"

    list_item_count = 0
    pages: list[CanonicalPage] = []
    for page in document.pages:
        blocks: list[CanonicalBlock] = []
        for block in page.blocks:
            block_update = state.updates.get(block.id)
            if block_update is None:
                blocks.append(block)
                continue

            attributes = dict(block.attributes)
            attributes.update(block_update.attributes)
            new_type = block_update.block_type or block.type
            if new_type == BlockType.LIST_ITEM:
                list_item_count += 1
            blocks.append(
                block.model_copy(
                    update={
                        "type": new_type,
                        "parent_id": block_update.parent_id or block.parent_id,
                        "attributes": attributes,
                    }
                )
            )
        pages.append(
            CanonicalPage(
                page_number=page.page_number,
                width=page.width,
                height=page.height,
                rotation=page.rotation,
                blocks=blocks,
            )
        )

    metadata = dict(document.metadata)
    metadata["admin_parser"] = {
        "version": ADMIN_PARSER_VERSION,
        "hierarchy_nodes": len(state.hierarchy),
        "list_items": list_item_count,
        "tables": len(document.tables) + len(state.tables),
    }

    # Constructed rather than copied so the canonical validators re-run: block
    # parents now reference hierarchy nodes, and that link must hold.
    return CanonicalDocument(
        schema_version=document.schema_version,
        document_id=document.document_id,
        parser_run=document.parser_run,
        metadata=metadata,
        pages=pages,
        hierarchy=state.hierarchy,
        tables=[*document.tables, *state.tables],
        extracted_fields=fields,
        quality_report=_quality(document, fields, state.hierarchy, list_item_count),
    )
