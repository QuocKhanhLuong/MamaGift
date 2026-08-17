"""Benchmark CLI.

    python -m tools.parser_bench run \
      --manifest benchmarks/parser/manifest.jsonl \
      --parsers pymupdf,mineru,marker,docling,ppstructure \
      --output artifacts/parser-bench/<run-id>

    python -m tools.parser_bench validate --manifest benchmarks/parser/manifest.jsonl
    python -m tools.parser_bench health --parsers pymupdf,mineru
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from mamagift_docpipe.adapters import available_adapter_names, build_adapter

from .manifest import ManifestError, check_manifest_files, load_manifest
from .report import write_reports
from .runner import run_benchmark

DEFAULT_MANIFEST = "benchmarks/parser/manifest.jsonl"
DEFAULT_PARSERS = "pymupdf"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _parse_parsers(raw: str) -> list[str]:
    return [name.strip() for name in raw.split(",") if name.strip()]


def _load_adapter_configs(path: str | None) -> dict[str, dict[str, object]]:
    if path is None:
        return {}
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit("adapter config file must contain a JSON object keyed by parser name")
    return payload


def command_validate(args: argparse.Namespace) -> int:
    root = _repo_root()
    try:
        entries = load_manifest(args.manifest)
    except ManifestError as exc:
        print(f"manifest invalid: {exc}")
        return 1

    problems = check_manifest_files(entries, root)
    if problems:
        print("Manifest references unusable files:")
        print("\n".join(f"- {problem}" for problem in problems))
        return 1

    routes: dict[str, int] = {}
    for entry in entries:
        routes[entry.route_label.value] = routes.get(entry.route_label.value, 0) + 1

    print(f"Manifest valid: {len(entries)} documents.")
    for route in sorted(routes):
        print(f"- {route}: {routes[route]}")
    return 0


def command_health(args: argparse.Namespace) -> int:
    for name in _parse_parsers(args.parsers):
        try:
            adapter = build_adapter(name)
        except KeyError as exc:
            print(f"{name}: {exc}")
            continue
        health = adapter.healthcheck()
        state = "available" if health.available else "unavailable"
        version = health.provider_version or "not installed"
        print(f"{name}: {state} (provider version: {version}) {health.detail}".rstrip())
    return 0


def command_run(args: argparse.Namespace) -> int:
    root = _repo_root()
    try:
        entries = load_manifest(args.manifest)
    except ManifestError as exc:
        print(f"manifest invalid: {exc}")
        return 1

    problems = check_manifest_files(entries, root)
    if problems:
        print("Manifest references unusable files:")
        print("\n".join(f"- {problem}" for problem in problems))
        return 1

    parsers = _parse_parsers(args.parsers)
    unknown = [name for name in parsers if name.split("+")[0] not in available_adapter_names()]
    if unknown:
        print(f"unknown parsers: {unknown}; available: {available_adapter_names()}")
        return 1

    run_id = args.run_id or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output_dir = Path(args.output) if args.output else root / "artifacts/parser-bench" / run_id

    metadata, runs, scores = run_benchmark(
        entries=entries,
        parsers=parsers,
        root=root,
        output_dir=output_dir,
        manifest_path=args.manifest,
        adapter_configs=_load_adapter_configs(args.adapter_config),
    )
    write_reports(output_dir, metadata, runs, scores)

    failures = [run for run in runs if run.status != "ok"]
    print(f"Benchmark complete: {len(runs)} runs, {len(failures)} failures.")
    print(f"Reports: {output_dir}")

    for score in scores:
        value = "n/a" if score.weighted_score is None else f"{score.weighted_score:.3f}"
        gates = ",".join(score.gate_failures) or "none"
        print(f"- {score.parser}: score={value} coverage={score.coverage:.2f} gates={gates}")

    if args.require_success and failures:
        print("Failing because --require-success was set and at least one run failed.")
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m tools.parser_bench")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="run the benchmark")
    run_parser.add_argument("--manifest", default=DEFAULT_MANIFEST)
    run_parser.add_argument("--parsers", default=DEFAULT_PARSERS)
    run_parser.add_argument("--output", default=None)
    run_parser.add_argument("--run-id", default=None)
    run_parser.add_argument("--adapter-config", default=None)
    run_parser.add_argument(
        "--require-success",
        action="store_true",
        help="exit non-zero if any parser run failed (used by the CI smoke job)",
    )
    run_parser.set_defaults(handler=command_run)

    validate_parser = subparsers.add_parser("validate", help="validate a manifest")
    validate_parser.add_argument("--manifest", default=DEFAULT_MANIFEST)
    validate_parser.set_defaults(handler=command_validate)

    health_parser = subparsers.add_parser("health", help="report adapter availability")
    health_parser.add_argument("--parsers", default=",".join(available_adapter_names()))
    health_parser.set_defaults(handler=command_health)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    handler = args.handler
    result: int = handler(args)
    return result


if __name__ == "__main__":
    sys.exit(main())
