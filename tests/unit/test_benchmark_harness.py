"""Benchmark harness tests: manifest validation, scoring gates and report generation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tools.parser_bench.manifest import (
    ManifestError,
    check_manifest_files,
    load_ground_truth,
    load_manifest,
)
from tools.parser_bench.metrics import MetricResult
from tools.parser_bench.report import per_document_csv, summary_markdown, write_reports
from tools.parser_bench.runner import DocumentRun, RunMetadata, route_confusion
from tools.parser_bench.scoring import (
    MIN_READING_ORDER,
    WEIGHTS,
    build_parser_score,
    integration_simplicity,
    runtime_score,
)

from bench_support import MANIFEST, REPO_ROOT

pytestmark = pytest.mark.unit


def write_manifest(tmp_path: Path, lines: list[str]) -> Path:
    path = tmp_path / "manifest.jsonl"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


VALID_LINE = json.dumps(
    {
        "document_id": "doc_a",
        "path": "benchmarks/parser/fixtures/cong_van_born_digital.pdf",
        "route_label": "born_digital",
        "difficulty": "easy",
        "provenance": "synthetic",
        "ground_truth": None,
        "notes": "",
    }
)


# ---------------------------------------------------------------------- manifest


def test_committed_manifest_is_valid_and_covers_every_route() -> None:
    entries = load_manifest(MANIFEST)

    assert check_manifest_files(entries, REPO_ROOT) == []
    routes = {entry.route_label.value for entry in entries}
    assert routes == {
        "born_digital",
        "scanned",
        "mixed",
        "garbled_text_layer",
        "encrypted",
        "unsupported",
    }
    assert all(entry.provenance.value == "synthetic" for entry in entries)


def test_committed_ground_truth_files_load() -> None:
    for entry in load_manifest(MANIFEST):
        path = entry.resolve_ground_truth(REPO_ROOT)
        if path is None:
            continue
        truth = load_ground_truth(path)
        assert truth.document_id == entry.document_id
        assert truth.page_count and truth.page_count >= 1


def test_blank_lines_and_comments_are_ignored(tmp_path: Path) -> None:
    path = write_manifest(tmp_path, ["# a comment", "", VALID_LINE])
    assert len(load_manifest(path)) == 1


def test_invalid_json_reports_the_line_number(tmp_path: Path) -> None:
    path = write_manifest(tmp_path, [VALID_LINE, "{not json"])
    with pytest.raises(ManifestError, match=r"manifest.jsonl:2: invalid JSON"):
        load_manifest(path)


def test_unknown_route_label_is_rejected(tmp_path: Path) -> None:
    bad = json.loads(VALID_LINE)
    bad["route_label"] = "handwritten"
    path = write_manifest(tmp_path, [json.dumps(bad)])
    with pytest.raises(ManifestError, match="route_label"):
        load_manifest(path)


def test_unknown_manifest_keys_are_rejected(tmp_path: Path) -> None:
    bad = json.loads(VALID_LINE)
    bad["secret_field"] = "x"
    path = write_manifest(tmp_path, [json.dumps(bad)])
    with pytest.raises(ManifestError):
        load_manifest(path)


def test_duplicate_document_ids_are_rejected(tmp_path: Path) -> None:
    path = write_manifest(tmp_path, [VALID_LINE, VALID_LINE])
    with pytest.raises(ManifestError, match="duplicate document_id"):
        load_manifest(path)


def test_empty_manifest_is_rejected(tmp_path: Path) -> None:
    path = write_manifest(tmp_path, ["# nothing here"])
    with pytest.raises(ManifestError, match="no entries"):
        load_manifest(path)


def test_missing_files_are_reported_not_raised(tmp_path: Path) -> None:
    bad = json.loads(VALID_LINE)
    bad["path"] = "benchmarks/parser/fixtures/khong-ton-tai.pdf"
    entries = load_manifest(write_manifest(tmp_path, [json.dumps(bad)]))

    problems = check_manifest_files(entries, REPO_ROOT)
    assert len(problems) == 1
    assert "missing PDF" in problems[0]


def test_private_documents_must_live_outside_the_repository(tmp_path: Path) -> None:
    bad = json.loads(VALID_LINE)
    bad["provenance"] = "private"
    entries = load_manifest(write_manifest(tmp_path, [json.dumps(bad)]))

    problems = check_manifest_files(entries, REPO_ROOT)
    assert any("absolute path" in problem for problem in problems)


# ----------------------------------------------------------------------- scoring


def make_run(parser: str, document_id: str, **overrides: object) -> DocumentRun:
    payload: dict[str, object] = {
        "parser": parser,
        "document_id": document_id,
        "status": "ok",
        "route_expected": "born_digital",
        "route_actual": "born_digital",
        "page_count": 1,
        "duration_ms": 100.0,
        "seconds_per_page": 0.1,
    }
    payload.update(overrides)
    return DocumentRun(**payload)  # type: ignore[arg-type]


def metric(name: str, value: float | None, available: bool = True) -> MetricResult:
    return MetricResult(name=name, value=value, available=available)


def test_weights_sum_to_one() -> None:
    assert sum(WEIGHTS.values()) == pytest.approx(1.0)


def test_unavailable_dimensions_are_excluded_rather_than_scored_zero() -> None:
    score = build_parser_score(
        parser="p",
        metrics={"reading_order_accuracy": [metric("reading_order_accuracy", 1.0)]},
        scan_metrics={},
        critical_results=[],
        documents_attempted=1,
        documents_parsed=1,
        seconds_per_page=None,
        best_seconds_per_page=None,
        requires_gpu=False,
        benefits_from_gpu=False,
        provider_installed=True,
        severity_3_failures=[],
    )

    assert score.coverage < 1.0
    assert score.weighted_score == pytest.approx(1.0)
    assert any("missing" in note for note in score.notes)


def test_reading_order_corruption_disqualifies_regardless_of_average() -> None:
    score = build_parser_score(
        parser="p",
        metrics={
            "reading_order_accuracy": [metric("reading_order_accuracy", MIN_READING_ORDER - 0.01)],
            "provenance_completeness": [metric("provenance_completeness", 1.0)],
        },
        scan_metrics={},
        critical_results=[metric("critical_field_accuracy", 1.0)],
        documents_attempted=1,
        documents_parsed=1,
        seconds_per_page=0.1,
        best_seconds_per_page=0.1,
        requires_gpu=False,
        benefits_from_gpu=False,
        provider_installed=True,
        severity_3_failures=[],
    )

    assert score.disqualified is True
    assert "reading_order_corruption" in score.gate_failures


def test_lost_page_provenance_disqualifies() -> None:
    score = build_parser_score(
        parser="p",
        metrics={"provenance_completeness": [metric("provenance_completeness", 0.99)]},
        scan_metrics={},
        critical_results=[],
        documents_attempted=1,
        documents_parsed=1,
        seconds_per_page=0.1,
        best_seconds_per_page=0.1,
        requires_gpu=False,
        benefits_from_gpu=False,
        provider_installed=True,
        severity_3_failures=[],
    )

    assert "provenance_loss" in score.gate_failures


def test_a_wrong_date_disqualifies_even_with_a_high_score() -> None:
    score = build_parser_score(
        parser="p",
        metrics={
            "reading_order_accuracy": [metric("reading_order_accuracy", 1.0)],
            "provenance_completeness": [metric("provenance_completeness", 1.0)],
        },
        scan_metrics={},
        critical_results=[metric("critical_field_accuracy", 0.95)],
        documents_attempted=1,
        documents_parsed=1,
        seconds_per_page=0.1,
        best_seconds_per_page=0.1,
        requires_gpu=False,
        benefits_from_gpu=False,
        provider_installed=True,
        severity_3_failures=["issue_date"],
    )

    assert score.disqualified is True
    assert "critical_fact_error" in score.gate_failures
    assert any("severity-3" in note for note in score.notes)


def test_total_parse_failure_is_gated() -> None:
    score = build_parser_score(
        parser="p",
        metrics={},
        scan_metrics={},
        critical_results=[],
        documents_attempted=3,
        documents_parsed=0,
        seconds_per_page=None,
        best_seconds_per_page=None,
        requires_gpu=False,
        benefits_from_gpu=False,
        provider_installed=False,
        severity_3_failures=[],
    )

    assert score.failure_rate == pytest.approx(1.0)
    assert "parse_failure" in score.gate_failures


def test_runtime_score_is_relative_to_the_fastest_candidate() -> None:
    assert runtime_score(0.1, 0.1) == pytest.approx(1.0)
    assert runtime_score(0.4, 0.1) == pytest.approx(0.25)
    assert runtime_score(None, 0.1) is None


def test_integration_simplicity_penalizes_gpu_requirements() -> None:
    assert integration_simplicity(False, False, True) == pytest.approx(1.0)
    assert integration_simplicity(False, True, True) == pytest.approx(0.8)
    assert integration_simplicity(True, False, True) == pytest.approx(0.5)
    assert integration_simplicity(True, False, False) == pytest.approx(0.3)


# ------------------------------------------------------------------------ report


def make_metadata(**overrides: object) -> RunMetadata:
    payload: dict[str, object] = {
        "run_id": "test-run",
        "started_at": "2026-01-01T00:00:00+00:00",
        "finished_at": "2026-01-01T00:00:05+00:00",
        "manifest": "benchmarks/parser/manifest.jsonl",
        "parsers": ["pymupdf"],
        "adapters": {
            "pymupdf": {
                "metadata": {
                    "provider_package": "pymupdf",
                    "provider_version": "1.28.2",
                    "configuration_hash": "abc",
                },
                "health": {"available": True},
            }
        },
        "environment": {"python": "3.12.10", "platform": "linux"},
        "git_commit": "deadbeef",
    }
    payload.update(overrides)
    return RunMetadata(**payload)  # type: ignore[arg-type]


def test_per_document_csv_has_a_stable_header_and_one_row_per_run() -> None:
    runs = [
        make_run("pymupdf", "doc_a", metrics={"character_accuracy": metric("ca", 0.5)}),
        make_run("pymupdf", "doc_b", status="failed", seconds_per_page=None),
    ]
    lines = per_document_csv(runs).strip().split("\n")

    assert lines[0].startswith("parser,document_id,status,route_expected")
    assert len(lines) == 3
    assert ",0.5000," in lines[1]


def test_report_files_are_written(tmp_path: Path) -> None:
    runs = [make_run("pymupdf", "doc_a")]
    scores = [
        build_parser_score(
            parser="pymupdf",
            metrics={"reading_order_accuracy": [metric("reading_order_accuracy", 1.0)]},
            scan_metrics={},
            critical_results=[],
            documents_attempted=1,
            documents_parsed=1,
            seconds_per_page=0.1,
            best_seconds_per_page=0.1,
            requires_gpu=False,
            benefits_from_gpu=False,
            provider_installed=True,
            severity_3_failures=[],
        )
    ]

    write_reports(tmp_path, make_metadata(), runs, scores)

    for name in ("run.json", "summary.json", "summary.md", "per_document.csv"):
        assert (tmp_path / name).is_file(), name

    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert summary["documents"] == 1
    assert summary["scores"][0]["parser"] == "pymupdf"


def test_summary_records_exact_versions_and_configuration() -> None:
    markdown = summary_markdown(make_metadata(), [make_run("pymupdf", "doc_a")], [])

    assert "1.28.2" in markdown
    assert "`abc`" in markdown
    assert "deadbeef" in markdown
    assert "3.12.10" in markdown


def test_summary_states_when_evidence_is_insufficient_for_a_decision() -> None:
    markdown = summary_markdown(make_metadata(), [make_run("pymupdf", "doc_a")], [])
    assert "Insufficient for a production decision" in markdown
    assert "at least 30" in markdown


def test_summary_lists_failures_with_their_error_codes() -> None:
    from mamagift_docpipe.errors import ParserErrorCode, ParserErrorModel

    failed = make_run(
        "pymupdf",
        "tai_lieu_ma_hoa",
        status="failed",
        error=ParserErrorModel(
            code=ParserErrorCode.ENCRYPTED_PDF,
            message="document is password protected",
            retryable=False,
            parser_name="pymupdf",
        ),
    )
    markdown = summary_markdown(make_metadata(), [failed], [])

    assert "encrypted_pdf" in markdown
    assert "document is password protected" in markdown


def test_route_confusion_counts_each_document_once() -> None:
    runs = [
        make_run("pymupdf", "doc_a"),
        make_run("mineru", "doc_a"),
        make_run("pymupdf", "doc_b", route_expected="scanned", route_actual="born_digital"),
    ]
    matrix = route_confusion(runs)

    assert matrix == {
        "born_digital": {"born_digital": 1},
        "scanned": {"born_digital": 1},
    }
