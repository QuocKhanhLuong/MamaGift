"""Tests for deterministic per-question failure analysis."""

from __future__ import annotations

import json

import pytest

from mamagift_eval import (
    FailureAnalysisCase,
    FailureLabel,
    analyze_failure,
    analyze_failures,
)
from mamagift_retrieval.budget import BudgetBreakdown
from mamagift_retrieval.chunk import Chunk, ChunkType
from mamagift_retrieval.evidence import Evidence, EvidenceSet
from mamagift_retrieval.scope import EvidenceScope

pytestmark = pytest.mark.unit


SCOPE = EvidenceScope(
    family_id="family-1",
    document_id="doc-1",
    document_version=2,
    parse_run_id="run-2",
)


def _chunk(
    *,
    text: str,
    document_id: str = "doc-1",
    document_version: int = 2,
    parse_run_id: str = "run-2",
    chunk_id: str = "chunk-1",
    block_id: str = "block-1",
) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        document_id=document_id,
        document_version=document_version,
        parse_run_id=parse_run_id,
        chunk_type=ChunkType.PARAGRAPH,
        text=text,
        source_block_ids=[block_id],
        source_page_numbers=[1],
    )


def _case(**kwargs: object) -> FailureAnalysisCase:
    values: dict[str, object] = {
        "case_id": "q-1",
        "answer_or_fact_correct": False,
        "scope": SCOPE,
        "retrieved_context": [_chunk(text="Nhiệm vụ giao cho Phòng Giáo dục.")],
        "expected_evidence_texts": ["Nhiệm vụ giao cho Phòng Giáo dục."],
    }
    values.update(kwargs)
    return FailureAnalysisCase.model_validate(values)


def test_wrong_answer_with_in_scope_evidence_is_generation_failure() -> None:
    diagnosis = analyze_failure(_case())
    assert diagnosis.evidence_present is True
    assert diagnosis.label == FailureLabel.GENERATION_GROUNDING_FAILURE


def test_wrong_answer_with_no_context_is_retrieval_failure() -> None:
    diagnosis = analyze_failure(_case(retrieved_context=[], expected_evidence_texts=["evidence"]))
    assert diagnosis.evidence_present is False
    assert diagnosis.label == FailureLabel.RETRIEVAL_FAILURE
    assert "narrowed to retrieval" in diagnosis.detail


@pytest.mark.parametrize(
    "stage",
    [
        FailureLabel.PARSER_FAILURE,
        FailureLabel.CHUNKING_FAILURE,
        FailureLabel.RETRIEVAL_FAILURE,
        FailureLabel.METADATA_VERSION_FAILURE,
    ],
)
def test_each_upstream_stage_is_preserved_when_supplied(stage: FailureLabel) -> None:
    diagnosis = analyze_failure(_case(evidence_stage=stage, retrieved_context=[]))
    assert diagnosis.label == stage
    assert diagnosis.evidence_present is False
    assert "supplied by evaluation data" in diagnosis.detail


def test_textually_present_wrong_version_is_metadata_version_not_generation() -> None:
    diagnosis = analyze_failure(
        _case(
            retrieved_context=[
                _chunk(text="Nhiệm vụ giao cho Phòng Giáo dục.", document_version=1)
            ],
        )
    )
    assert diagnosis.evidence_present is False
    assert diagnosis.label == FailureLabel.METADATA_VERSION_FAILURE
    assert "metadata-version" in diagnosis.detail


def test_textually_present_wrong_parse_run_is_metadata_version_not_generation() -> None:
    diagnosis = analyze_failure(
        _case(
            retrieved_context=[
                _chunk(text="Nhiệm vụ giao cho Phòng Giáo dục.", parse_run_id="old-run")
            ],
        )
    )
    assert diagnosis.evidence_present is False
    assert diagnosis.label == FailureLabel.METADATA_VERSION_FAILURE


def test_wrong_provenance_expected_chunk_id_is_metadata_version() -> None:
    diagnosis = analyze_failure(
        _case(
            retrieved_context=[
                _chunk(
                    text="changed text",
                    document_version=1,
                    chunk_id="expected-chunk",
                )
            ],
            expected_evidence_texts=["expected text"],
            expected_chunk_ids=["expected-chunk"],
        )
    )
    assert diagnosis.label == FailureLabel.METADATA_VERSION_FAILURE
    assert diagnosis.evidence_present is False


def test_foreign_document_text_is_not_in_scope_evidence() -> None:
    diagnosis = analyze_failure(
        _case(
            retrieved_context=[
                _chunk(text="Nhiệm vụ giao cho Phòng Giáo dục.", document_id="other-doc")
            ]
        )
    )
    assert diagnosis.label == FailureLabel.METADATA_VERSION_FAILURE
    assert diagnosis.evidence_present is False


def test_evidence_set_scope_must_agree_with_requested_scope() -> None:
    context = EvidenceSet(
        scope=SCOPE.model_copy(update={"parse_run_id": "old-run"}),
        evidence=[
            Evidence(
                citation_id="c1",
                chunk_id="chunk-1",
                document_id="doc-1",
                parse_run_id="old-run",
                document_version=2,
                page_numbers=[1],
                source_block_ids=["block-1"],
                section_path=[],
                text="expected",
            )
        ],
        budget=BudgetBreakdown(categories=[]),
        query_id="query-1",
    )
    with pytest.raises(ValueError, match="EvidenceSet scope"):
        analyze_failure(_case(retrieved_context=context))


def test_parser_and_chunking_can_be_narrowed_from_in_scope_ids() -> None:
    parser = analyze_failure(
        _case(
            retrieved_context=[_chunk(text="different", block_id="expected-block")],
            expected_evidence_texts=["expected"],
            expected_source_block_ids=["expected-block"],
        )
    )
    chunking = analyze_failure(
        _case(
            retrieved_context=[_chunk(text="different", chunk_id="expected-chunk")],
            expected_evidence_texts=["expected"],
            expected_chunk_ids=["expected-chunk"],
        )
    )
    assert parser.label == FailureLabel.PARSER_FAILURE
    assert chunking.label == FailureLabel.CHUNKING_FAILURE


def test_correct_answer_has_no_failure() -> None:
    diagnosis = analyze_failure(_case(answer_or_fact_correct=True))
    assert diagnosis.label == FailureLabel.NONE


def test_batch_has_machine_and_human_readable_output_and_accepts_empty_input() -> None:
    empty = analyze_failures([])
    assert empty.cases == []
    assert json.loads(empty.to_json()) == {"cases": []}
    assert "Cases: 0" in empty.to_markdown()

    report = analyze_failures([_case()])
    assert report.diagnoses == report.cases
    assert json.loads(report.to_json())["cases"][0]["label"] == "generation_grounding_failure"
    assert "q-1" in report.to_markdown()


def test_missing_expected_evidence_contract_is_rejected() -> None:
    with pytest.raises(ValueError, match="expected_evidence"):
        analyze_failure(
            _case(expected_evidence_texts=[], expected_chunk_ids=[], expected_source_block_ids=[])
        )
