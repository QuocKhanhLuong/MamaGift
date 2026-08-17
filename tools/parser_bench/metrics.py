"""Benchmark quality metrics.

Deliberately more than CER. A parser that transcribes characters well but corrupts
reading order, drops the Article hierarchy, leaks running headers into the body, or
loses page provenance is not acceptable for this product, and the metric set has to
be able to say so (`docs/03_DOCUMENT_PIPELINE.md` section 5).

Every metric returns a score in [0, 1] where higher is better, plus an `available`
flag. When the required ground-truth layer is missing the metric reports unavailable
and is excluded from scoring. Missing labels never become zeros.
"""

from __future__ import annotations

import re
import unicodedata

from pydantic import BaseModel, ConfigDict, Field

from mamagift_docpipe.canonical import BlockType, CanonicalDocument

from .manifest import GroundTruth

METRICS_VERSION = "1.0"

_WHITESPACE = re.compile(r"\s+")

BODY_BLOCK_TYPES = frozenset(
    {
        BlockType.TITLE,
        BlockType.HEADING,
        BlockType.PARAGRAPH,
        BlockType.LIST_ITEM,
        BlockType.CAPTION,
    }
)

HEADING_BLOCK_TYPES = frozenset({BlockType.TITLE, BlockType.HEADING})


class MetricResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    value: float | None = None
    available: bool = True
    detail: dict[str, float | int | str] = Field(default_factory=dict)

    @classmethod
    def unavailable(cls, name: str, reason: str) -> MetricResult:
        return cls(name=name, value=None, available=False, detail={"reason": reason})


def compare_key(text: str) -> str:
    """Normalize text for comparison without destroying Vietnamese diacritics."""
    return _WHITESPACE.sub(" ", unicodedata.normalize("NFC", text)).strip().casefold()


def levenshtein(reference: str, hypothesis: str) -> int:
    if reference == hypothesis:
        return 0
    if not reference:
        return len(hypothesis)
    if not hypothesis:
        return len(reference)

    previous = list(range(len(hypothesis) + 1))
    for i, ref_char in enumerate(reference, start=1):
        current = [i]
        for j, hyp_char in enumerate(hypothesis, start=1):
            cost = 0 if ref_char == hyp_char else 1
            current.append(
                min(
                    previous[j] + 1,
                    current[j - 1] + 1,
                    previous[j - 1] + cost,
                )
            )
        previous = current
    return previous[-1]


def _error_rate(reference: list[str] | str, hypothesis: list[str] | str) -> float:
    if isinstance(reference, list):
        # Token-level edit distance via a private codepoint alphabet.
        vocabulary: dict[str, str] = {}

        def encode(tokens: list[str]) -> str:
            encoded = []
            for token in tokens:
                if token not in vocabulary:
                    vocabulary[token] = chr(0xE000 + len(vocabulary))
                encoded.append(vocabulary[token])
            return "".join(encoded)

        ref_encoded, hyp_encoded = encode(reference), encode(list(hypothesis))
        return levenshtein(ref_encoded, hyp_encoded) / max(1, len(ref_encoded))

    return levenshtein(reference, str(hypothesis)) / max(1, len(reference))


# --------------------------------------------------------------------------- text


def character_accuracy(document: CanonicalDocument, truth: GroundTruth) -> MetricResult:
    if not truth.transcript:
        return MetricResult.unavailable("character_accuracy", "no Level C transcript")

    actual = document.text_by_page()
    total_ref = 0
    total_errors = 0
    for page_key, expected in truth.transcript.items():
        page_number = int(page_key)
        reference = compare_key(expected)
        hypothesis = compare_key(actual.get(page_number, ""))
        total_ref += len(reference)
        total_errors += levenshtein(reference, hypothesis)

    cer = total_errors / max(1, total_ref)
    return MetricResult(
        name="character_accuracy",
        value=max(0.0, 1.0 - cer),
        detail={"cer": round(cer, 6), "reference_characters": total_ref},
    )


def word_accuracy(document: CanonicalDocument, truth: GroundTruth) -> MetricResult:
    if not truth.transcript:
        return MetricResult.unavailable("word_accuracy", "no Level C transcript")

    actual = document.text_by_page()
    total_ref = 0
    total_errors = 0
    for page_key, expected in truth.transcript.items():
        page_number = int(page_key)
        reference = compare_key(expected).split()
        hypothesis = compare_key(actual.get(page_number, "")).split()
        total_ref += len(reference)
        total_errors += round(_error_rate(reference, hypothesis) * max(1, len(reference)))

    wer = total_errors / max(1, total_ref)
    return MetricResult(
        name="word_accuracy",
        value=max(0.0, 1.0 - wer),
        detail={"wer": round(wer, 6), "reference_words": total_ref},
    )


def diacritic_preservation(document: CanonicalDocument, truth: GroundTruth) -> MetricResult:
    """Vietnamese diacritics must survive parsing and Unicode normalization."""
    if not truth.transcript:
        return MetricResult.unavailable("diacritic_preservation", "no Level C transcript")

    def combining_count(text: str) -> int:
        return sum(1 for char in unicodedata.normalize("NFD", text) if unicodedata.combining(char))

    expected = sum(combining_count(value) for value in truth.transcript.values())
    if expected == 0:
        return MetricResult.unavailable("diacritic_preservation", "transcript has no diacritics")

    produced = sum(combining_count(text) for text in document.text_by_page().values())
    return MetricResult(
        name="diacritic_preservation",
        value=min(1.0, produced / expected),
        detail={"expected_marks": expected, "produced_marks": produced},
    )


# ---------------------------------------------------------------------- structure


def reading_order_accuracy(document: CanonicalDocument, truth: GroundTruth) -> MetricResult:
    """Pairwise concordance between the expected sequence and the produced one.

    Blocks the parser missed are not silently ignored: they lower recall, which is
    folded into the score alongside the ordering of what was found.
    """
    if not truth.reading_order:
        return MetricResult.unavailable("reading_order_accuracy", "no reading_order labels")

    produced = [compare_key(block.text) for block in document.iter_blocks() if block.text.strip()]
    positions: dict[str, int] = {}
    for index, text in enumerate(produced):
        positions.setdefault(text, index)

    expected = [compare_key(text) for text in truth.reading_order]
    found = [(index, positions[text]) for index, text in enumerate(expected) if text in positions]

    recall = len(found) / len(expected)
    if len(found) < 2:
        return MetricResult(
            name="reading_order_accuracy",
            value=recall,
            detail={"matched_blocks": len(found), "expected_blocks": len(expected)},
        )

    concordant = 0
    total_pairs = 0
    for i in range(len(found)):
        for j in range(i + 1, len(found)):
            total_pairs += 1
            if found[j][1] > found[i][1]:
                concordant += 1

    order_score = concordant / total_pairs
    return MetricResult(
        name="reading_order_accuracy",
        value=order_score * recall,
        detail={
            "pairwise_order_score": round(order_score, 6),
            "block_recall": round(recall, 6),
            "matched_blocks": len(found),
            "expected_blocks": len(expected),
        },
    )


def heading_hierarchy_f1(document: CanonicalDocument, truth: GroundTruth) -> MetricResult:
    if not truth.headings:
        return MetricResult.unavailable("heading_hierarchy_f1", "no heading labels")

    expected = {compare_key(heading.text) for heading in truth.headings}
    produced = {
        compare_key(block.text)
        for block in document.iter_blocks()
        if block.type in HEADING_BLOCK_TYPES and block.text.strip()
    }

    if not produced:
        return MetricResult(
            name="heading_hierarchy_f1",
            value=0.0,
            detail={"expected": len(expected), "produced": 0},
        )

    true_positives = len(expected & produced)
    precision = true_positives / len(produced)
    recall = true_positives / len(expected)
    f1 = 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)

    return MetricResult(
        name="heading_hierarchy_f1",
        value=f1,
        detail={
            "precision": round(precision, 6),
            "recall": round(recall, 6),
            "expected": len(expected),
            "produced": len(produced),
        },
    )


def list_preservation(document: CanonicalDocument, truth: GroundTruth) -> MetricResult:
    if not truth.lists:
        return MetricResult.unavailable("list_preservation", "no list labels")

    produced = [
        compare_key(block.text)
        for block in document.iter_blocks()
        if block.type == BlockType.LIST_ITEM and block.text.strip()
    ]
    positions = {text: index for index, text in enumerate(produced)}

    scores: list[float] = []
    for expected_list in truth.lists:
        items = [compare_key(item) for item in expected_list]
        found = [positions[item] for item in items if item in positions]
        recall = len(found) / max(1, len(items))
        ordered = all(found[i] < found[i + 1] for i in range(len(found) - 1))
        scores.append(recall * (1.0 if ordered else 0.5))

    return MetricResult(
        name="list_preservation",
        value=sum(scores) / len(scores),
        detail={"lists_evaluated": len(scores), "list_items_produced": len(produced)},
    )


def table_structure_score(document: CanonicalDocument, truth: GroundTruth) -> MetricResult:
    if not truth.tables:
        return MetricResult.unavailable("table_structure_score", "no table labels")

    scores: list[float] = []
    for expected in truth.tables:
        candidates = [
            table for table in document.tables if table.page_number == expected.page_number
        ]
        if not candidates:
            scores.append(0.0)
            continue

        expected_cells = [compare_key(cell) for row in expected.cells for cell in row]
        best = 0.0
        for table in candidates:
            produced_cells = [compare_key(cell) for row in table.cells for cell in row]
            matched = 0
            remaining = list(produced_cells)
            for cell in expected_cells:
                if cell in remaining:
                    remaining.remove(cell)
                    matched += 1
            cell_recall = matched / max(1, len(expected_cells))
            shape_match = (
                1.0
                if (table.n_rows, table.n_cols)
                == (
                    len(expected.cells),
                    max((len(row) for row in expected.cells), default=0),
                )
                else 0.5
            )
            best = max(best, cell_recall * shape_match)
        scores.append(best)

    return MetricResult(
        name="table_structure_score",
        value=sum(scores) / len(scores),
        detail={"tables_expected": len(truth.tables), "tables_produced": len(document.tables)},
    )


def header_footer_leakage(document: CanonicalDocument, truth: GroundTruth) -> MetricResult:
    """Score is 1 - leakage: running headers/footers must not pollute body text."""
    if not truth.header_footer_texts:
        return MetricResult.unavailable("header_footer_leakage", "no header/footer labels")

    body_text = " ".join(
        compare_key(block.text)
        for block in document.iter_blocks()
        if block.type in BODY_BLOCK_TYPES
    )

    leaked = [text for text in truth.header_footer_texts if compare_key(text) in body_text]
    leakage = len(leaked) / len(truth.header_footer_texts)
    return MetricResult(
        name="header_footer_leakage",
        value=1.0 - leakage,
        detail={"leaked": len(leaked), "expected_margins": len(truth.header_footer_texts)},
    )


def provenance_completeness(document: CanonicalDocument, truth: GroundTruth) -> MetricResult:
    """Hard requirement: every useful block keeps page provenance and a unique order."""
    del truth  # provenance is a schema invariant, not a labelled property

    blocks = document.iter_blocks()
    if not blocks:
        return MetricResult(
            name="provenance_completeness",
            value=0.0,
            detail={"blocks": 0, "reason": "parser produced no blocks"},
        )

    complete = 0
    for page in document.pages:
        orders = [block.reading_order for block in page.blocks]
        orders_unique = len(orders) == len(set(orders))
        for block in page.blocks:
            if block.provenance.page_number == page.page_number and block.id and orders_unique:
                complete += 1

    with_bbox = sum(1 for block in blocks if block.bbox is not None)
    return MetricResult(
        name="provenance_completeness",
        value=complete / len(blocks),
        detail={
            "blocks": len(blocks),
            "blocks_with_bbox": with_bbox,
            "pages": len(document.pages),
        },
    )


def page_attribution_accuracy(document: CanonicalDocument, truth: GroundTruth) -> MetricResult:
    """Does text land on the page it actually came from?"""
    if not truth.transcript:
        return MetricResult.unavailable("page_attribution_accuracy", "no Level C transcript")

    actual = document.text_by_page()
    correct = 0
    for page_key, expected in truth.transcript.items():
        page_number = int(page_key)
        expected_words = set(compare_key(expected).split())
        produced_words = set(compare_key(actual.get(page_number, "")).split())
        if expected_words and len(expected_words & produced_words) / len(expected_words) >= 0.5:
            correct += 1

    return MetricResult(
        name="page_attribution_accuracy",
        value=correct / max(1, len(truth.transcript)),
        detail={"pages_checked": len(truth.transcript), "pages_correct": correct},
    )


# ----------------------------------------------------------------- critical fields


def critical_field_accuracy(
    extracted: dict[str, str | None],
    truth: GroundTruth,
) -> tuple[MetricResult, list[str]]:
    """Normalized exact match on the fields whose errors are release-blocking.

    Returns the metric plus the list of fields that were wrong, so the caller can
    apply the severity-3 hard gate rather than hiding it inside an average.
    """
    if not truth.critical_fields:
        return (
            MetricResult.unavailable("critical_field_accuracy", "no critical-field labels"),
            [],
        )

    wrong: list[str] = []
    correct = 0
    for name, expected in truth.critical_fields.items():
        produced = extracted.get(name)
        if produced is not None and compare_key(produced) == compare_key(expected):
            correct += 1
        else:
            wrong.append(name)

    return (
        MetricResult(
            name="critical_field_accuracy",
            value=correct / len(truth.critical_fields),
            detail={"expected": len(truth.critical_fields), "correct": correct},
        ),
        wrong,
    )


def route_accuracy(actual_route: str, expected_route: str) -> MetricResult:
    return MetricResult(
        name="route_accuracy",
        value=1.0 if actual_route == expected_route else 0.0,
        detail={"expected": expected_route, "actual": actual_route},
    )


ALL_DOCUMENT_METRICS = (
    character_accuracy,
    word_accuracy,
    diacritic_preservation,
    reading_order_accuracy,
    heading_hierarchy_f1,
    list_preservation,
    table_structure_score,
    header_footer_leakage,
    provenance_completeness,
    page_attribution_accuracy,
)


def evaluate_document(document: CanonicalDocument, truth: GroundTruth) -> dict[str, MetricResult]:
    return {metric.__name__: metric(document, truth) for metric in ALL_DOCUMENT_METRICS}
