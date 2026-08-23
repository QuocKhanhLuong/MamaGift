"""Deterministic answer-quality metrics for Vietnamese administrative QA.

The inputs to these metrics are hand-authored expectations and the structured
outputs of the QA pipeline.  They intentionally do not inspect prose with a
model.  Citation metrics use the existing ``EvidenceSet`` allow-list and the
existing ``Citation`` contract; task metrics use the Phase 3.5
``ExpectedTaskRelation``/``ParserSemanticCase`` and ``Chunk`` contracts.

Citation metric denominators are deliberately explicit:

* :func:`citation_correctness` is the number of citation references emitted by
  the answer (a missing citation is handled by completeness).  A reference is
  correct only when its claim's expected citation id, EvidenceSet entry, and
  full document/version/parse-run provenance all agree.
* :func:`citation_completeness` is the number of hand-authored factual claims.
  A claim counts only when it has at least one valid, in-scope citation.
* :func:`abstention_correctness` is the number of QA cases.
* The deadline and responsible-party metrics divide by expected relations that
  actually specify the respective field.
* :func:`task_action_completeness` divides by all expected task relations.

Empty expected sets are vacuously perfect (``1.0``); a non-empty expectation
with no actual evidence/relations scores ``0.0``.  This keeps every metric
defined without a zero-division special case leaking to callers.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TypeAlias

from mamagift_rag.schema import Citation, QaAnswer
from mamagift_retrieval.chunk import Chunk
from mamagift_retrieval.evidence import Evidence, EvidenceSet

from .metrics import (
    deadline_accuracy,
    task_deadline_association_accuracy,
    task_owner_association_accuracy,
    task_recall,
)
from .schemas import ExpectedTaskRelation, ParserSemanticCase

CitationReference: TypeAlias = str | Citation
ClaimCitations: TypeAlias = Mapping[str, Sequence[CitationReference]]
ExpectedTasks: TypeAlias = Sequence[ExpectedTaskRelation] | ParserSemanticCase
ActualTasks: TypeAlias = Sequence[ExpectedTaskRelation] | Sequence[Chunk]
AbstentionValue: TypeAlias = bool | str | QaAnswer


def _bounded(value: float) -> float:
    """Return a defensive [0, 1] value for all public metric results."""
    return max(0.0, min(1.0, value))


def _evidence_by_id(evidence: EvidenceSet) -> dict[str, Evidence]:
    """Build the citation allow-list, rejecting ambiguous ids.

    EvidenceSet normally comes from the assembler, but evaluation must not
    assume that an arbitrary fixture was assembled correctly.  A duplicate id
    cannot resolve deterministically and is therefore never credited.
    """
    by_id: dict[str, Evidence] = {}
    duplicates: set[str] = set()
    for item in evidence.evidence:
        if item.citation_id in by_id:
            duplicates.add(item.citation_id)
        else:
            by_id[item.citation_id] = item
    for citation_id in duplicates:
        by_id.pop(citation_id, None)
    return by_id


def _citation_id(reference: CitationReference) -> str:
    return reference if isinstance(reference, str) else reference.citation_id


def _reference_in_scope(reference: CitationReference, evidence: EvidenceSet) -> bool:
    """Check citation metadata and the complete provenance tuple.

    ``Citation`` intentionally carries presentation metadata only; version and
    parse-run provenance are resolved through its ``citation_id`` into the
    EvidenceSet.  A textually identical foreign/stale Evidence entry is still
    rejected because all three identity fields must match the request scope.
    """
    evidence_by_id = _evidence_by_id(evidence)
    citation = evidence_by_id.get(_citation_id(reference))
    scope = evidence.scope
    if citation is None:
        return False
    if scope.document_id is None or scope.document_version is None or scope.parse_run_id is None:
        return False
    if (
        citation.document_id != scope.document_id
        or citation.document_version != scope.document_version
        or citation.parse_run_id != scope.parse_run_id
    ):
        return False

    if isinstance(reference, str):
        return True
    if reference.document_id != citation.document_id:
        return False
    if reference.page_number not in citation.page_numbers:
        return False
    if not reference.block_ids or not set(reference.block_ids).issubset(citation.source_block_ids):
        return False
    return reference.quote is None or reference.quote in citation.text


def _expected_claims(expected: ClaimCitations) -> tuple[str, ...]:
    claims = tuple(expected)
    if len(set(claims)) != len(claims):
        raise ValueError("expected claim ids must be unique")
    return claims


def citation_correctness(
    expected_claim_citations: ClaimCitations,
    actual_claim_citations: ClaimCitations,
    evidence: EvidenceSet,
) -> float:
    """Score whether emitted citation references support their claims.

    The denominator is the total number of emitted citation references.  Each
    reference must be one of the hand-authored supporting ids for that claim,
    resolve in the EvidenceSet, and match its request's document, version, and
    parse run.  With no emitted references, the result is ``1.0`` only when no
    factual claims were expected; otherwise it is ``0.0``.
    """
    expected_claims = _expected_claims(expected_claim_citations)
    expected_support = {
        claim_id: set(expected_claim_citations[claim_id]) for claim_id in expected_claims
    }
    references = [
        (claim_id, reference)
        for claim_id, claim_references in actual_claim_citations.items()
        for reference in claim_references
    ]
    if not references:
        return 1.0 if not expected_claims else 0.0

    correct = sum(
        1
        for claim_id, reference in references
        if claim_id in expected_support
        and _citation_id(reference) in expected_support[claim_id]
        and _reference_in_scope(reference, evidence)
    )
    return _bounded(correct / len(references))


def citation_completeness(
    expected_claim_citations: ClaimCitations,
    actual_claim_citations: ClaimCitations,
    evidence: EvidenceSet,
) -> float:
    """Score whether every factual claim has a valid citation.

    The denominator is the number of hand-authored factual claims.  A claim is
    complete when it has at least one emitted citation that resolves through the
    EvidenceSet and matches the full request provenance.  The citation need not
    be the *best* supporting id here; that distinction belongs to correctness.
    """
    expected_claims = _expected_claims(expected_claim_citations)
    if not expected_claims:
        return 1.0

    complete = 0
    for claim_id in expected_claims:
        references = actual_claim_citations.get(claim_id, ())
        if any(_reference_in_scope(reference, evidence) for reference in references):
            complete += 1
    return _bounded(complete / len(expected_claims))


def _is_abstention(value: AbstentionValue) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, QaAnswer):
        return value.status == "insufficient_evidence"
    return value == "insufficient_evidence"


def abstention_correctness(
    should_abstain: Sequence[bool],
    actual: Sequence[AbstentionValue],
) -> float:
    """Score exact abstention decisions, including both error directions.

    The denominator is the number of QA cases.  ``True`` means the evidence was
    insufficient and the answer should have status ``insufficient_evidence``;
    ``False`` means the answer should be answered.  Thus both answering without
    evidence and abstaining despite available evidence are incorrect.
    """
    if len(should_abstain) != len(actual):
        raise ValueError("should_abstain and actual must contain the same number of cases")
    if not should_abstain:
        return 1.0
    correct = sum(
        expected == _is_abstention(observed)
        for expected, observed in zip(should_abstain, actual, strict=True)
    )
    return _bounded(correct / len(should_abstain))


def _expected_relations(expected: ExpectedTasks) -> list[ExpectedTaskRelation]:
    relations = (
        expected.expected_task_relations if isinstance(expected, ParserSemanticCase) else expected
    )
    result = list(relations)
    ordinals = [relation.task_ordinal for relation in result]
    if len(set(ordinals)) != len(ordinals):
        raise ValueError("expected task_ordinal values must be unique")
    return result


def _actual_relation_map(actual: Sequence[ExpectedTaskRelation]) -> dict[str, ExpectedTaskRelation]:
    result: dict[str, ExpectedTaskRelation] = {}
    for relation in actual:
        if relation.task_ordinal in result:
            raise ValueError(f"duplicate actual task_ordinal {relation.task_ordinal!r}")
        result[relation.task_ordinal] = relation
    return result


def _relation_metric(
    expected: ExpectedTasks,
    actual: ActualTasks,
    *,
    field: str,
    chunk_metric: object,
    case: ParserSemanticCase | None,
    document_id: str | None,
    document_version: int | None,
    parse_run_id: str | None,
    document_type: str | None,
) -> float:
    expected_relations = _expected_relations(expected)
    scored = [relation for relation in expected_relations if getattr(relation, field) is not None]
    if not scored:
        return 1.0
    if not actual:
        return 0.0
    if all(isinstance(item, Chunk) for item in actual):
        # The existing Phase 3.5 metrics are the single authority for chunk
        # provenance filtering and task association semantics.
        chunks = [item for item in actual if isinstance(item, Chunk)]
        metric = chunk_metric
        if metric is task_deadline_association_accuracy:
            value = task_deadline_association_accuracy(
                expected_relations,
                chunks,
                case=case,
                document_id=document_id,
                document_version=document_version,
                parse_run_id=parse_run_id,
                document_type=document_type,
            )
        else:
            value = task_owner_association_accuracy(
                expected_relations,
                chunks,
                case=case,
                document_id=document_id,
                document_version=document_version,
                parse_run_id=parse_run_id,
                document_type=document_type,
            )
        return _bounded(value)
    if not all(isinstance(item, ExpectedTaskRelation) for item in actual):
        raise TypeError("actual tasks must contain only ExpectedTaskRelation or only Chunk values")
    by_ordinal = _actual_relation_map(
        [item for item in actual if isinstance(item, ExpectedTaskRelation)]
    )
    correct = sum(
        getattr(by_ordinal[relation.task_ordinal], field, None) == getattr(relation, field)
        if relation.task_ordinal in by_ordinal
        else 0
        for relation in scored
    )
    return _bounded(correct / len(scored))


def deadline_correctness(
    expected: ExpectedTasks,
    actual: ActualTasks,
    *,
    case: ParserSemanticCase | None = None,
    document_id: str | None = None,
    document_version: int | None = None,
    parse_run_id: str | None = None,
    document_type: str | None = "ke_hoach",
) -> float:
    """Score exact expected task deadlines.

    The denominator is expected task relations with a non-null deadline.  For
    chunk inputs, Phase 3.5's provenance-aware ``deadline_accuracy`` contract is
    reused; relation fixtures compare by task ordinal, never by list position.
    """
    expected_relations = _expected_relations(expected)
    scored = [relation for relation in expected_relations if relation.deadline is not None]
    if not scored:
        return 1.0
    if actual and all(isinstance(item, Chunk) for item in actual):
        chunks = [item for item in actual if isinstance(item, Chunk)]
        value = deadline_accuracy(
            expected_relations,
            chunks,
            case=case,
            document_id=document_id,
            document_version=document_version,
            parse_run_id=parse_run_id,
            document_type=document_type,
        )
        return _bounded(value)
    return _relation_metric(
        expected_relations,
        actual,
        field="deadline",
        chunk_metric=task_deadline_association_accuracy,
        case=case,
        document_id=document_id,
        document_version=document_version,
        parse_run_id=parse_run_id,
        document_type=document_type,
    )


def responsible_party_correctness(
    expected: ExpectedTasks,
    actual: ActualTasks,
    *,
    case: ParserSemanticCase | None = None,
    document_id: str | None = None,
    document_version: int | None = None,
    parse_run_id: str | None = None,
    document_type: str | None = "ke_hoach",
) -> float:
    """Score exact task-owner/responsible-party associations.

    The denominator is expected task relations with a non-null owner.  Matching
    is keyed by the task ordinal so an owner cannot be credited after crossing
    into another task.
    """
    return _relation_metric(
        expected,
        actual,
        field="owner",
        chunk_metric=task_owner_association_accuracy,
        case=case,
        document_id=document_id,
        document_version=document_version,
        parse_run_id=parse_run_id,
        document_type=document_type,
    )


def task_action_completeness(
    expected: ExpectedTasks,
    actual: ActualTasks,
    *,
    case: ParserSemanticCase | None = None,
    document_id: str | None = None,
    document_version: int | None = None,
    parse_run_id: str | None = None,
    document_type: str | None = "ke_hoach",
) -> float:
    """Score whether every expected task/action is present.

    The denominator is all expected task relations.  Structured relation
    fixtures must match both ordinal and normalized task title.  Chunk inputs
    delegate to Phase 3.5 ``task_recall``, whose ordinal and full-provenance
    filtering is the established parser/chunking contract.
    """
    expected_relations = _expected_relations(expected)
    if not expected_relations:
        return 1.0
    if not actual:
        return 0.0
    if all(isinstance(item, Chunk) for item in actual):
        chunks = [item for item in actual if isinstance(item, Chunk)]
        value = task_recall(
            expected_relations,
            chunks,
            case=case,
            document_id=document_id,
            document_version=document_version,
            parse_run_id=parse_run_id,
            document_type=document_type,
        )
        return _bounded(value)
    if not all(isinstance(item, ExpectedTaskRelation) for item in actual):
        raise TypeError("actual tasks must contain only ExpectedTaskRelation or only Chunk values")
    by_ordinal = _actual_relation_map(
        [item for item in actual if isinstance(item, ExpectedTaskRelation)]
    )

    def normalized(value: str) -> str:
        return " ".join(value.casefold().split())

    complete = sum(
        1
        for relation in expected_relations
        if relation.task_ordinal in by_ordinal
        and normalized(by_ordinal[relation.task_ordinal].task_title)
        == normalized(relation.task_title)
    )
    return _bounded(complete / len(expected_relations))


__all__ = [
    "ClaimCitations",
    "CitationReference",
    "abstention_correctness",
    "citation_completeness",
    "citation_correctness",
    "deadline_correctness",
    "responsible_party_correctness",
    "task_action_completeness",
]
