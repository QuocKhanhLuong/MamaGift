"""Benchmark execution.

One parser failing must never abort the rest of the run: a candidate that crashes on
a hard document is itself a benchmark result, and the remaining candidates still need
their numbers (`docs/04_PHASE_PLAN.md`, Phase 1 benchmark harness tests).
"""

from __future__ import annotations

import json
import platform
import resource
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from mamagift_docpipe.adapters import build_adapter
from mamagift_docpipe.canonical import CanonicalDocument
from mamagift_docpipe.errors import ParserError, ParserErrorCode, ParserErrorModel
from mamagift_docpipe.interface import ParseRequest
from mamagift_docpipe.normalize import normalize_provider_result
from mamagift_docpipe.router import InspectionReport, Route, inspect_pdf

from .critical_fields import (
    EXTRACTOR_NAME,
    EXTRACTOR_VERSION,
    extract_critical_fields,
    severity_3_failures,
)
from .manifest import ManifestEntry, load_ground_truth
from .metrics import (
    METRICS_VERSION,
    MetricResult,
    critical_field_accuracy,
    evaluate_document,
    route_accuracy,
)
from .scoring import build_parser_score

RUNNER_VERSION = "1.0"


class DocumentRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parser: str
    document_id: str
    status: str
    route_expected: str
    route_actual: str | None = None
    page_count: int | None = None
    duration_ms: float | None = None
    seconds_per_page: float | None = None
    peak_rss_mb: float | None = None
    error: ParserErrorModel | None = None
    metrics: dict[str, MetricResult] = Field(default_factory=dict)
    critical_field_metric: MetricResult | None = None
    wrong_critical_fields: list[str] = Field(default_factory=list)
    severity_3_fields: list[str] = Field(default_factory=list)
    extracted_critical_fields: dict[str, str | None] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class RunMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    started_at: str
    finished_at: str | None = None
    runner_version: str = RUNNER_VERSION
    metrics_version: str = METRICS_VERSION
    manifest: str
    parsers: list[str]
    adapters: dict[str, dict[str, Any]] = Field(default_factory=dict)
    environment: dict[str, str] = Field(default_factory=dict)
    git_commit: str | None = None


def _git_commit(root: Path) -> str | None:
    try:
        return (
            subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=root, stderr=subprocess.DEVNULL
            )
            .decode()
            .strip()
        )
    except Exception:
        return None


def _environment() -> dict[str, str]:
    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor() or "unknown",
    }


def _peak_rss_mb() -> float:
    usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # Linux reports kibibytes, macOS reports bytes.
    return usage / 1024.0 if sys.platform.startswith("linux") else usage / (1024.0 * 1024.0)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def run_document(
    parser_name: str,
    entry: ManifestEntry,
    inspection: InspectionReport,
    root: Path,
    output_dir: Path,
    adapter_config: dict[str, Any] | None = None,
) -> DocumentRun:
    """Parse, normalize, score and persist artifacts for one (parser, document) pair."""
    artifact_dir = output_dir / "parsers" / parser_name / entry.document_id
    run = DocumentRun(
        parser=parser_name,
        document_id=entry.document_id,
        status="failed",
        route_expected=entry.route_label.value,
        route_actual=inspection.route.value,
        page_count=inspection.page_count,
    )

    try:
        adapter = build_adapter(parser_name, adapter_config)
    except KeyError as exc:
        run.error = ParserErrorModel(
            code=ParserErrorCode.UNSUPPORTED_INPUT,
            message=str(exc),
            retryable=False,
            parser_name=parser_name,
        )
        _write_json(artifact_dir / "metrics.json", run.model_dump(mode="json"))
        return run

    rss_before = _peak_rss_mb()
    start = time.perf_counter()

    try:
        provider_result = adapter.parse(
            ParseRequest(document_id=entry.document_id, pdf_path=entry.resolve_path(root))
        )
    except ParserError as exc:
        run.error = exc.model
        run.duration_ms = (time.perf_counter() - start) * 1000.0
        _write_json(artifact_dir / "metrics.json", run.model_dump(mode="json"))
        return run
    except Exception as exc:  # a crashing candidate is a result, not a runner failure
        run.error = ParserErrorModel(
            code=ParserErrorCode.PROVIDER_FAILURE,
            message=f"{type(exc).__name__}: {exc}",
            retryable=False,
            parser_name=parser_name,
        )
        run.duration_ms = (time.perf_counter() - start) * 1000.0
        _write_json(artifact_dir / "metrics.json", run.model_dump(mode="json"))
        return run

    run.duration_ms = provider_result.duration_ms
    run.peak_rss_mb = max(0.0, _peak_rss_mb() - rss_before)
    _write_json(
        artifact_dir / "provider-output" / "result.json",
        provider_result.model_dump(mode="json"),
    )

    try:
        document = normalize_provider_result(provider_result, inspection)
    except Exception as exc:
        run.error = ParserErrorModel(
            code=ParserErrorCode.NORMALIZATION_FAILURE,
            message=f"{type(exc).__name__}: {exc}",
            retryable=False,
            parser_name=parser_name,
        )
        _write_json(artifact_dir / "metrics.json", run.model_dump(mode="json"))
        return run

    _write_json(artifact_dir / "canonical.json", document.model_dump(mode="json"))

    run.status = "ok"
    run.page_count = len(document.pages)
    run.seconds_per_page = (
        None if not document.pages else (run.duration_ms or 0.0) / 1000.0 / len(document.pages)
    )
    run.warnings = list(provider_result.warnings)
    run.metrics = {
        "route_accuracy": route_accuracy(inspection.route.value, entry.route_label.value)
    }

    truth_path = entry.resolve_ground_truth(root)
    if truth_path is not None and truth_path.is_file():
        truth = load_ground_truth(truth_path)
        run.metrics.update(evaluate_document(document, truth))

        extracted = extract_critical_fields(document)
        run.extracted_critical_fields = extracted
        metric, wrong = critical_field_accuracy(extracted, truth)
        run.critical_field_metric = metric
        run.wrong_critical_fields = wrong
        run.severity_3_fields = severity_3_failures(truth.critical_fields, wrong)

    _write_json(artifact_dir / "metrics.json", run.model_dump(mode="json"))
    return run


def run_benchmark(
    entries: list[ManifestEntry],
    parsers: list[str],
    root: Path,
    output_dir: Path,
    manifest_path: str,
    adapter_configs: dict[str, dict[str, Any]] | None = None,
) -> tuple[RunMetadata, list[DocumentRun], list[Any]]:
    """Run every parser over every manifest document and score the results."""
    configs = adapter_configs or {}
    run_id = output_dir.name or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")

    metadata = RunMetadata(
        run_id=run_id,
        started_at=datetime.now(UTC).isoformat(),
        manifest=manifest_path,
        parsers=list(parsers),
        environment=_environment(),
        git_commit=_git_commit(root),
    )

    for parser_name in parsers:
        try:
            adapter = build_adapter(parser_name, configs.get(parser_name))
        except KeyError:
            metadata.adapters[parser_name] = {"error": "unknown adapter"}
            continue
        metadata.adapters[parser_name] = {
            "metadata": adapter.metadata.model_dump(mode="json"),
            "health": adapter.healthcheck().model_dump(mode="json"),
        }

    inspections: dict[str, InspectionReport] = {}
    for entry in entries:
        try:
            inspections[entry.document_id] = inspect_pdf(
                entry.resolve_path(root), entry.document_id
            )
        except ParserError as exc:
            inspections[entry.document_id] = InspectionReport(
                document_id=entry.document_id,
                route=Route.UNSUPPORTED,
                route_confidence=1.0,
                page_count=0,
                warnings=[exc.model.message],
            )
        _write_json(
            output_dir / "inspection" / f"{entry.document_id}.json",
            inspections[entry.document_id].model_dump(mode="json"),
        )

    runs: list[DocumentRun] = []
    for parser_name in parsers:
        for entry in entries:
            runs.append(
                run_document(
                    parser_name,
                    entry,
                    inspections[entry.document_id],
                    root,
                    output_dir,
                    configs.get(parser_name),
                )
            )

    scores = _score_runs(runs, parsers, entries, metadata)
    metadata.finished_at = datetime.now(UTC).isoformat()
    return metadata, runs, scores


def _score_runs(
    runs: list[DocumentRun],
    parsers: list[str],
    entries: list[ManifestEntry],
    metadata: RunMetadata,
) -> list[Any]:
    scan_routes = {"scanned", "mixed", "garbled_text_layer"}
    entry_by_id = {entry.document_id: entry for entry in entries}

    seconds_by_parser: dict[str, float | None] = {}
    for parser_name in parsers:
        values = [
            run.seconds_per_page
            for run in runs
            if run.parser == parser_name and run.seconds_per_page is not None
        ]
        seconds_by_parser[parser_name] = sum(values) / len(values) if values else None

    measured = [value for value in seconds_by_parser.values() if value is not None]
    best_seconds = min(measured) if measured else None

    scores = []
    for parser_name in parsers:
        parser_runs = [run for run in runs if run.parser == parser_name]
        metrics: dict[str, list[MetricResult]] = {}
        scan_metrics: dict[str, list[MetricResult]] = {}
        critical: list[MetricResult] = []
        severity_3: list[str] = []

        for run in parser_runs:
            is_scan = entry_by_id[run.document_id].route_label.value in scan_routes
            for name, result in run.metrics.items():
                metrics.setdefault(name, []).append(result)
                if is_scan:
                    scan_metrics.setdefault(name, []).append(result)
            if run.critical_field_metric is not None:
                critical.append(run.critical_field_metric)
            severity_3.extend(run.severity_3_fields)

        adapter_info = metadata.adapters.get(parser_name, {})
        capabilities = (
            adapter_info.get("metadata", {}).get("capabilities", {})
            if isinstance(adapter_info, dict)
            else {}
        )
        health = adapter_info.get("health", {}) if isinstance(adapter_info, dict) else {}

        scores.append(
            build_parser_score(
                parser=parser_name,
                metrics=metrics,
                scan_metrics=scan_metrics,
                critical_results=critical,
                documents_attempted=len(parser_runs),
                documents_parsed=sum(1 for run in parser_runs if run.status == "ok"),
                seconds_per_page=seconds_by_parser[parser_name],
                best_seconds_per_page=best_seconds,
                requires_gpu=bool(capabilities.get("requires_gpu")),
                benefits_from_gpu=bool(capabilities.get("benefits_from_gpu")),
                provider_installed=bool(health.get("available")),
                severity_3_failures=severity_3,
            )
        )
    return scores


CRITICAL_FIELD_EXTRACTOR = f"{EXTRACTOR_NAME}-{EXTRACTOR_VERSION}"


def route_confusion(runs: list[DocumentRun]) -> dict[str, dict[str, int]]:
    """Routing accuracy measured independently of parser quality."""
    matrix: dict[str, dict[str, int]] = {}
    seen: set[str] = set()
    for run in runs:
        if run.document_id in seen or run.route_actual is None:
            continue
        seen.add(run.document_id)
        matrix.setdefault(run.route_expected, {}).setdefault(run.route_actual, 0)
        matrix[run.route_expected][run.route_actual] += 1
    return matrix


def canonical_from_artifact(path: Path) -> CanonicalDocument:
    return CanonicalDocument.model_validate_json(path.read_text(encoding="utf-8"))
