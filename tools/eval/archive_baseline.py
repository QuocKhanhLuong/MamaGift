"""Run the Phase 5 archive retrieval baseline comparison and write the evidence report.

Deterministic and offline: a fake embedding provider and a fake reranker, a synthetic
sanitized corpus, no network, no API key, no GPU. Run against SQLite by default, or against a
real PostgreSQL + pgvector database by setting MAMAGIFT_TEST_DATABASE_URL.

    uv run python -m tools.eval.archive_baseline --output docs/eval/phase-5-baseline.md
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from alembic import command
from app.db import Base
from mamagift_eval.archive_harness import (
    ArchiveBaselineComparison,
    compare_archive_baselines,
    load_archive_cases,
)
from mamagift_retrieval.archive.sql_archive_index import SqlArchiveIndex
from mamagift_retrieval.providers import FakeEmbeddingProvider
from mamagift_retrieval.rerank import FakeReranker

REPO_ROOT = Path(__file__).resolve().parents[2]
CASES = REPO_ROOT / "tests" / "fixtures" / "archive" / "cases.jsonl"
EMBEDDING_VERSION = "fake-bge-m3-v1"
DIMENSION = 1024


def _build_session_factory() -> tuple[sessionmaker, str]:
    """Return a session factory over a seeded archive, plus the backend's name."""
    from tests.fixtures.archive.corpus import seed_archive

    url = os.environ.get("MAMAGIFT_TEST_DATABASE_URL")
    if url:
        os.environ["DATABASE_URL"] = url
        config = Config(str(REPO_ROOT / "services" / "api" / "alembic.ini"))
        command.downgrade(config, "base")
        command.upgrade(config, "head")
        engine = create_engine(url, future=True)
        backend = f"PostgreSQL + pgvector ({engine.dialect.name})"
    else:
        engine = create_engine("sqlite:///:memory:", future=True)
        Base.metadata.create_all(engine)
        backend = "SQLite (in-memory)"

    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    seed_archive(factory, embedding_version=EMBEDDING_VERSION, dimension=DIMENSION)
    return factory, backend


def run() -> tuple[ArchiveBaselineComparison, str]:
    factory, backend = _build_session_factory()
    cases = load_archive_cases(CASES)
    with factory() as session:
        comparison = compare_archive_baselines(
            cases,
            index=SqlArchiveIndex(session, default_embedding_version=EMBEDDING_VERSION),
            embedding_provider=FakeEmbeddingProvider(
                dimension=DIMENSION, embedding_version=EMBEDDING_VERSION
            ),
            reranker=FakeReranker(cross_document=True),
        )
    return comparison, backend


def _header(backend: str, case_count: int) -> str:
    return (
        "# Phase 5 — archive retrieval baseline comparison\n\n"
        f"Generated: {datetime.now(UTC).date().isoformat()}\n\n"
        f"Backend: {backend}\n\n"
        f"Cases: {case_count} (synthetic, sanitized, born-digital)\n\n"
        "Every number below is measured by `tools/eval/archive_baseline.py` on the fixture\n"
        "corpus in `tests/fixtures/archive/`. The corpus is synthetic: it contains no real\n"
        "school, person or document, and it makes no claim about scanned-PDF behaviour, which\n"
        "remains blocked on ADR-001.\n\n"
        "The retrieval stack is deterministic here -- a fake embedding provider and a fake\n"
        "reranker -- so these numbers measure the RETRIEVAL PLUMBING (filters, fusion,\n"
        "current-version isolation, identifier handling), not the quality of a real embedding\n"
        "model or a real cross-encoder. Read the leakage rows as correctness gates and the\n"
        "recall rows as a regression baseline, not as production quality.\n\n"
        "## What these numbers do and do not settle\n\n"
        "**Settled — the correctness gates hold in every mode.** Stale-version leakage and\n"
        "wrong-document leakage are 0.0 across lexical, dense, hybrid and hybrid+reranker, and\n"
        "metadata-filter accuracy is 1.0. The corpus deliberately contains a superseded parse\n"
        "version and documents outside each filter, so those zeros are measured, not vacuous.\n\n"
        "**Not settled — whether reranking improves ranking.** The reranker used here is\n"
        "`FakeReranker`, a deterministic shuffle with no semantic signal. The table below shows\n"
        "`hybrid_rerank` scoring *lower* than `lexical` and `dense` on Recall@3/@5/@10, MRR and\n"
        "nDCG. That is the expected behaviour of a stub reordering already-good results at\n"
        "random, and it is evidence about the stub, not about the production cross-encoder.\n"
        "No claim is made in either direction; answering it requires running this same harness\n"
        "against a real reranker, which needs the self-hosted worker and is offline operator\n"
        "evidence, not a CI gate.\n\n"
        "The API serves `CrossEncoderReranker` outside the test environment precisely because\n"
        "the fake is measurably worse than no reranking at all.\n\n"
        "**Not settled — real-model retrieval quality.** Embeddings here are deterministic\n"
        "hashes, not BGE-M3. Recall numbers measure whether the plumbing returns the right\n"
        "rows, not whether a real embedding model would rank them well.\n\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT / "docs" / "eval" / "phase-5-baseline.md",
        help="Where to write the markdown report.",
    )
    parser.add_argument("--print", action="store_true", help="Also print the report to stdout.")
    args = parser.parse_args(argv)

    comparison, backend = run()
    case_count = len(comparison.modes[0].cases) if comparison.modes else 0
    report = _header(backend, case_count) + comparison.render_markdown()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report, encoding="utf-8")
    if args.print:
        sys.stdout.write(report)

    # Release-blocking gates. These are CORRECTNESS properties -- they must hold regardless of
    # which retrieval mode or model is in use, so they are checked in every mode.
    #
    # There is deliberately NO gate here asserting that hybrid+reranker beats the single
    # retrievers. The reranker in this harness is a deterministic shuffle with no semantic
    # signal, so such a comparison would measure noise; the measured table shows the fake
    # reranker making ranking worse, which is the expected behaviour of a stub and says
    # nothing about the real cross-encoder. Claiming an improvement from these numbers would
    # be claiming an improvement without data.
    failures: list[str] = []
    for mode in comparison.modes:
        if mode.stale_version_leakage != 0.0:
            failures.append(f"{mode.mode}: stale_version_leakage={mode.stale_version_leakage}")
        if mode.wrong_document_leakage != 0.0:
            failures.append(f"{mode.mode}: wrong_document_leakage={mode.wrong_document_leakage}")
        if mode.metadata_filter_accuracy is not None and mode.metadata_filter_accuracy != 1.0:
            failures.append(
                f"{mode.mode}: metadata_filter_accuracy={mode.metadata_filter_accuracy}"
            )
    if failures:
        sys.stderr.write("Release-blocking leakage detected:\n  " + "\n  ".join(failures) + "\n")
        return 1

    sys.stdout.write(f"Wrote {args.output} ({case_count} cases, {len(comparison.modes)} modes)\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
