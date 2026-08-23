"""Hand-computed deterministic tests for the Phase 4 retrieval harness."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pytest

from mamagift_eval.retrieval_harness import (
    RetrievalEvaluationHarness,
    evaluate_retrieval,
    load_retrieval_cases,
)
from mamagift_eval.schemas import RetrievalQACase
from mamagift_retrieval.chunk import Chunk, ChunkType
from mamagift_retrieval.scope import EvidenceScope
from mamagift_retrieval.search import BM25LexicalRetriever, ScoredChunk

pytestmark = pytest.mark.unit

_FIXTURE = (
    Path(__file__).resolve().parents[1] / "fixtures" / "eval" / "retrieval_mini" / "cases.json"
)


def _chunk(
    chunk_id: str,
    text: str,
    *,
    document_id: str = "doc-mini",
    document_version: int = 1,
    parse_run_id: str = "run-mini-1",
    block_ids: list[str] | None = None,
    document_number: str | None = "01/SYNTHETIC",
    metadata: dict[str, Any] | None = None,
) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        document_id=document_id,
        parse_run_id=parse_run_id,
        document_version=document_version,
        document_type="synthetic_notice",
        document_number=document_number,
        chunk_type=ChunkType.PARAGRAPH,
        text=text,
        source_block_ids=block_ids or [f"block-{chunk_id}"],
        source_page_numbers=[1],
        metadata=metadata or {},
    )


def _case(
    *,
    expected_chunk_ids: list[str] | None = None,
    expected_block_ids: list[str] | None = None,
    document_id: str = "doc-mini",
    document_version: int = 1,
    parse_run_id: str = "run-mini-1",
    document_number: str | None = "01/SYNTHETIC",
    case_id: str = "case",
) -> RetrievalQACase:
    scope = {
        "family_id": "mamagift",
        "document_id": document_id,
        "document_version": str(document_version),
        "parse_run_id": parse_run_id,
    }
    if document_number is not None:
        scope["document_number"] = document_number
    return RetrievalQACase(
        case_id=case_id,
        question="Which synthetic block is relevant?",
        expected_document_ids=[document_id],
        expected_block_ids=expected_block_ids or [],
        expected_chunk_ids=expected_chunk_ids or [],
        required_metadata_scope=scope,
    )


def _hit(chunk: Chunk, score: float = 1.0) -> ScoredChunk:
    return ScoredChunk(chunk=chunk, score=score, rank=1, retriever="lexical")


class _StaticRetriever:
    def __init__(self, results: list[ScoredChunk]) -> None:
        self.results = results

    def search(
        self,
        query: str,
        *,
        scope: EvidenceScope,
        top_k: int,
    ) -> list[ScoredChunk]:
        del query, scope
        return self.results[:top_k]


def test_recall_mrr_and_ndcg_are_hand_computable() -> None:
    case = _case(expected_chunk_ids=["good-1", "good-2"], case_id="ranked")
    results = [
        _hit(_chunk("irrelevant", "unrelated")),
        _hit(_chunk("good-1", "target one")),
        _hit(_chunk("good-1", "target one")),
        _hit(_chunk("good-2", "target two")),
    ]

    report = evaluate_retrieval([case], _StaticRetriever(results))
    result = report.cases[0]

    assert result.recall_at_1 == 0.0
    assert result.recall_at_3 == pytest.approx(0.5)
    assert result.recall_at_5 == 1.0
    assert result.recall_at_10 == 1.0
    assert result.mrr == pytest.approx(0.5)
    expected_ndcg = (1 / math.log2(3) + 1 / math.log2(5)) / (1 + 1 / math.log2(3))
    assert result.ndcg == pytest.approx(expected_ndcg)


def test_ndcg_penalizes_an_expected_chunk_that_is_not_retrieved() -> None:
    case = _case(expected_chunk_ids=["good", "absent"], case_id="partial-ndcg")
    result = evaluate_retrieval([case], _StaticRetriever([_hit(_chunk("good", "target"))])).cases[0]
    assert result.ndcg == pytest.approx(1.0 / (1.0 + 1.0 / math.log2(3)))


def test_exact_document_number_retrieval_requires_valid_provenance() -> None:
    case = _case(expected_chunk_ids=["good"], case_id="document-number")
    result = evaluate_retrieval([case], _StaticRetriever([_hit(_chunk("good", "target"))])).cases[0]
    assert result.exact_document_number_retrieval == 1.0

    wrong_number = _chunk("good", "target", document_number="99/FOREIGN")
    wrong = evaluate_retrieval([case], _StaticRetriever([_hit(wrong_number)])).cases[0]
    assert wrong.exact_document_number_retrieval == 0.0


def test_document_version_mismatch_is_a_miss_and_isolation_failure() -> None:
    case = _case(expected_chunk_ids=["answer"], case_id="stale-version")
    stale = _chunk("answer", "stale answer", document_version=2, parse_run_id="run-mini-1")
    result = evaluate_retrieval([case], _StaticRetriever([_hit(stale)])).cases[0]
    assert result.recall_at_10 == 0.0
    assert result.mrr == 0.0
    assert result.foreign_chunk_ids == ["answer"]
    assert result.metadata_version_isolation == 0.0


def test_parse_run_mismatch_is_a_miss_even_when_version_matches() -> None:
    case = _case(expected_chunk_ids=["answer"], case_id="stale-parse")
    stale = _chunk("answer", "stale parse", parse_run_id="run-mini-old")
    result = evaluate_retrieval([case], _StaticRetriever([_hit(stale)])).cases[0]
    assert result.recall_at_10 == 0.0
    assert result.metadata_version_isolation == 0.0


def test_empty_result_set_scores_zero_without_dividing_by_zero() -> None:
    case = _case(expected_chunk_ids=["missing"], case_id="empty")
    result = evaluate_retrieval([case], _StaticRetriever([])).cases[0]
    assert result.recall_at_1 == 0.0
    assert result.mrr == 0.0
    assert result.ndcg == 0.0
    assert result.metadata_version_isolation == 1.0


def test_duplicate_result_ids_do_not_inflate_recall() -> None:
    case = _case(expected_chunk_ids=["good", "also-good"], case_id="duplicate")
    results = [_hit(_chunk("good", "target")), _hit(_chunk("good", "target"))]
    result = evaluate_retrieval([case], _StaticRetriever(results)).cases[0]
    assert result.recall_at_10 == pytest.approx(0.5)
    assert result.retrieved_chunk_ids == ["good"]
    assert result.duplicate_chunk_ids == ["good"]


def test_expected_chunk_absent_is_zero_even_if_document_is_retrieved() -> None:
    case = _case(expected_chunk_ids=["absent"], case_id="absent")
    result = evaluate_retrieval(
        [case], _StaticRetriever([_hit(_chunk("other", "same document"))])
    ).cases[0]
    assert result.recall_at_10 == 0.0
    assert result.exact_document_number_retrieval == 1.0


def test_expected_blocks_are_scored_by_source_block_id() -> None:
    case = _case(expected_block_ids=["block-answer"], case_id="blocks")
    answer = _chunk("chunk-answer", "target", block_ids=["block-answer"])
    result = evaluate_retrieval([case], _StaticRetriever([_hit(answer)])).cases[0]
    assert result.recall_at_1 == 1.0
    assert result.relevant_chunk_or_block_ids == ["block-answer"]


def test_harness_runs_in_repo_lexical_retriever_and_emits_both_reports() -> None:
    case = _case(expected_chunk_ids=["good"], case_id="lexical")
    scope = EvidenceScope(
        family_id="mamagift",
        document_id="doc-mini",
        document_version=1,
        parse_run_id="run-mini-1",
    )
    retriever = BM25LexicalRetriever.from_chunks(
        [_chunk("good", "synthetic target block"), _chunk("other", "different text")],
        scope=scope,
    )
    report = RetrievalEvaluationHarness(retriever, name="bm25-mini").run([case])
    assert report.metrics.recall_at_10 == 1.0
    assert '"recall_at_10": 1.0' in report.to_json()
    assert "# Retrieval evaluation" in report.to_markdown()


def test_fixture_cases_are_synthetic_and_loadable() -> None:
    cases = load_retrieval_cases(_FIXTURE)
    assert len(cases) >= 2
    assert all(case.required_metadata_scope["family_id"] == "mamagift" for case in cases)
    assert all("synthetic" in case.question.lower() for case in cases)


def test_missing_provenance_pins_are_rejected() -> None:
    case = RetrievalQACase(
        case_id="unbound",
        question="question",
        expected_document_ids=["doc-mini"],
    )
    with pytest.raises(ValueError, match="document_version and parse_run_id"):
        evaluate_retrieval([case], _StaticRetriever([]))


def test_non_authoritative_family_is_rejected() -> None:
    case = _case(case_id="wrong-family")
    case = case.model_copy(
        update={
            "required_metadata_scope": {
                **case.required_metadata_scope,
                "family_id": "foreign-family",
            }
        }
    )
    with pytest.raises(ValueError, match="unsupported family_id"):
        evaluate_retrieval([case], _StaticRetriever([]))


def test_human_report_contains_latency_and_isolation() -> None:
    case = _case(expected_chunk_ids=["good"], case_id="report")
    report = evaluate_retrieval([case], _StaticRetriever([_hit(_chunk("good", "target"))]))
    markdown = report.to_markdown()
    assert "Metadata/version isolation" in markdown
    assert "Mean latency (ms)" in markdown
    assert report.metrics.mean_latency_ms >= 0.0


def test_case_loader_rejects_duplicate_ids(tmp_path: Path) -> None:
    payload = [_case(case_id="same").model_dump(), _case(case_id="same").model_dump()]
    path = tmp_path / "duplicate.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate case_id"):
        load_retrieval_cases(path)
