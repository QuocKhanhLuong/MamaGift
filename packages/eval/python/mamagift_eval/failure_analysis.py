"""Deterministic per-question failure analysis for grounded QA.

This module is deliberately an evaluator seam, not a judge.  The caller supplies
the answer/fact correctness decision (for example, from a hand-authored fixture
and the Phase 4 metrics), while this module determines whether the expected
evidence is in the retrieved context under the complete requested provenance.

The decision path is:

    wrong answer
      -> in-scope evidence present? no -> upstream; yes -> generation/grounding

Textually matching evidence with a different document, version, or parse run is
never credited as present.  It is reported as a metadata-version failure so a
stale or foreign match cannot be mistaken for a generation failure.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Sequence
from typing import TypeAlias

from pydantic import BaseModel, ConfigDict, Field

from mamagift_retrieval.chunk import Chunk
from mamagift_retrieval.evidence import Evidence, EvidenceSet
from mamagift_retrieval.scope import EvidenceScope, scope_matches

from .taxonomy import FailureDiagnosis, FailureLabel, classify_failure

ContextItem: TypeAlias = Chunk | Evidence
Context: TypeAlias = Sequence[ContextItem] | EvidenceSet
_UPSTREAM_LABELS = frozenset(
    {
        FailureLabel.PARSER_FAILURE,
        FailureLabel.CHUNKING_FAILURE,
        FailureLabel.RETRIEVAL_FAILURE,
        FailureLabel.METADATA_VERSION_FAILURE,
    }
)
_WHITESPACE = re.compile(r"\s+")


class FailureAnalysisCase(BaseModel):
    """One hand-authored, deterministic question diagnosis input.

    ``answer_or_fact_correct`` is intentionally supplied by the caller; no LLM
    or opaque judge is used here.  At least one expected text, chunk id, or source
    block id must be supplied so evidence presence has an explicit contract.
    ``evidence_stage`` is an optional signal from H1/H3 or parser diagnostics. It
    is consulted only when the context cannot identify a more specific cause.
    """

    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1)
    answer_or_fact_correct: bool
    scope: EvidenceScope
    retrieved_context: list[ContextItem] | EvidenceSet = Field(default_factory=list)
    expected_evidence_texts: list[str] = Field(default_factory=list)
    expected_chunk_ids: list[str] = Field(default_factory=list)
    expected_source_block_ids: list[str] = Field(default_factory=list)
    evidence_stage: FailureLabel | None = None
    detail: str = ""


class FailureAnalysisReport(BaseModel):
    """Machine-readable batch output with a deterministic human rendering."""

    model_config = ConfigDict(extra="forbid")

    cases: list[FailureDiagnosis] = Field(default_factory=list)

    @property
    def diagnoses(self) -> list[FailureDiagnosis]:
        """Compatibility name for callers that describe output as diagnoses."""
        return self.cases

    def to_json(self, *, indent: int = 2) -> str:
        """Return stable machine-readable JSON for tooling."""
        return self.model_dump_json(indent=indent)

    def to_markdown(self) -> str:
        """Return deterministic triage output for a person."""
        lines = [
            "# Per-question failure analysis",
            "",
            f"Cases: {len(self.cases)}",
            "",
            "| Case | Answer/fact | Evidence in scope | Label | Detail |",
            "| --- | --- | --- | --- | --- |",
        ]
        for diagnosis in self.cases:
            answer = "correct" if diagnosis.answer_or_fact_correct else "wrong"
            evidence = "yes" if diagnosis.evidence_present else "no"
            detail = diagnosis.detail.replace("|", "\\|").replace("\n", " ")
            lines.append(
                f"| `{diagnosis.case_id}` | {answer} | {evidence} | "
                f"`{diagnosis.label.value}` | {detail} |"
            )
        return "\n".join(lines)


def analyze_failure(case: FailureAnalysisCase) -> FailureDiagnosis:
    """Classify one question using scoped retrieved context.

    A matching item is considered evidence only when its own recorded
    ``document_id``, ``document_version``, and ``parse_run_id`` match the fully
    pinned request scope.  A textual/identifier match outside that scope is
    deliberately checked before optional stage hints and classified as a
    metadata-version failure.
    """
    _require_pinned_scope(case.scope)
    context = _context_items(case.retrieved_context, case.scope)
    expected_texts = tuple(
        _normalize(text) for text in case.expected_evidence_texts if text.strip()
    )
    expected_chunks = frozenset(case.expected_chunk_ids)
    expected_blocks = frozenset(case.expected_source_block_ids)
    if not expected_texts and not expected_chunks and not expected_blocks:
        raise ValueError(
            "at least one expected_evidence_texts, expected_chunk_ids, or "
            "expected_source_block_ids value is required"
        )

    matching: list[tuple[ContextItem, bool, bool, bool]] = []
    for item in context:
        text_match, identifier_match = _match_kinds(
            item,
            expected_texts=expected_texts,
            expected_chunks=expected_chunks,
            expected_blocks=expected_blocks,
        )
        if text_match or identifier_match:
            matching.append(
                (
                    item,
                    _item_matches_scope(item, case.scope),
                    text_match,
                    identifier_match,
                )
            )

    # An identifier alone is a retrieval/location signal when expected text is
    # supplied: it can narrow parser/chunking loss, but does not prove that the
    # expected evidence survived.  Conversely, an out-of-scope identifier is
    # enough to expose a provenance/version mismatch even when its text changed.
    in_scope_match = any(
        is_in_scope and (text_match or not expected_texts)
        for _, is_in_scope, text_match, _ in matching
    )
    out_of_scope_match = any(not is_in_scope for _, is_in_scope, _, _ in matching)

    if case.answer_or_fact_correct:
        detail = _join_detail(case.detail, "The answer/fact is correct; no failure is assigned.")
        return classify_failure(
            case_id=case.case_id,
            answer_or_fact_correct=True,
            evidence_present=in_scope_match,
            detail=detail,
        )

    if in_scope_match:
        detail = _join_detail(
            case.detail,
            "Expected evidence is present in the retrieved context under the full "
            "document/version/parse-run scope; classify as downstream "
            "generation/grounding.",
        )
        return classify_failure(
            case_id=case.case_id,
            answer_or_fact_correct=False,
            evidence_present=True,
            detail=detail,
        )

    if out_of_scope_match:
        detail = _join_detail(
            case.detail,
            "Matching evidence text or identifiers were retrieved, but their "
            "document, version, or parse-run provenance does not match the "
            "requested scope; classify as metadata-version.",
        )
        return classify_failure(
            case_id=case.case_id,
            answer_or_fact_correct=False,
            evidence_present=False,
            evidence_stage=FailureLabel.METADATA_VERSION_FAILURE,
            detail=detail,
        )

    stage, stage_detail = _infer_upstream_stage(
        case,
        context,
        expected_chunks=expected_chunks,
        expected_blocks=expected_blocks,
    )
    return classify_failure(
        case_id=case.case_id,
        answer_or_fact_correct=False,
        evidence_present=False,
        evidence_stage=stage,
        detail=_join_detail(case.detail, stage_detail),
    )


def analyze_failure_case(case: FailureAnalysisCase) -> FailureDiagnosis:
    """Explicitly named alias for :func:`analyze_failure`."""
    return analyze_failure(case)


def analyze_failures(cases: Iterable[FailureAnalysisCase]) -> FailureAnalysisReport:
    """Analyze a batch in input order; an empty batch is a valid empty report."""
    return FailureAnalysisReport(cases=[analyze_failure(case) for case in cases])


def _require_pinned_scope(scope: EvidenceScope) -> None:
    if (
        scope.document_id is None
        or scope.document_version is None
        or scope.parse_run_id is None
        or not scope.parse_run_id
    ):
        raise ValueError(
            "failure analysis requires a fully pinned EvidenceScope: "
            "document_id, document_version, and parse_run_id"
        )


def _context_items(context: Context, scope: EvidenceScope) -> list[ContextItem]:
    if isinstance(context, EvidenceSet):
        _require_pinned_scope(context.scope)
        if context.scope != scope:
            raise ValueError(
                "retrieved EvidenceSet scope must exactly match the requested "
                "family/document/version/parse-run scope"
            )
        return list(context.evidence)
    return list(context)


def _item_matches_scope(item: ContextItem, scope: EvidenceScope) -> bool:
    candidate = EvidenceScope(
        family_id=scope.family_id,
        document_id=item.document_id,
        document_version=item.document_version,
        parse_run_id=item.parse_run_id,
        user_id=scope.user_id,
        thread_id=scope.thread_id,
    )
    return scope_matches(candidate, scope)


def _match_kinds(
    item: ContextItem,
    *,
    expected_texts: Sequence[str],
    expected_chunks: frozenset[str],
    expected_blocks: frozenset[str],
) -> tuple[bool, bool]:
    text_match = bool(
        expected_texts and any(text in _normalize(item.text) for text in expected_texts)
    )
    identifier_match = bool(
        (expected_chunks and item.chunk_id in expected_chunks)
        or (expected_blocks and expected_blocks.intersection(_source_block_ids(item)))
    )
    return text_match, identifier_match


def _infer_upstream_stage(
    case: FailureAnalysisCase,
    context: Sequence[ContextItem],
    *,
    expected_chunks: frozenset[str],
    expected_blocks: frozenset[str],
) -> tuple[FailureLabel, str]:
    if case.evidence_stage is not None:
        if case.evidence_stage not in _UPSTREAM_LABELS:
            raise ValueError(
                "evidence_stage must be parser/chunking/retrieval/metadata_version "
                "when evidence is absent"
            )
        return (
            case.evidence_stage,
            f"The retrieved context does not contain the expected evidence; "
            f"upstream stage supplied by evaluation data: {case.evidence_stage.value}.",
        )

    if not context:
        return (
            FailureLabel.RETRIEVAL_FAILURE,
            "The retrieved context is empty, so the upstream failure is narrowed to retrieval.",
        )

    # An expected source block with no expected text indicates parser loss in a
    # chunk that still points at the source block.  A known chunk id with altered
    # or absent expected text indicates chunking loss.  These checks are only made
    # after provenance matching, so stale/foreign ids cannot be credited here.
    in_scope_items = [item for item in context if _item_matches_scope(item, case.scope)]
    if expected_blocks and any(
        expected_blocks.intersection(_source_block_ids(item)) for item in in_scope_items
    ):
        return (
            FailureLabel.PARSER_FAILURE,
            "An in-scope source block is present but the expected evidence text is "
            "not present; the upstream failure is narrowed to parsing.",
        )
    if expected_chunks and any(item.chunk_id in expected_chunks for item in in_scope_items):
        return (
            FailureLabel.CHUNKING_FAILURE,
            "An in-scope chunk is present but the expected evidence is not present; "
            "the upstream failure is narrowed to chunking.",
        )
    return (
        FailureLabel.RETRIEVAL_FAILURE,
        "The expected evidence is absent and the available data cannot narrow the "
        "upstream failure beyond retrieval/parser/chunking/metadata-version stages.",
    )


def _source_block_ids(item: ContextItem) -> frozenset[str]:
    return frozenset(item.source_block_ids)


def _normalize(value: str) -> str:
    return _WHITESPACE.sub(" ", unicodedata.normalize("NFKC", value).casefold()).strip()


def _join_detail(existing: str, generated: str) -> str:
    return f"{existing.strip()} {generated}".strip() if existing.strip() else generated


__all__ = [
    "Context",
    "ContextItem",
    "FailureAnalysisCase",
    "FailureAnalysisReport",
    "analyze_failure",
    "analyze_failure_case",
    "analyze_failures",
]
