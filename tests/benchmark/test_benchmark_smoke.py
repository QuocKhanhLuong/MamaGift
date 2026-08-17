"""End-to-end benchmark smoke test.

This is the `parser-benchmark-smoke` CI job: the whole harness — router, adapter,
normalizer, metrics, scoring, reports — over the committed synthetic fixtures using
only the lightweight parser. No GPU, no model weights, no private documents.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tools.parser_bench.__main__ import main
from tools.parser_bench.manifest import load_manifest
from tools.parser_bench.report import write_reports
from tools.parser_bench.runner import run_benchmark

from bench_support import MANIFEST, RECORDINGS, REPO_ROOT
from mamagift_docpipe import CanonicalDocument

pytestmark = pytest.mark.contract


def run_smoke(output_dir: Path, parsers: list[str]) -> tuple[object, list, list]:
    entries = load_manifest(MANIFEST)
    metadata, runs, scores = run_benchmark(
        entries=entries,
        parsers=parsers,
        root=REPO_ROOT,
        output_dir=output_dir,
        manifest_path=str(MANIFEST),
        adapter_configs={
            f"{name}+recorded": {"recordings_dir": str(RECORDINGS)}
            for name in ("mineru", "marker", "docling", "ppstructure")
        },
    )
    write_reports(output_dir, metadata, runs, scores)
    return metadata, runs, scores


def test_lightweight_parser_runs_the_whole_corpus_end_to_end(tmp_path: Path) -> None:
    metadata, runs, scores = run_smoke(tmp_path / "run", ["pymupdf"])

    assert len(runs) == len(load_manifest(MANIFEST))
    assert len(scores) == 1
    assert scores[0].parser == "pymupdf"
    assert scores[0].documents_parsed >= 6


def test_artifact_layout_matches_the_documented_contract(tmp_path: Path) -> None:
    output = tmp_path / "run"
    run_smoke(output, ["pymupdf"])

    for name in ("run.json", "summary.json", "summary.md", "per_document.csv"):
        assert (output / name).is_file(), name

    document_dir = output / "parsers/pymupdf/cong_van_born_digital"
    assert (document_dir / "canonical.json").is_file()
    assert (document_dir / "provider-output/result.json").is_file()
    assert (document_dir / "metrics.json").is_file()


def test_persisted_canonical_artifact_revalidates_against_the_schema(tmp_path: Path) -> None:
    output = tmp_path / "run"
    run_smoke(output, ["pymupdf"])

    path = output / "parsers/pymupdf/cong_van_born_digital/canonical.json"
    document = CanonicalDocument.model_validate_json(path.read_text(encoding="utf-8"))

    assert document.document_id == "cong_van_born_digital"
    assert len(document.pages) == 2
    assert all(block.provenance.page_number for block in document.iter_blocks())


def test_a_failing_parser_does_not_abort_the_other_candidates(tmp_path: Path) -> None:
    """`mineru+recorded` has no recording for these documents; pymupdf must still run."""
    _, runs, scores = run_smoke(tmp_path / "run", ["mineru+recorded", "pymupdf"])

    by_parser = {score.parser: score for score in scores}
    assert by_parser["mineru+recorded"].documents_parsed == 0
    assert by_parser["pymupdf"].documents_parsed >= 6

    codes = {run.error.code.value for run in runs if run.parser == "mineru+recorded" and run.error}
    assert codes == {"recording_missing"}


def test_encrypted_and_malformed_inputs_are_recorded_as_results_not_crashes(
    tmp_path: Path,
) -> None:
    _, runs, _ = run_smoke(tmp_path / "run", ["pymupdf"])
    by_document = {run.document_id: run for run in runs}

    assert by_document["tai_lieu_ma_hoa"].error is not None
    assert by_document["tai_lieu_ma_hoa"].error.code.value == "encrypted_pdf"
    assert by_document["tep_khong_hop_le"].error is not None
    assert by_document["tep_khong_hop_le"].error.code.value == "invalid_pdf"


def test_router_labels_every_fixture_correctly_in_a_full_run(tmp_path: Path) -> None:
    _, runs, _ = run_smoke(tmp_path / "run", ["pymupdf"])

    mismatches = [
        (run.document_id, run.route_expected, run.route_actual)
        for run in runs
        if run.route_actual != run.route_expected
    ]
    assert mismatches == []


def test_repeated_runs_capture_versions_and_configuration(tmp_path: Path) -> None:
    first_meta, _, _ = run_smoke(tmp_path / "one", ["pymupdf"])
    second_meta, _, _ = run_smoke(tmp_path / "two", ["pymupdf"])

    for metadata in (first_meta, second_meta):
        adapter = metadata.adapters["pymupdf"]
        assert adapter["metadata"]["provider_version"], "exact provider version must be recorded"
        assert adapter["metadata"]["configuration_hash"]
        assert metadata.environment["python"]
        assert metadata.runner_version and metadata.metrics_version

    assert first_meta.adapters["pymupdf"]["metadata"] == second_meta.adapters["pymupdf"]["metadata"]


def test_canonical_output_is_deterministic_across_two_identical_runs(tmp_path: Path) -> None:
    run_smoke(tmp_path / "one", ["pymupdf"])
    run_smoke(tmp_path / "two", ["pymupdf"])

    for document_id in ("cong_van_born_digital", "quyet_dinh_dieu_khoan", "trang_xoay"):
        first = json.loads(
            (tmp_path / f"one/parsers/pymupdf/{document_id}/canonical.json").read_text("utf-8")
        )
        second = json.loads(
            (tmp_path / f"two/parsers/pymupdf/{document_id}/canonical.json").read_text("utf-8")
        )

        # Timestamps and durations legitimately differ between runs; everything the
        # product depends on must not.
        for payload in (first, second):
            payload["parser_run"].pop("started_at")
            payload["parser_run"].pop("finished_at")
            payload["metadata"].pop("provider_duration_ms")

        assert first == second, document_id


def test_metrics_never_fabricate_scores_for_unlabelled_documents(tmp_path: Path) -> None:
    _, runs, _ = run_smoke(tmp_path / "run", ["pymupdf"])
    unlabelled = {run.document_id: run for run in runs}["scan_khong_co_text"]

    assert unlabelled.status == "ok"
    assert unlabelled.critical_field_metric is None
    assert set(unlabelled.metrics) == {"route_accuracy"}


def test_cli_validate_and_run_exit_zero(tmp_path: Path) -> None:
    assert main(["validate", "--manifest", str(MANIFEST)]) == 0
    assert main(["health", "--parsers", "pymupdf,mineru"]) == 0
    assert (
        main(
            [
                "run",
                "--manifest",
                str(MANIFEST),
                "--parsers",
                "pymupdf",
                "--output",
                str(tmp_path / "cli"),
            ]
        )
        == 0
    )
    assert (tmp_path / "cli/summary.md").is_file()


def test_cli_rejects_an_unknown_parser(tmp_path: Path) -> None:
    assert main(["run", "--manifest", str(MANIFEST), "--parsers", "khong-ton-tai"]) == 1
