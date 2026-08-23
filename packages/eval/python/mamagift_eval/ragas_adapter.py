"""Optional, offline-only RAGAS evaluation.

RAGAS is deliberately kept behind :class:`RagasBackend`.  The normal package
and deterministic test suite do not import RAGAS (or its optional dependencies)
at all.  An operator can opt into the lazy SDK loader for an offline run; any
missing dependency, missing API key, malformed result, or failed call is
reported as ``unavailable`` rather than being converted into a score.
"""

from __future__ import annotations

import importlib
import math
import os
from collections.abc import Callable, Iterable, Mapping, Sequence
from enum import StrEnum
from typing import Literal, Protocol, TypeAlias, cast

from pydantic import BaseModel, ConfigDict, Field

from mamagift_rag.schema import QaAnswer
from mamagift_retrieval.evidence import EvidenceSet

from .schemas import RetrievalQACase


class RagasMetricName(StrEnum):
    """The four RAGAS metrics exposed by the adapter."""

    FAITHFULNESS = "faithfulness"
    ANSWER_RELEVANCY = "answer_relevancy"
    CONTEXT_PRECISION = "context_precision"
    CONTEXT_RECALL = "context_recall"


RAGAS_METRICS: tuple[RagasMetricName, ...] = (
    RagasMetricName.FAITHFULNESS,
    RagasMetricName.ANSWER_RELEVANCY,
    RagasMetricName.CONTEXT_PRECISION,
    RagasMetricName.CONTEXT_RECALL,
)


class RagasAvailableResult(BaseModel):
    """One measured metric, including a real score (which may be ``0.0``)."""

    model_config = ConfigDict(extra="forbid")

    metric: RagasMetricName
    status: Literal["available"] = "available"
    value: float = Field(ge=0.0, le=1.0)
    reason: None = None


class RagasUnavailableResult(BaseModel):
    """One metric that could not be measured.

    ``value`` is intentionally typed as ``None`` so unavailable cannot be
    confused with a measured score of ``0.0``.
    """

    model_config = ConfigDict(extra="forbid")

    metric: RagasMetricName
    status: Literal["unavailable"] = "unavailable"
    value: None = None
    reason: str = Field(min_length=1)


RagasMetricResult: TypeAlias = RagasAvailableResult | RagasUnavailableResult


class RagasEvaluationResult(BaseModel):
    """Stable result containing every requested metric exactly once."""

    model_config = ConfigDict(extra="forbid")

    metrics: dict[RagasMetricName, RagasMetricResult]

    def metric(self, name: RagasMetricName | str) -> RagasMetricResult:
        """Return a metric result by enum or wire-format name."""
        return self.metrics[RagasMetricName(name)]


class RagasBackend(Protocol):
    """Narrow seam for a real RAGAS runner or a deterministic test stub."""

    def evaluate(self, samples: Sequence[Mapping[str, object]]) -> Mapping[str, object]:
        """Evaluate rows and return raw metric values keyed by metric name."""


class _DatasetFactory(Protocol):
    @classmethod
    def from_list(cls, rows: list[dict[str, object]]) -> object: ...


class _RagasSdkBackend:
    """Small dynamic wrapper around the optional RAGAS and datasets packages."""

    def __init__(
        self,
        evaluate: Callable[..., object],
        dataset_factory: _DatasetFactory,
        metric_objects: Sequence[object],
    ) -> None:
        self._evaluate = evaluate
        self._dataset_factory = dataset_factory
        self._metric_objects = tuple(metric_objects)

    def evaluate(self, samples: Sequence[Mapping[str, object]]) -> Mapping[str, object]:
        rows = [dict(sample) for sample in samples]
        dataset = self._dataset_factory.from_list(rows)
        raw_result = self._evaluate(dataset, metrics=list(self._metric_objects))
        if not isinstance(raw_result, Mapping):
            raise TypeError("RAGAS returned a non-mapping result")
        return cast(Mapping[str, object], raw_result)


def _load_ragas_backend() -> RagasBackend:
    """Load RAGAS only when an explicitly requested offline run needs it."""
    ragas_module = importlib.import_module("ragas")
    metrics_module = importlib.import_module("ragas.metrics")
    datasets_module = importlib.import_module("datasets")

    evaluate = getattr(ragas_module, "evaluate", None)
    dataset_factory = getattr(datasets_module, "Dataset", None)
    if not callable(evaluate) or dataset_factory is None:
        raise ImportError("installed RAGAS dependencies do not expose evaluate/Dataset")
    from_list = getattr(dataset_factory, "from_list", None)
    if not callable(from_list):
        raise ImportError("installed datasets dependency does not expose Dataset.from_list")

    metric_objects: list[object] = []
    for metric in RAGAS_METRICS:
        metric_object = getattr(metrics_module, metric.value, None)
        if metric_object is None:
            raise ImportError(f"installed RAGAS does not expose {metric.value}")
        metric_objects.append(metric_object)

    return _RagasSdkBackend(
        cast(Callable[..., object], evaluate),
        cast(_DatasetFactory, dataset_factory),
        metric_objects,
    )


def _unavailable(reason: str) -> RagasEvaluationResult:
    return RagasEvaluationResult(
        metrics={
            metric: RagasUnavailableResult(metric=metric, reason=reason) for metric in RAGAS_METRICS
        }
    )


def _samples(
    cases: Sequence[RetrievalQACase],
    answers: Sequence[QaAnswer],
    evidence_sets: Sequence[EvidenceSet],
    reference_answers: Sequence[str] | None,
) -> list[dict[str, object]]:
    if not (len(cases) == len(answers) == len(evidence_sets)):
        raise ValueError("cases, answers, and evidence_sets must have the same length")
    if reference_answers is not None and len(reference_answers) != len(cases):
        raise ValueError("reference_answers must have the same length as cases")

    rows: list[dict[str, object]] = []
    for index, (case, answer, evidence_set) in enumerate(
        zip(cases, answers, evidence_sets, strict=True)
    ):
        row: dict[str, object] = {
            "user_input": case.question,
            "response": answer.answer,
            "retrieved_contexts": [item.text for item in evidence_set.evidence],
        }
        if reference_answers is not None:
            row["reference"] = reference_answers[index]
        rows.append(row)
    return rows


def _map_scores(raw_scores: Mapping[str, object]) -> RagasEvaluationResult:
    results: dict[RagasMetricName, RagasMetricResult] = {}
    for metric in RAGAS_METRICS:
        raw_value = raw_scores.get(metric.value)
        if raw_value is None or isinstance(raw_value, bool):
            results[metric] = RagasUnavailableResult(
                metric=metric,
                reason=f"RAGAS did not return {metric.value}",
            )
            continue
        if not isinstance(raw_value, (str, int, float)):
            results[metric] = RagasUnavailableResult(
                metric=metric,
                reason=f"RAGAS returned a non-numeric {metric.value} value",
            )
            continue
        try:
            value = float(raw_value)
        except (TypeError, ValueError, OverflowError):
            results[metric] = RagasUnavailableResult(
                metric=metric,
                reason=f"RAGAS returned a non-numeric {metric.value} value",
            )
            continue
        if not math.isfinite(value) or not 0.0 <= value <= 1.0:
            results[metric] = RagasUnavailableResult(
                metric=metric,
                reason=f"RAGAS returned an invalid {metric.value} value",
            )
            continue
        results[metric] = RagasAvailableResult(metric=metric, value=value)
    return RagasEvaluationResult(metrics=results)


class RagasAdapter:
    """Evaluate generated answers with an optional, offline RAGAS backend.

    ``backend`` is the test seam and may be a deterministic stub.  Without an
    injected backend, the adapter checks for an API key before lazily importing
    RAGAS.  It performs no network operation itself.
    """

    def __init__(
        self,
        *,
        backend: RagasBackend | None = None,
        api_key: str | None = None,
        backend_factory: Callable[[], RagasBackend] = _load_ragas_backend,
    ) -> None:
        self._backend = backend
        self._api_key = api_key
        self._backend_factory = backend_factory

    def evaluate(
        self,
        cases: Iterable[RetrievalQACase],
        answers: Iterable[QaAnswer],
        evidence_sets: Iterable[EvidenceSet],
        *,
        reference_answers: Iterable[str] | None = None,
    ) -> RagasEvaluationResult:
        """Return four scores or four explicit unavailable outcomes."""
        if self._backend is None and not (
            self._api_key or os.getenv("RAGAS_API_KEY") or os.getenv("OPENAI_API_KEY")
        ):
            return _unavailable("RAGAS API key is absent")

        try:
            case_list = list(cases)
            answer_list = list(answers)
            evidence_list = list(evidence_sets)
            reference_list = None if reference_answers is None else list(reference_answers)
            rows = _samples(case_list, answer_list, evidence_list, reference_list)
            backend = self._backend or self._backend_factory()
            return _map_scores(backend.evaluate(rows))
        except Exception as exc:
            return _unavailable(f"RAGAS evaluation failed: {exc}")


__all__ = [
    "RAGAS_METRICS",
    "RagasAdapter",
    "RagasAvailableResult",
    "RagasBackend",
    "RagasEvaluationResult",
    "RagasMetricName",
    "RagasMetricResult",
    "RagasUnavailableResult",
]
