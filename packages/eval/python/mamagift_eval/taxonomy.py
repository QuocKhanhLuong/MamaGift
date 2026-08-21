"""Failure-analysis taxonomy for evaluation diagnosis (Phase 3.5).

Encodes the diagnosis path this phase's goal requires:

    wrong answer/fact
      -> was correct evidence present?
          -> no: parser / chunking / retrieval / metadata-version failure
          -> yes: generation/grounding failure

Only the parser/chunking/retrieval/metadata-version branch is executable in this
phase — there is no generation step yet, so `GENERATION_GROUNDING_FAILURE` is a
label this phase can assign to record "not applicable to this phase's own code",
never a bug this phase's code path can itself produce.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

_UPSTREAM_STAGES = frozenset(
    {
        "parser_failure",
        "chunking_failure",
        "retrieval_failure",
        "metadata_version_failure",
    }
)


class FailureLabel(StrEnum):
    NONE = "none"
    PARSER_FAILURE = "parser_failure"
    CHUNKING_FAILURE = "chunking_failure"
    RETRIEVAL_FAILURE = "retrieval_failure"
    METADATA_VERSION_FAILURE = "metadata_version_failure"
    GENERATION_GROUNDING_FAILURE = "generation_grounding_failure"


class FailureDiagnosis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    answer_or_fact_correct: bool
    evidence_present: bool
    label: FailureLabel
    detail: str = ""


def classify_failure(
    *,
    case_id: str,
    answer_or_fact_correct: bool,
    evidence_present: bool,
    evidence_stage: FailureLabel | None = None,
    detail: str = "",
) -> FailureDiagnosis:
    """Apply the diagnosis path deterministically.

    `evidence_stage` names which Phase 3.5 stage failed to surface evidence
    (`PARSER_FAILURE`, `CHUNKING_FAILURE`, `RETRIEVAL_FAILURE` or
    `METADATA_VERSION_FAILURE`) and is required when `evidence_present` is False.
    When `evidence_present` is True and the fact is still wrong, the label is
    `GENERATION_GROUNDING_FAILURE` regardless of `evidence_stage`, since Phase 3.5
    has no generation step to attribute the failure to more specifically.
    """
    if answer_or_fact_correct:
        return FailureDiagnosis(
            case_id=case_id,
            answer_or_fact_correct=True,
            evidence_present=evidence_present,
            label=FailureLabel.NONE,
            detail=detail,
        )

    if not evidence_present:
        if evidence_stage is None or evidence_stage.value not in _UPSTREAM_STAGES:
            raise ValueError(
                "evidence_stage must be one of parser/chunking/retrieval/"
                "metadata_version failure when evidence_present is False"
            )
        return FailureDiagnosis(
            case_id=case_id,
            answer_or_fact_correct=False,
            evidence_present=False,
            label=evidence_stage,
            detail=detail,
        )

    return FailureDiagnosis(
        case_id=case_id,
        answer_or_fact_correct=False,
        evidence_present=True,
        label=FailureLabel.GENERATION_GROUNDING_FAILURE,
        detail=detail,
    )
