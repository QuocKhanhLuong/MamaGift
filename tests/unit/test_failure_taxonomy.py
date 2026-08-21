"""Tests for the Phase 3.5 failure-analysis diagnosis path:

    wrong answer/fact
      -> was correct evidence present?
          -> no: parser / chunking / retrieval / metadata-version failure
          -> yes: generation/grounding failure

Only the "no" branch is executable in this phase — there is no generation step yet.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from mamagift_eval.taxonomy import FailureDiagnosis, FailureLabel, classify_failure

pytestmark = pytest.mark.unit


def test_failure_label_complete_member_set() -> None:
    expected_members = {
        "NONE": "none",
        "PARSER_FAILURE": "parser_failure",
        "CHUNKING_FAILURE": "chunking_failure",
        "RETRIEVAL_FAILURE": "retrieval_failure",
        "METADATA_VERSION_FAILURE": "metadata_version_failure",
        "GENERATION_GROUNDING_FAILURE": "generation_grounding_failure",
    }
    assert {member.name: member.value for member in FailureLabel} == expected_members


def test_failure_diagnosis_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError):
        FailureDiagnosis(
            case_id="c1",
            answer_or_fact_correct=True,
            evidence_present=True,
            label=FailureLabel.NONE,
            unexpected_field="disallowed",  # type: ignore[call-arg]
        )


def test_failure_diagnosis_requires_case_id() -> None:
    with pytest.raises(ValidationError):
        FailureDiagnosis(
            case_id="",
            answer_or_fact_correct=True,
            evidence_present=True,
            label=FailureLabel.NONE,
        )


def test_classify_failure_rejects_empty_case_id() -> None:
    with pytest.raises(ValidationError):
        classify_failure(
            case_id="",
            answer_or_fact_correct=True,
            evidence_present=True,
        )


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


@pytest.mark.parametrize(
    "stage",
    [
        FailureLabel.PARSER_FAILURE,
        FailureLabel.CHUNKING_FAILURE,
        FailureLabel.RETRIEVAL_FAILURE,
        FailureLabel.METADATA_VERSION_FAILURE,
    ],
)
def test_wrong_fact_with_missing_evidence_all_upstream_stages(stage: FailureLabel) -> None:
    diagnosis = classify_failure(
        case_id="c_stage",
        answer_or_fact_correct=False,
        evidence_present=False,
        evidence_stage=stage,
        detail="upstream issue",
    )
    assert diagnosis.label == stage
    assert diagnosis.evidence_present is False
    assert diagnosis.answer_or_fact_correct is False
    assert diagnosis.detail == "upstream issue"


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


def test_evidence_stage_rejects_generation_grounding_failure_when_evidence_missing() -> None:
    with pytest.raises(ValueError, match="evidence_stage"):
        classify_failure(
            case_id="c6",
            answer_or_fact_correct=False,
            evidence_present=False,
            evidence_stage=FailureLabel.GENERATION_GROUNDING_FAILURE,
        )


def test_classify_failure_preserves_detail() -> None:
    diagnosis = classify_failure(
        case_id="c7",
        answer_or_fact_correct=True,
        evidence_present=True,
        detail="All assertions met",
    )
    assert diagnosis.detail == "All assertions met"
