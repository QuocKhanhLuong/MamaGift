"""Benchmark report generation.

Writes the artifact layout documented in `docs/03_DOCUMENT_PIPELINE.md` section 7.
The Markdown summary never prints a recommendation: it prints the numbers, the gate
failures and the coverage, and says explicitly when evidence is insufficient.
"""

from __future__ import annotations

import csv
import json
from io import StringIO
from pathlib import Path
from typing import Any

from .runner import DocumentRun, RunMetadata, route_confusion
from .scoring import ParserScore

REPORT_VERSION = "1.0"

PER_DOCUMENT_COLUMNS = [
    "parser",
    "document_id",
    "status",
    "route_expected",
    "route_actual",
    "page_count",
    "duration_ms",
    "seconds_per_page",
    "peak_rss_mb",
    "error_code",
    "critical_field_accuracy",
    "severity_3_fields",
    "character_accuracy",
    "word_accuracy",
    "diacritic_preservation",
    "reading_order_accuracy",
    "heading_hierarchy_f1",
    "list_preservation",
    "table_structure_score",
    "header_footer_leakage",
    "provenance_completeness",
    "page_attribution_accuracy",
]


def _metric_value(run: DocumentRun, name: str) -> str:
    result = run.metrics.get(name)
    if result is None or not result.available or result.value is None:
        return ""
    return f"{result.value:.4f}"


def per_document_csv(runs: list[DocumentRun]) -> str:
    buffer = StringIO()
    writer = csv.DictWriter(buffer, fieldnames=PER_DOCUMENT_COLUMNS, lineterminator="\n")
    writer.writeheader()

    for run in runs:
        critical = run.critical_field_metric
        row: dict[str, Any] = {
            "parser": run.parser,
            "document_id": run.document_id,
            "status": run.status,
            "route_expected": run.route_expected,
            "route_actual": run.route_actual or "",
            "page_count": run.page_count if run.page_count is not None else "",
            "duration_ms": "" if run.duration_ms is None else f"{run.duration_ms:.2f}",
            "seconds_per_page": (
                "" if run.seconds_per_page is None else f"{run.seconds_per_page:.4f}"
            ),
            "peak_rss_mb": "" if run.peak_rss_mb is None else f"{run.peak_rss_mb:.2f}",
            "error_code": "" if run.error is None else run.error.code.value,
            "critical_field_accuracy": (
                ""
                if critical is None or not critical.available or critical.value is None
                else f"{critical.value:.4f}"
            ),
            "severity_3_fields": ";".join(run.severity_3_fields),
        }
        for name in PER_DOCUMENT_COLUMNS[12:]:
            row[name] = _metric_value(run, name)
        writer.writerow(row)

    return buffer.getvalue()


def _format_score(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3f}"


def summary_markdown(
    metadata: RunMetadata,
    runs: list[DocumentRun],
    scores: list[ParserScore],
) -> str:
    lines: list[str] = []
    lines.append(f"# Parser benchmark run `{metadata.run_id}`")
    lines.append("")
    lines.append(f"- Manifest: `{metadata.manifest}`")
    lines.append(f"- Started: {metadata.started_at}")
    lines.append(f"- Finished: {metadata.finished_at or 'n/a'}")
    lines.append(f"- Commit: `{metadata.git_commit or 'unknown'}`")
    lines.append(f"- Python: {metadata.environment.get('python', 'unknown')}")
    lines.append(f"- Platform: {metadata.environment.get('platform', 'unknown')}")
    lines.append("")

    lines.append("## Adapter versions and configuration")
    lines.append("")
    lines.append("| Parser | Provider package | Provider version | Config hash | Available |")
    lines.append("|---|---|---|---|---|")
    for parser_name in metadata.parsers:
        info = metadata.adapters.get(parser_name, {})
        adapter_meta = info.get("metadata", {}) if isinstance(info, dict) else {}
        health = info.get("health", {}) if isinstance(info, dict) else {}
        lines.append(
            f"| `{parser_name}` "
            f"| `{adapter_meta.get('provider_package') or 'n/a'}` "
            f"| `{adapter_meta.get('provider_version') or 'not installed'}` "
            f"| `{adapter_meta.get('configuration_hash', 'n/a')}` "
            f"| {'yes' if health.get('available') else 'no'} |"
        )
    lines.append("")

    lines.append("## Weighted scores")
    lines.append("")
    lines.append("| Parser | Weighted score | Weight coverage | Parsed | Failure rate | Gates |")
    lines.append("|---|---|---|---|---|---|")
    for score in sorted(
        scores, key=lambda item: (item.weighted_score is None, -(item.weighted_score or 0.0))
    ):
        gates = ", ".join(score.gate_failures) if score.gate_failures else "—"
        lines.append(
            f"| `{score.parser}` "
            f"| {_format_score(score.weighted_score)} "
            f"| {score.coverage:.2f} "
            f"| {score.documents_parsed}/{score.documents_attempted} "
            f"| {score.failure_rate:.2f} "
            f"| {gates} |"
        )
    lines.append("")

    lines.append("## Dimensions")
    lines.append("")
    dimension_names = [dimension.name for dimension in scores[0].dimensions] if scores else []
    lines.append("| Parser | " + " | ".join(dimension_names) + " |")
    lines.append("|---" * (len(dimension_names) + 1) + "|")
    for score in scores:
        cells = [_format_score(dimension.value) for dimension in score.dimensions]
        lines.append(f"| `{score.parser}` | " + " | ".join(cells) + " |")
    lines.append("")

    lines.append("## Router accuracy (independent of parser quality)")
    lines.append("")
    matrix = route_confusion(runs)
    if matrix:
        lines.append("| Expected route | Produced route | Documents |")
        lines.append("|---|---|---|")
        for expected in sorted(matrix):
            for actual in sorted(matrix[expected]):
                lines.append(f"| `{expected}` | `{actual}` | {matrix[expected][actual]} |")
    else:
        lines.append("No routed documents in this run.")
    lines.append("")

    lines.append("## Failures")
    lines.append("")
    failures = [run for run in runs if run.status != "ok"]
    if failures:
        lines.append("| Parser | Document | Error code | Message |")
        lines.append("|---|---|---|---|")
        for run in failures:
            code = run.error.code.value if run.error else "unknown"
            message = (run.error.message if run.error else "").replace("|", "\\|")
            lines.append(f"| `{run.parser}` | `{run.document_id}` | `{code}` | {message} |")
    else:
        lines.append("No parser failures in this run.")
    lines.append("")

    lines.append("## Evidence sufficiency")
    lines.append("")
    lines.extend(_evidence_notes(runs, scores))
    lines.append("")
    return "\n".join(lines)


def _evidence_notes(runs: list[DocumentRun], scores: list[ParserScore]) -> list[str]:
    """State plainly whether this run can support a parser decision."""
    notes: list[str] = []
    documents = {run.document_id for run in runs}
    labelled = {run.document_id for run in runs if run.critical_field_metric is not None}

    notes.append(f"- Documents in run: {len(documents)}")
    notes.append(f"- Documents with critical-field ground truth: {len(labelled)}")

    if len(documents) < 30:
        notes.append(
            f"- **Insufficient for a production decision.** `docs/04_PHASE_PLAN.md` requires at "
            f"least 30 representative real documents; this run has {len(documents)}."
        )
    for score in scores:
        if score.coverage < 1.0:
            notes.append(
                f"- `{score.parser}`: scored over {score.coverage:.2f} of 1.00 weight; "
                "missing dimensions were excluded rather than defaulted to zero."
            )
    return notes


def write_reports(
    output_dir: Path,
    metadata: RunMetadata,
    runs: list[DocumentRun],
    scores: list[ParserScore],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    (output_dir / "run.json").write_text(
        json.dumps(metadata.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )

    summary = {
        "report_version": REPORT_VERSION,
        "run_id": metadata.run_id,
        "scores": [score.model_dump(mode="json") for score in scores],
        "route_confusion": route_confusion(runs),
        "documents": len({run.document_id for run in runs}),
        "runs": [run.model_dump(mode="json") for run in runs],
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    (output_dir / "summary.md").write_text(
        summary_markdown(metadata, runs, scores), encoding="utf-8"
    )
    (output_dir / "per_document.csv").write_text(per_document_csv(runs), encoding="utf-8")
