"""Tests for the Phase 3.5 failure-analysis diagnosis path:

    wrong answer/fact
      -> was correct evidence present?
          -> no: parser / chunking / retrieval / metadata-version failure
          -> yes: generation/grounding failure

Only the "no" branch is executable in this phase — there is no generation step yet.
"""

from __future__ import annotations

import pytest

from mamagift_eval.taxonomy import FailureLabel, classify_failure

pytestmark = pytest.mark.unit


def test_correct_fact_is_labelled_none() -> None:
    diagnosis = classify_failure(case_id="c1", answer_or_fact_correct=True, evidence_present=True)
    assert diagnosis.label == FailureLabel.NONE


def test_wrong_fact_with_missing_evidence_requires_a_stage() -> None:
    with pytest.raises(ValueError, match="evidence_stage"):
        classify_failure(case_id="c2", answer_or_fact_correct=False, evidence_present=False)


def test_wrong_fact_with_missing_evidence_is_labelled_by_stage() -> None:
    diagnosis = classify_failure(
        case_id="c3",
        answer_or_fact_correct=False,
        evidence_present=False,
        evidence_stage=FailureLabel.CHUNKING_FAILURE,
    )
    assert diagnosis.label == FailureLabel.CHUNKING_FAILURE
    assert diagnosis.evidence_present is False


def test_wrong_fact_with_evidence_present_is_generation_grounding_failure() -> None:
    diagnosis = classify_failure(
        case_id="c4",
        answer_or_fact_correct=False,
        evidence_present=True,
        evidence_stage=FailureLabel.RETRIEVAL_FAILURE,  # ignored: evidence was present
    )
    assert diagnosis.label == FailureLabel.GENERATION_GROUNDING_FAILURE


def test_evidence_stage_must_be_a_valid_upstream_stage() -> None:
    with pytest.raises(ValueError, match="evidence_stage"):
        classify_failure(
            case_id="c5",
            answer_or_fact_correct=False,
            evidence_present=False,
            evidence_stage=FailureLabel.NONE,
        )
