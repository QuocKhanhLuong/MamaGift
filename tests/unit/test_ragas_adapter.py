"""Offline-only contract tests for the optional RAGAS adapter."""

from __future__ import annotations

import importlib
import sys
from collections.abc import Mapping, Sequence

import pytest

from mamagift_eval.ragas_adapter import (
    RAGAS_METRICS,
    RagasAdapter,
    RagasAvailableResult,
    RagasEvaluationResult,
    RagasMetricName,
    RagasUnavailableResult,
)
from mamagift_eval.schemas import RetrievalQACase
from mamagift_rag.schema import ModelRef, QaAnswer, RetrievalRef
from mamagift_retrieval.budget import BudgetBreakdown
from mamagift_retrieval.evidence import Evidence, EvidenceSet
from mamagift_retrieval.scope import EvidenceScope

pytestmark = pytest.mark.unit


_SCOPE = EvidenceScope(
    family_id="mamagift",
    document_id="doc-1",
    document_version=1,
    parse_run_id="parse-1",
)


def _case() -> RetrievalQACase:
    return RetrievalQACase(
        case_id="case-1",
        question="Đơn vị nào chủ trì nhiệm vụ?",
        expected_document_ids=["doc-1"],
        expected_block_ids=["block-1"],
        required_metadata_scope={
            "family_id": "mamagift",
            "document_id": "doc-1",
            "document_version": "1",
            "parse_run_id": "parse-1",
        },
    )


def _answer() -> QaAnswer:
    return QaAnswer(
        answer="Đơn vị A chủ trì.",
        status="answered",
        citations=[],
        retrieval=RetrievalRef(query_id="query-1"),
        model=ModelRef(provider="fake", model="fake", version="1"),
    )


def _evidence_set() -> EvidenceSet:
    return EvidenceSet(
        scope=_SCOPE,
        evidence=[
            Evidence(
                citation_id="c1",
                chunk_id="chunk-1",
                document_id="doc-1",
                parse_run_id="parse-1",
                document_version=1,
                page_numbers=[1],
                source_block_ids=["block-1"],
                section_path=["Điều 1"],
                text="Đơn vị A chủ trì nhiệm vụ.",
            )
        ],
        budget=BudgetBreakdown(categories=[]),
        query_id="query-1",
    )


def _result(adapter: RagasAdapter) -> RagasEvaluationResult:
    return adapter.evaluate([_case()], [_answer()], [_evidence_set()])


def test_missing_library_is_unavailable_without_importing_ragas() -> None:
    def missing_library() -> object:
        raise ModuleNotFoundError("No module named 'ragas'")

    result = _result(RagasAdapter(api_key="offline-test", backend_factory=missing_library))

    assert all(isinstance(item, RagasUnavailableResult) for item in result.metrics.values())
    assert all("ragas" in item.reason.lower() for item in result.metrics.values())
    assert "ragas" not in sys.modules


def test_absent_api_key_is_unavailable_before_backend_loading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("RAGAS_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    def must_not_load() -> object:
        raise AssertionError("backend must not load without an API key")

    result = _result(RagasAdapter(backend_factory=must_not_load))

    assert all(isinstance(item, RagasUnavailableResult) for item in result.metrics.values())
    assert all(item.reason == "RAGAS API key is absent" for item in result.metrics.values())


def test_failing_backend_call_is_unavailable_not_a_score() -> None:
    class FailingBackend:
        def evaluate(self, samples: Sequence[Mapping[str, object]]) -> Mapping[str, object]:
            raise RuntimeError("offline evaluator failed")

    result = _result(RagasAdapter(backend=FailingBackend()))

    assert all(isinstance(item, RagasUnavailableResult) for item in result.metrics.values())
    assert all("offline evaluator failed" in item.reason for item in result.metrics.values())
    assert all(item.value is None for item in result.metrics.values())


def test_unavailable_is_distinct_from_a_real_zero_score() -> None:
    class ZeroBackend:
        def evaluate(self, samples: Sequence[Mapping[str, object]]) -> Mapping[str, object]:
            return {metric.value: 0.0 for metric in RAGAS_METRICS}

    available = _result(RagasAdapter(backend=ZeroBackend()))
    unavailable = _result(
        RagasAdapter(backend_factory=lambda: (_ for _ in ()).throw(RuntimeError("no")), api_key="x")
    )

    assert all(isinstance(item, RagasAvailableResult) for item in available.metrics.values())
    assert all(item.value == 0.0 for item in available.metrics.values())
    assert all(isinstance(item, RagasUnavailableResult) for item in unavailable.metrics.values())
    assert all(item.value is None for item in unavailable.metrics.values())
    assert (
        available.metric(RagasMetricName.FAITHFULNESS).status
        != unavailable.metric(RagasMetricName.FAITHFULNESS).status
    )


def test_stub_success_maps_all_four_metrics_and_reuses_eval_contracts() -> None:
    expected = {
        "faithfulness": 0.11,
        "answer_relevancy": 0.22,
        "context_precision": 0.33,
        "context_recall": 0.44,
    }

    class StubBackend:
        def evaluate(self, samples: Sequence[Mapping[str, object]]) -> Mapping[str, object]:
            assert len(samples) == 1
            assert samples[0]["user_input"] == _case().question
            assert samples[0]["response"] == _answer().answer
            assert samples[0]["retrieved_contexts"] == [_evidence_set().evidence[0].text]
            return expected

    result = _result(RagasAdapter(backend=StubBackend()))

    assert [result.metric(metric).value for metric in RAGAS_METRICS] == list(expected.values())
    assert all(result.metric(metric).status == "available" for metric in RAGAS_METRICS)


@pytest.mark.parametrize("bad_value", [None, object(), "not-a-number", 1.1, float("nan")])
def test_invalid_or_missing_scores_are_unavailable(bad_value: object) -> None:
    class InvalidBackend:
        def evaluate(self, samples: Sequence[Mapping[str, object]]) -> Mapping[str, object]:
            return {
                "faithfulness": bad_value,
                "answer_relevancy": 0.5,
                "context_precision": 0.5,
                "context_recall": 0.5,
            }

    result = _result(RagasAdapter(backend=InvalidBackend()))

    faithfulness = result.metric(RagasMetricName.FAITHFULNESS)
    assert isinstance(faithfulness, RagasUnavailableResult)
    assert faithfulness.value is None


def test_tests_do_not_import_ragas_or_touch_network() -> None:
    module = importlib.import_module("mamagift_eval.ragas_adapter")
    assert module.__name__ == "mamagift_eval.ragas_adapter"
    assert "ragas" not in sys.modules
    assert "datasets" not in sys.modules
