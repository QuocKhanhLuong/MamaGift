"""Hand-computed deterministic tests for MamaGift answer-quality metrics."""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from mamagift_eval.qa_metrics import (
    abstention_correctness,
    citation_completeness,
    citation_correctness,
    deadline_correctness,
    responsible_party_correctness,
    task_action_completeness,
)
from mamagift_eval.schemas import ExpectedTaskRelation
from mamagift_rag.schema import Citation, ModelRef, QaAnswer, RetrievalRef
from mamagift_retrieval.budget import BudgetBreakdown
from mamagift_retrieval.evidence import Evidence, EvidenceSet
from mamagift_retrieval.scope import EvidenceScope

pytestmark = pytest.mark.unit


_SCOPE = EvidenceScope(
    family_id="mamagift",
    document_id="doc-1",
    document_version=2,
    parse_run_id="parse-2",
)


def _evidence(
    citation_id: str,
    *,
    document_id: str = "doc-1",
    document_version: int = 2,
    parse_run_id: str = "parse-2",
    text: str = "Hạn cuối là ngày 15/09/2026. Đơn vị A thực hiện.",
    block_id: str | None = None,
) -> Evidence:
    return Evidence(
        citation_id=citation_id,
        chunk_id=f"chunk-{citation_id}",
        document_id=document_id,
        parse_run_id=parse_run_id,
        document_version=document_version,
        page_numbers=[3],
        source_block_ids=[block_id or f"block-{citation_id}"],
        section_path=["Điều 1"],
        text=text,
    )


def _evidence_set(items: Sequence[Evidence]) -> EvidenceSet:
    return EvidenceSet(
        scope=_SCOPE,
        evidence=list(items),
        budget=BudgetBreakdown(categories=[]),
        query_id="query-1",
    )


def _citation(
    citation_id: str,
    *,
    document_id: str = "doc-1",
    page_number: int = 3,
    block_id: str | None = None,
    quote: str | None = None,
) -> Citation:
    return Citation(
        citation_id=citation_id,
        document_id=document_id,
        page_number=page_number,
        block_ids=[block_id or f"block-{citation_id}"],
        quote=quote,
    )


def _answer(status: str) -> QaAnswer:
    return QaAnswer(
        answer="Tôi không đủ căn cứ để trả lời." if status != "answered" else "Có căn cứ.",
        status=status,  # type: ignore[arg-type]
        citations=[],
        retrieval=RetrievalRef(query_id="query-1"),
        model=ModelRef(provider="fake", model="fake", version="1"),
    )


def _relations() -> list[ExpectedTaskRelation]:
    return [
        ExpectedTaskRelation(
            task_ordinal="1",
            task_title="Gửi báo cáo",
            owner="Đơn vị A",
            deadline="2026-09-15",
        ),
        ExpectedTaskRelation(
            task_ordinal="2",
            task_title="Tổng hợp kết quả",
            owner="Đơn vị B",
            deadline="2026-09-30",
        ),
    ]


def test_citation_correctness_is_hand_computable_and_checks_supporting_id() -> None:
    evidence = _evidence_set([_evidence("c1"), _evidence("c2")])
    expected = {"deadline": ["c1"], "owner": ["c2"]}
    actual = {
        "deadline": [_citation("c1")],
        "owner": [_citation("c2"), _citation("c1")],
    }

    # c1 and c2 support their respective claims; the extra c1 does not.
    assert citation_correctness(expected, actual, evidence) == pytest.approx(2 / 3)


def test_textually_right_citation_from_wrong_version_or_parse_run_is_not_correct() -> None:
    expected = {"deadline": ["c1"]}
    actual = {"deadline": [_citation("c1")]}

    wrong_version = _evidence_set([_evidence("c1", document_version=1)])
    wrong_parse_run = _evidence_set([_evidence("c1", parse_run_id="parse-old")])
    assert citation_correctness(expected, actual, wrong_version) == 0.0
    assert citation_correctness(expected, actual, wrong_parse_run) == 0.0


def test_citation_presentation_metadata_must_resolve_to_the_evidence_span() -> None:
    evidence = _evidence_set([_evidence("c1", text="Hạn cuối là 15/09/2026.")])
    expected = {"deadline": ["c1"]}
    assert citation_correctness(expected, {"deadline": [_citation("c1")]}, evidence) == 1.0
    assert (
        citation_correctness(
            expected, {"deadline": [_citation("c1", block_id="foreign-block")]}, evidence
        )
        == 0.0
    )
    assert (
        citation_correctness(
            expected, {"deadline": [_citation("c1", document_id="foreign-doc")]}, evidence
        )
        == 0.0
    )
    assert (
        citation_correctness(expected, {"deadline": [_citation("c1", page_number=4)]}, evidence)
        == 0.0
    )
    assert (
        citation_correctness(
            expected, {"deadline": [_citation("c1", quote="not in source")]}, evidence
        )
        == 0.0
    )


def test_citation_completeness_scores_valid_claim_coverage() -> None:
    evidence = _evidence_set([_evidence("c1"), _evidence("c2")])
    expected = {"deadline": ["c1"], "owner": ["c2"], "appeal": ["c1"]}
    actual = {"deadline": ["c1"], "owner": ["c2"]}
    assert citation_completeness(expected, actual, evidence) == pytest.approx(2 / 3)


def test_citation_completeness_does_not_credit_foreign_or_unknown_evidence() -> None:
    expected = {"deadline": ["c1"], "owner": ["c2"]}
    actual = {"deadline": ["unknown"], "owner": ["c2"]}
    evidence = _evidence_set([_evidence("c2")])
    assert citation_completeness(expected, actual, evidence) == 0.5

    stale = _evidence_set([_evidence("c1", document_version=1), _evidence("c2")])
    assert citation_completeness(expected, {"deadline": ["c1"], "owner": ["c2"]}, stale) == 0.5


def test_duplicate_citation_ids_are_not_deterministically_creditable() -> None:
    evidence = _evidence_set([_evidence("c1"), _evidence("c1")])
    expected = {"deadline": ["c1"]}
    assert citation_correctness(expected, {"deadline": ["c1"]}, evidence) == 0.0
    assert citation_completeness(expected, {"deadline": ["c1"]}, evidence) == 0.0


def test_abstention_correctness_catches_both_failure_directions() -> None:
    # Case 1 should abstain but answered; case 2 had evidence but abstained.
    assert (
        abstention_correctness(
            [True, False], [_answer("answered"), _answer("insufficient_evidence")]
        )
        == 0.0
    )


def test_abstention_correctness_scores_exact_statuses() -> None:
    assert (
        abstention_correctness(
            [True, False, True],
            [_answer("insufficient_evidence"), _answer("answered"), "insufficient_evidence"],
        )
        == 1.0
    )


def test_deadline_correctness_scores_each_expected_deadline_by_task() -> None:
    expected = _relations()
    actual = [expected[0], expected[1].model_copy(update={"deadline": "2026-12-31"})]
    assert deadline_correctness(expected, expected) == 1.0
    assert deadline_correctness(expected, actual) == 0.5


def test_responsible_party_correctness_never_credits_crossed_owner() -> None:
    expected = _relations()
    actual = [
        expected[0].model_copy(update={"owner": "Đơn vị B"}),
        expected[1].model_copy(update={"owner": "Đơn vị A"}),
    ]
    assert responsible_party_correctness(expected, actual) == 0.0


def test_task_action_completeness_scores_present_actions_and_titles() -> None:
    expected = _relations()
    actual = [expected[0], expected[1].model_copy(update={"task_title": "Sai hành động"})]
    assert task_action_completeness(expected, actual) == 0.5


def test_all_metrics_define_empty_input() -> None:
    empty_evidence = _evidence_set([])
    assert citation_correctness({}, {}, empty_evidence) == 1.0
    assert citation_completeness({}, {}, empty_evidence) == 1.0
    assert citation_correctness({"claim": ["c1"]}, {}, empty_evidence) == 0.0
    assert citation_completeness({"claim": ["c1"]}, {}, empty_evidence) == 0.0
    assert abstention_correctness([], []) == 1.0
    assert deadline_correctness([], []) == 1.0
    assert responsible_party_correctness([], []) == 1.0
    assert task_action_completeness([], []) == 1.0


def test_abstention_case_count_must_match() -> None:
    with pytest.raises(ValueError, match="same number"):
        abstention_correctness([True], [])
