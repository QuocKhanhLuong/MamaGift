"""Weighted selection score and hard gates.

A single scalar must never hide a catastrophic failure, so scoring has two layers:
weighted dimensions for comparison, and hard gates that disqualify a configuration
regardless of its average (`docs/03_DOCUMENT_PIPELINE.md` section 6).
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from .metrics import MetricResult

SCORING_VERSION = "1.0"

WEIGHTS: dict[str, float] = {
    "structure_correctness": 0.30,
    "critical_field_correctness": 0.25,
    "text_fidelity": 0.20,
    "scan_robustness": 0.10,
    "runtime_cost": 0.10,
    "integration_simplicity": 0.05,
}

STRUCTURE_METRICS = (
    "reading_order_accuracy",
    "heading_hierarchy_f1",
    "list_preservation",
    "table_structure_score",
    "header_footer_leakage",
    "provenance_completeness",
    "page_attribution_accuracy",
)

TEXT_METRICS = (
    "character_accuracy",
    "word_accuracy",
    "diacritic_preservation",
)

# Hard gate thresholds.
MIN_READING_ORDER = 0.70
MIN_PROVENANCE = 1.0


class GateFailure(StrEnum):
    READING_ORDER_CORRUPTION = "reading_order_corruption"
    PROVENANCE_LOSS = "provenance_loss"
    CRITICAL_FACT_ERROR = "critical_fact_error"
    PARSE_FAILURE = "parse_failure"


class DimensionScore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    weight: float
    value: float | None = None
    available: bool = True
    contributing_metrics: list[str] = Field(default_factory=list)


class ParserScore(BaseModel):
    """Aggregate score for one parser across the whole benchmark run."""

    model_config = ConfigDict(extra="forbid")

    parser: str
    scoring_version: str = SCORING_VERSION
    documents_attempted: int = 0
    documents_parsed: int = 0
    failure_rate: float = 0.0
    dimensions: list[DimensionScore] = Field(default_factory=list)
    weighted_score: float | None = None
    coverage: float = Field(default=0.0, ge=0.0, le=1.0)
    gate_failures: list[str] = Field(default_factory=list)
    disqualified: bool = False
    notes: list[str] = Field(default_factory=list)


def _mean_available(values: list[MetricResult]) -> float | None:
    usable = [result.value for result in values if result.available and result.value is not None]
    if not usable:
        return None
    return sum(usable) / len(usable)


def mean_of(metrics: dict[str, list[MetricResult]], names: tuple[str, ...]) -> float | None:
    collected: list[MetricResult] = []
    for name in names:
        collected.extend(metrics.get(name, []))
    return _mean_available(collected)


def runtime_score(
    seconds_per_page: float | None, best_seconds_per_page: float | None
) -> float | None:
    """Relative cost score: the fastest candidate in the run scores 1.0."""
    if seconds_per_page is None or best_seconds_per_page is None or seconds_per_page <= 0:
        return None
    return min(1.0, best_seconds_per_page / seconds_per_page)


def integration_simplicity(
    requires_gpu: bool,
    benefits_from_gpu: bool,
    provider_installed: bool,
) -> float:
    """Declared operational cost, not a measurement.

    This is the only dimension not derived from benchmark output, which is why it
    carries the smallest weight. It is stated explicitly so the ADR can show it was
    a judgement rather than evidence.
    """
    score = 1.0
    if requires_gpu:
        score -= 0.5
    elif benefits_from_gpu:
        score -= 0.2
    if not provider_installed:
        score -= 0.2
    return max(0.0, score)


def build_parser_score(
    parser: str,
    metrics: dict[str, list[MetricResult]],
    scan_metrics: dict[str, list[MetricResult]],
    critical_results: list[MetricResult],
    documents_attempted: int,
    documents_parsed: int,
    seconds_per_page: float | None,
    best_seconds_per_page: float | None,
    requires_gpu: bool,
    benefits_from_gpu: bool,
    provider_installed: bool,
    severity_3_failures: list[str],
) -> ParserScore:
    dimensions = [
        DimensionScore(
            name="structure_correctness",
            weight=WEIGHTS["structure_correctness"],
            value=mean_of(metrics, STRUCTURE_METRICS),
            contributing_metrics=list(STRUCTURE_METRICS),
        ),
        DimensionScore(
            name="critical_field_correctness",
            weight=WEIGHTS["critical_field_correctness"],
            value=_mean_available(critical_results),
            contributing_metrics=["critical_field_accuracy"],
        ),
        DimensionScore(
            name="text_fidelity",
            weight=WEIGHTS["text_fidelity"],
            value=mean_of(metrics, TEXT_METRICS),
            contributing_metrics=list(TEXT_METRICS),
        ),
        DimensionScore(
            name="scan_robustness",
            weight=WEIGHTS["scan_robustness"],
            value=mean_of(scan_metrics, STRUCTURE_METRICS + TEXT_METRICS),
            contributing_metrics=["scanned and mixed documents only"],
        ),
        DimensionScore(
            name="runtime_cost",
            weight=WEIGHTS["runtime_cost"],
            value=runtime_score(seconds_per_page, best_seconds_per_page),
            contributing_metrics=["seconds_per_page"],
        ),
        DimensionScore(
            name="integration_simplicity",
            weight=WEIGHTS["integration_simplicity"],
            value=integration_simplicity(requires_gpu, benefits_from_gpu, provider_installed),
            contributing_metrics=["declared, not measured"],
        ),
    ]

    for dimension in dimensions:
        dimension.available = dimension.value is not None

    available = [dimension for dimension in dimensions if dimension.available]
    total_weight = sum(dimension.weight for dimension in available)
    weighted_score = (
        None
        if total_weight == 0
        else sum((d.value or 0.0) * d.weight for d in available) / total_weight
    )

    gates: list[str] = []
    reading_order = mean_of(metrics, ("reading_order_accuracy",))
    if reading_order is not None and reading_order < MIN_READING_ORDER:
        gates.append(GateFailure.READING_ORDER_CORRUPTION.value)

    provenance = mean_of(metrics, ("provenance_completeness",))
    if provenance is not None and provenance < MIN_PROVENANCE:
        gates.append(GateFailure.PROVENANCE_LOSS.value)

    if severity_3_failures:
        gates.append(GateFailure.CRITICAL_FACT_ERROR.value)

    if documents_attempted and documents_parsed == 0:
        gates.append(GateFailure.PARSE_FAILURE.value)

    notes: list[str] = []
    if total_weight < 1.0:
        missing = [d.name for d in dimensions if not d.available]
        notes.append(f"score computed over {total_weight:.2f} of 1.00 weight; missing: {missing}")
    if severity_3_failures:
        notes.append(f"severity-3 field errors: {sorted(set(severity_3_failures))}")

    return ParserScore(
        parser=parser,
        documents_attempted=documents_attempted,
        documents_parsed=documents_parsed,
        failure_rate=(
            0.0
            if documents_attempted == 0
            else (documents_attempted - documents_parsed) / documents_attempted
        ),
        dimensions=dimensions,
        weighted_score=weighted_score,
        coverage=total_weight,
        gate_failures=gates,
        disqualified=bool(gates),
        notes=notes,
    )
