"""Unit tests for the sanitized multi-document archive evaluation harness and corpus."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from tests.fixtures.archive.corpus import (
    ARCHIVE_CORPUS,
    seed_archive,
)

from app.db import Base
from app.models import Document, DocumentChunk, ParseRun
from mamagift_eval.archive_harness import (
    ArchiveBaselineComparison,
    ArchiveModeReport,
    ArchiveRetrievalMode,
    compare_archive_baselines,
    evaluate_archive_retrieval,
    load_archive_cases,
)
from mamagift_retrieval.archive.sql_archive_index import SqlArchiveIndex
from mamagift_retrieval.providers import FakeEmbeddingProvider
from mamagift_retrieval.rerank import FakeReranker

pytestmark = pytest.mark.unit

CASES_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "archive" / "cases.jsonl"


@pytest.fixture
def seeded_db():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    seed_archive(factory, embedding_version="fake-bge-m3-v1", dimension=1024)
    return factory


@pytest.fixture
def eval_env(seeded_db):
    index = SqlArchiveIndex(seeded_db, embedding_version="fake-bge-m3-v1")
    provider = FakeEmbeddingProvider(dimension=1024, embedding_version="fake-bge-m3-v1")
    reranker = FakeReranker(cross_document=True)
    return index, provider, reranker


def test_seed_archive_produces_expected_documents_and_matching_current_parse_runs(
    seeded_db: sessionmaker[Session],
) -> None:
    """1. seed_archive produces expected doc count and current_parse_run_id matches."""
    with seeded_db() as session:
        docs = session.scalars(select(Document)).all()
        parse_runs = session.scalars(select(ParseRun)).all()
        chunks = session.scalars(select(DocumentChunk)).all()

    # 14 distinct documents (doc_sup_1 has 2 parse runs: v1 superseded, v2 current)
    assert len(docs) == 14
    assert len(parse_runs) == 15
    assert len(chunks) > 0

    current_runs_by_id = {pr.id: pr for pr in parse_runs if pr.is_current}

    for doc in docs:
        assert doc.current_parse_run_id is not None
        prun = current_runs_by_id.get(doc.current_parse_run_id)
        assert prun is not None, f"doc {doc.id} points to missing current parse run"
        assert prun.is_current is True
        assert prun.document_id == doc.id

    # Check superseded parse run explicitly
    superseded_run = next((pr for pr in parse_runs if not pr.is_current), None)
    assert superseded_run is not None
    assert superseded_run.document_id == "doc_sup_1"
    assert superseded_run.version == 1

    doc_sup = next(d for d in docs if d.id == "doc_sup_1")
    assert doc_sup.current_parse_run_id == "run_doc_sup_1_v2"


def test_load_retrieval_cases_parses_every_case() -> None:
    """2. load_retrieval_cases(cases.jsonl) parses every case."""
    cases = load_archive_cases(CASES_PATH)
    assert len(cases) >= 15
    for case in cases:
        assert len(case.case_id) > 0
        assert len(case.question) > 0
        assert len(case.expected_document_ids) > 0


def test_every_case_expected_document_ids_exist_in_corpus() -> None:
    """3. Every case's expected_document_ids reference documents that EXIST in the corpus."""
    corpus_doc_ids = {doc.document_id for doc in ARCHIVE_CORPUS}
    cases = load_archive_cases(CASES_PATH)

    for case in cases:
        for exp_id in case.expected_document_ids:
            assert exp_id in corpus_doc_ids, (
                f"Case {case.case_id} expected_document_id {exp_id!r} not in ARCHIVE_CORPUS"
            )
        for forb_id in case.forbidden_document_ids:
            assert forb_id in corpus_doc_ids, (
                f"Case {case.case_id} forbidden_document_id {forb_id!r} not in ARCHIVE_CORPUS"
            )


def test_all_four_modes_run_and_produce_populated_reports(eval_env) -> None:
    """4. All four modes run and produce a report with every field populated."""
    index, provider, reranker = eval_env
    cases = load_archive_cases(CASES_PATH)

    for mode in ArchiveRetrievalMode:
        report = evaluate_archive_retrieval(
            cases, index=index, embedding_provider=provider, reranker=reranker, mode=mode
        )
        assert isinstance(report, ArchiveModeReport)
        assert report.mode == mode.value
        assert len(report.cases) == len(cases)
        assert 0.0 <= report.recall_at_1 <= 1.0
        assert 0.0 <= report.recall_at_3 <= 1.0
        assert 0.0 <= report.recall_at_5 <= 1.0
        assert 0.0 <= report.recall_at_10 <= 1.0
        assert 0.0 <= report.mrr <= 1.0
        assert 0.0 <= report.ndcg_at_10 <= 1.0
        assert report.latency_p50_ms >= 0.0
        assert report.latency_p95_ms >= report.latency_p50_ms
        assert len(report.per_document_type) > 0
        for _dtype, metrics in report.per_document_type.items():
            assert "recall_at_1" in metrics
            assert "mrr" in metrics
            assert "ndcg_at_10" in metrics


def test_stale_version_leakage_is_zero_in_every_mode(eval_env) -> None:
    """5. stale_version_leakage is 0.0 in every mode."""
    index, provider, reranker = eval_env
    cases = load_archive_cases(CASES_PATH)

    for mode in ArchiveRetrievalMode:
        report = evaluate_archive_retrieval(
            cases, index=index, embedding_provider=provider, reranker=reranker, mode=mode
        )
        assert report.stale_version_leakage == 0.0, (
            f"Mode {mode} leaked stale version with rate {report.stale_version_leakage}"
        )
        for case_res in report.cases:
            assert case_res.stale_version_leaked is False, (
                f"Mode {mode} leaked stale version in case {case_res.case_id}"
            )

    # Also verify that searching for the distinctive phrase in doc_sup_1 returns NO stale chunk
    stale_case = next(c for c in cases if c.case_id == "case_stale_version_trap_doc_sup_1")
    rep = evaluate_archive_retrieval(
        [stale_case],
        index=index,
        embedding_provider=provider,
        reranker=reranker,
        mode=ArchiveRetrievalMode.HYBRID_RERANK,
    )
    assert rep.cases[0].stale_version_leaked is False


def test_wrong_document_leakage_is_zero_in_every_mode(eval_env) -> None:
    """6. wrong_document_leakage is 0.0 in every mode."""
    index, provider, reranker = eval_env
    cases = load_archive_cases(CASES_PATH)

    for mode in ArchiveRetrievalMode:
        report = evaluate_archive_retrieval(
            cases, index=index, embedding_provider=provider, reranker=reranker, mode=mode
        )
        assert report.wrong_document_leakage == 0.0, (
            f"Mode {mode} leaked wrong documents with rate {report.wrong_document_leakage}"
        )
        for case_res in report.cases:
            assert case_res.wrong_document_leaked is False, (
                f"Mode {mode} leaked forbidden doc in case {case_res.case_id}"
            )


def test_exact_identifier_query_ranks_thong_tu_first_in_hybrid_rerank(eval_env) -> None:
    """7. Exact-identifier query puts the right document first in HYBRID_RERANK."""
    index, provider, reranker = eval_env
    cases = load_archive_cases(CASES_PATH)
    case_19 = next(c for c in cases if c.case_id == "case_exact_doc_num_19")

    report = evaluate_archive_retrieval(
        [case_19],
        index=index,
        embedding_provider=provider,
        reranker=reranker,
        mode=ArchiveRetrievalMode.HYBRID_RERANK,
    )
    result = report.cases[0]
    assert result.recall_at_1 == 1.0
    assert result.exact_identifier_hit is True
    assert result.retrieved_document_ids[0] == "doc_tt_1"


def test_compare_archive_baselines_returns_all_modes_and_renders_markdown(eval_env) -> None:
    """8. Baseline comparison returns all 4 modes and renders markdown table."""
    index, provider, reranker = eval_env
    cases = load_archive_cases(CASES_PATH)

    comparison = compare_archive_baselines(
        cases, index=index, embedding_provider=provider, reranker=reranker
    )
    assert isinstance(comparison, ArchiveBaselineComparison)
    assert len(comparison.modes) == 4

    mode_names = [m.mode for m in comparison.modes]
    assert mode_names == ["lexical", "dense", "hybrid", "hybrid_rerank"]

    best = comparison.best_mode()
    assert best in mode_names

    md = comparison.render_markdown()
    for mode in mode_names:
        assert f"`{mode}`" in md

    for metric in [
        "Recall@1",
        "Recall@3",
        "Recall@5",
        "Recall@10",
        "MRR",
        "nDCG@10",
        "P50",
        "P95",
    ]:
        assert metric in md


def test_evaluation_determinism(eval_env) -> None:
    """9. Determinism: running the same mode twice gives identical recall/MRR/nDCG numbers."""
    index, provider, reranker = eval_env
    cases = load_archive_cases(CASES_PATH)

    report_1 = evaluate_archive_retrieval(
        cases,
        index=index,
        embedding_provider=provider,
        reranker=reranker,
        mode=ArchiveRetrievalMode.HYBRID_RERANK,
    )
    report_2 = evaluate_archive_retrieval(
        cases,
        index=index,
        embedding_provider=provider,
        reranker=reranker,
        mode=ArchiveRetrievalMode.HYBRID_RERANK,
    )

    assert report_1.recall_at_1 == report_2.recall_at_1
    assert report_1.recall_at_3 == report_2.recall_at_3
    assert report_1.recall_at_5 == report_2.recall_at_5
    assert report_1.recall_at_10 == report_2.recall_at_10
    assert report_1.mrr == report_2.mrr
    assert report_1.ndcg_at_10 == report_2.ndcg_at_10
    assert report_1.stale_version_leakage == report_2.stale_version_leakage
    assert report_1.wrong_document_leakage == report_2.wrong_document_leakage


def test_metrics_are_bounded_zero_to_one_and_latency_p95_ge_p50(eval_env) -> None:
    """10. Metrics are bounded 0..1 and P95 >= P50."""
    index, provider, reranker = eval_env
    cases = load_archive_cases(CASES_PATH)

    for mode in ArchiveRetrievalMode:
        report = evaluate_archive_retrieval(
            cases, index=index, embedding_provider=provider, reranker=reranker, mode=mode
        )
        assert 0.0 <= report.recall_at_1 <= 1.0
        assert 0.0 <= report.recall_at_3 <= 1.0
        assert 0.0 <= report.recall_at_5 <= 1.0
        assert 0.0 <= report.recall_at_10 <= 1.0
        assert 0.0 <= report.mrr <= 1.0
        assert 0.0 <= report.ndcg_at_10 <= 1.0
        assert 0.0 <= report.stale_version_leakage <= 1.0
        assert 0.0 <= report.wrong_document_leakage <= 1.0
        if report.exact_identifier_accuracy is not None:
            assert 0.0 <= report.exact_identifier_accuracy <= 1.0
        if report.metadata_filter_accuracy is not None:
            assert 0.0 <= report.metadata_filter_accuracy <= 1.0
        assert report.latency_p95_ms >= report.latency_p50_ms >= 0.0

        for case_res in report.cases:
            assert 0.0 <= case_res.recall_at_1 <= 1.0
            assert 0.0 <= case_res.recall_at_3 <= 1.0
            assert 0.0 <= case_res.recall_at_5 <= 1.0
            assert 0.0 <= case_res.recall_at_10 <= 1.0
            assert 0.0 <= case_res.reciprocal_rank <= 1.0
            assert 0.0 <= case_res.ndcg_at_10 <= 1.0
            assert case_res.latency_ms >= 0.0
