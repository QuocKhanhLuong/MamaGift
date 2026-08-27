"""Sanitized multi-document archive evaluation harness and baseline comparison (Phase 5).

This module evaluates cross-document retrieval across current archive documents. It provides
metrics for lexical, dense, hybrid (RRF + identifier boost), and hybrid+rerank retrieval
modes, measuring recall, MRR, nDCG, exact identifier hit rate, metadata filter accuracy,
version isolation, and latency percentiles.
"""

from __future__ import annotations

import asyncio
import json
import math
import time
from collections.abc import Mapping, Sequence
from datetime import date
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from mamagift_retrieval.archive.filters import ArchiveFilter, normalize_identifier
from mamagift_retrieval.archive.identifiers import (
    extract_query_identifiers,
    identifier_match_score,
)
from mamagift_retrieval.archive.protocol import (
    AUTHORITATIVE_FAMILY_ID,
    ArchiveDocumentRef,
    ArchiveIndex,
)
from mamagift_retrieval.archive.retriever import ArchiveRetriever
from mamagift_retrieval.providers.embedding import EmbeddingProvider
from mamagift_retrieval.rerank.protocol import Reranker
from mamagift_retrieval.scope import EvidenceScope
from mamagift_retrieval.search.fusion import archive_reciprocal_rank_fusion
from mamagift_retrieval.search.types import ScoredChunk

from .schemas import RetrievalQACase


class ArchiveRetrievalMode(StrEnum):
    LEXICAL = "lexical"
    DENSE = "dense"
    HYBRID = "hybrid"
    HYBRID_RERANK = "hybrid_rerank"


class ArchiveCaseResult(BaseModel):
    """Evaluation result for one retrieval case in a specific retrieval mode."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    mode: str
    recall_at_1: float = Field(ge=0.0, le=1.0)
    recall_at_3: float = Field(ge=0.0, le=1.0)
    recall_at_5: float = Field(ge=0.0, le=1.0)
    recall_at_10: float = Field(ge=0.0, le=1.0)
    reciprocal_rank: float = Field(ge=0.0, le=1.0)
    ndcg_at_10: float = Field(ge=0.0, le=1.0)
    exact_identifier_hit: bool | None = None
    metadata_filter_respected: bool | None = None
    stale_version_leaked: bool
    wrong_document_leaked: bool
    latency_ms: float = Field(ge=0.0)
    retrieved_document_ids: list[str] = Field(default_factory=list)


class ArchiveModeReport(BaseModel):
    """Aggregate evaluation report across cases for one retrieval mode."""

    model_config = ConfigDict(extra="forbid")

    mode: str
    cases: list[ArchiveCaseResult]
    recall_at_1: float = Field(ge=0.0, le=1.0)
    recall_at_3: float = Field(ge=0.0, le=1.0)
    recall_at_5: float = Field(ge=0.0, le=1.0)
    recall_at_10: float = Field(ge=0.0, le=1.0)
    mrr: float = Field(ge=0.0, le=1.0)
    ndcg_at_10: float = Field(ge=0.0, le=1.0)
    exact_identifier_accuracy: float | None = None
    metadata_filter_accuracy: float | None = None
    stale_version_leakage: float = Field(ge=0.0, le=1.0)
    wrong_document_leakage: float = Field(ge=0.0, le=1.0)
    latency_p50_ms: float = Field(ge=0.0)
    latency_p95_ms: float = Field(ge=0.0)
    per_document_type: dict[str, dict[str, float]] = Field(default_factory=dict)


class ArchiveBaselineComparison(BaseModel):
    """Comparison table across all evaluated archive retrieval baselines."""

    model_config = ConfigDict(extra="forbid")

    modes: list[ArchiveModeReport]

    def best_mode(self) -> str:
        """Select the best performing mode based on MRR and nDCG@10."""
        if not self.modes:
            return ""
        # Sort by mrr desc, ndcg_at_10 desc, recall_at_5 desc, latency_p50_ms asc
        best = max(
            self.modes,
            key=lambda m: (m.mrr, m.ndcg_at_10, m.recall_at_5, -m.latency_p50_ms),
        )
        return best.mode

    def render_markdown(self) -> str:
        """Render measured metrics as a markdown table per mode and per document type."""
        header = (
            "| Mode | Recall@1 | Recall@3 | Recall@5 | Recall@10 | MRR | nDCG@10 | "
            "Ident. Acc | Filter Acc | Stale Leak | Wrong Leak | P50 (ms) | P95 (ms) |"
        )
        separator = (
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | "
            "---: | ---: | ---: | ---: |"
        )
        lines: list[str] = [
            "# Archive Retrieval Baseline Comparison",
            "",
            "## Overall Mode Metrics",
            "",
            header,
            separator,
        ]

        for m in self.modes:
            ident_str = (
                f"{m.exact_identifier_accuracy:.4f}"
                if m.exact_identifier_accuracy is not None
                else "n/a"
            )
            filter_str = (
                f"{m.metadata_filter_accuracy:.4f}"
                if m.metadata_filter_accuracy is not None
                else "n/a"
            )
            row = (
                f"| `{m.mode}` | {m.recall_at_1:.4f} | {m.recall_at_3:.4f} | "
                f"{m.recall_at_5:.4f} | {m.recall_at_10:.4f} | {m.mrr:.4f} | "
                f"{m.ndcg_at_10:.4f} | {ident_str} | {filter_str} | "
                f"{m.stale_version_leakage:.4f} | {m.wrong_document_leakage:.4f} | "
                f"{m.latency_p50_ms:.2f} | {m.latency_p95_ms:.2f} |"
            )
            lines.append(row)

        lines.extend(
            [
                "",
                "## Per Document Type Slices",
                "",
            ]
        )

        # Gather all doc types
        doc_types = sorted({dtype for m in self.modes for dtype in m.per_document_type})
        if doc_types:
            for dtype in doc_types:
                lines.extend(
                    [
                        f"### Document Type: `{dtype}`",
                        "",
                        "| Mode | Recall@1 | Recall@5 | Recall@10 | MRR | nDCG@10 | Case Count |",
                        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
                    ]
                )
                for m in self.modes:
                    stats = m.per_document_type.get(dtype)
                    if stats:
                        r1 = stats.get("recall_at_1", 0.0)
                        r5 = stats.get("recall_at_5", 0.0)
                        r10 = stats.get("recall_at_10", 0.0)
                        mrr_val = stats.get("mrr", 0.0)
                        ndcg_val = stats.get("ndcg_at_10", 0.0)
                        cnt = int(stats.get("case_count", 0))
                        row = (
                            f"| `{m.mode}` | {r1:.4f} | {r5:.4f} | {r10:.4f} | "
                            f"{mrr_val:.4f} | {ndcg_val:.4f} | {cnt} |"
                        )
                        lines.append(row)
                lines.append("")
        else:
            lines.append("No per-document-type slices recorded.\n")

        return "\n".join(lines).strip() + "\n"


def load_archive_cases(path: str | Path) -> list[RetrievalQACase]:
    """Load archive eval cases from JSONL (one object per line) or a JSON array.

    Deliberately NOT named `load_retrieval_cases`: `mamagift_eval.retrieval_harness`
    already exports that name for JSON arrays only, and two same-named loaders with
    different accepted formats is a trap for the caller.
    """
    case_path = Path(path)
    text = case_path.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError(f"{case_path}: empty file")

    cases: list[RetrievalQACase] = []
    # Try parsing as JSON array first if it starts with '['
    if text.startswith("[") or text.startswith("{"):
        try:
            payload = json.loads(text)
            if isinstance(payload, Mapping):
                payload = payload.get("cases", [])
            if isinstance(payload, list):
                cases = [RetrievalQACase.model_validate(item) for item in payload]
        except json.JSONDecodeError:
            cases = []

    # If not loaded as JSON, parse line by line (JSONL format)
    if not cases:
        for line_num, line in enumerate(text.splitlines(), start=1):
            line_str = line.strip()
            if not line_str or line_str.startswith("#"):
                continue
            try:
                data = json.loads(line_str)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{case_path}:{line_num}: invalid JSON: {exc.msg}") from exc
            cases.append(RetrievalQACase.model_validate(data))

    if not cases:
        raise ValueError(f"{case_path}: expected at least one test case")

    # Validate unique case_id
    case_ids = [c.case_id for c in cases]
    if len(set(case_ids)) != len(case_ids):
        raise ValueError(f"{case_path}: duplicate case_id found in test cases")

    return cases


def _percentile(values: Sequence[float], p: float) -> float:
    """Calculate percentile p (0..100) using the nearest-rank method."""
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    rank = math.ceil((p / 100.0) * len(sorted_vals))
    idx = max(0, min(rank - 1, len(sorted_vals) - 1))
    return sorted_vals[idx]


def _filter_from_case(case: RetrievalQACase) -> ArchiveFilter | None:
    """Extract relational ArchiveFilter from a case required_metadata_scope."""
    meta = case.required_metadata_scope
    if not meta:
        return None

    doc_ids = [meta["document_id"]] if "document_id" in meta else None
    if "document_ids" in meta:
        doc_ids = [s.strip() for s in meta["document_ids"].split(",") if s.strip()]

    doc_types = [meta["document_type"]] if "document_type" in meta else None
    if "document_types" in meta:
        doc_types = [s.strip() for s in meta["document_types"].split(",") if s.strip()]

    doc_numbers = [meta["document_number"]] if "document_number" in meta else None
    if "document_numbers" in meta:
        doc_numbers = [s.strip() for s in meta["document_numbers"].split(",") if s.strip()]

    issuers = [meta["issuer"]] if "issuer" in meta else None
    if "issuers" in meta:
        issuers = [s.strip() for s in meta["issuers"].split(",") if s.strip()]

    issued_date_from: date | None = None
    if "issued_date_from" in meta:
        issued_date_from = date.fromisoformat(meta["issued_date_from"])

    issued_date_to: date | None = None
    if "issued_date_to" in meta:
        issued_date_to = date.fromisoformat(meta["issued_date_to"])

    if (
        doc_ids is None
        and doc_types is None
        and doc_numbers is None
        and issuers is None
        and issued_date_from is None
        and issued_date_to is None
    ):
        return None

    return ArchiveFilter(
        document_ids=doc_ids,
        document_types=doc_types,
        document_numbers=doc_numbers,
        issuers=issuers,
        issued_date_from=issued_date_from,
        issued_date_to=issued_date_to,
    )


def _recall_at_k(expected_ids: set[str], matches: Mapping[int, set[str]], k: int) -> float:
    """Standard Recall@k formula from retrieval_harness."""
    if not expected_ids:
        return 0.0
    found = {identifier for rank, ids in matches.items() if rank <= k for identifier in ids}
    return len(found) / len(expected_ids)


def _ndcg(matches: Mapping[int, set[str]], expected_count: int, top_k: int) -> float:
    """Standard nDCG formula from retrieval_harness."""
    if not matches:
        return 0.0
    dcg = sum(1.0 / math.log2(rank + 1) for rank, ids in matches.items() if rank <= top_k and ids)
    ideal_relevant = min(expected_count, top_k)
    ideal_dcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_relevant + 1))
    return dcg / ideal_dcg if ideal_dcg else 0.0


def _score_archive_case(
    case: RetrievalQACase,
    mode: str,
    candidates: Sequence[ScoredChunk],
    latency_ms: float,
    current_docs_by_id: Mapping[str, ArchiveDocumentRef],
    filters: ArchiveFilter | None,
) -> ArchiveCaseResult:
    """Compute case-level metrics for one case result."""
    # Deduplicate retrieved candidates by chunk_id preserving rank order
    unique_candidates: list[tuple[int, ScoredChunk]] = []
    seen_chunk_ids: set[str] = set()
    for rank, c in enumerate(candidates, start=1):
        if c.chunk.chunk_id in seen_chunk_ids:
            continue
        seen_chunk_ids.add(c.chunk.chunk_id)
        unique_candidates.append((rank, c))

    retrieved_doc_ids: list[str] = []
    seen_doc_ids: set[str] = set()
    for _, c in unique_candidates:
        if c.chunk.document_id not in seen_doc_ids:
            seen_doc_ids.add(c.chunk.document_id)
            retrieved_doc_ids.append(c.chunk.document_id)

    # Determine expected relevance targets
    if case.expected_chunk_ids:
        expected_ids = set(case.expected_chunk_ids)
    elif case.expected_block_ids:
        expected_ids = set(case.expected_block_ids)
    else:
        expected_ids = set(case.expected_document_ids)

    matches_by_position: dict[int, set[str]] = {}
    already_credited: set[str] = set()
    for rank, c in unique_candidates:
        matched: set[str] = set()
        if case.expected_chunk_ids:
            if c.chunk.chunk_id in expected_ids:
                matched.add(c.chunk.chunk_id)
        elif case.expected_block_ids:
            matched = set(c.chunk.source_block_ids).intersection(expected_ids)
        else:
            if c.chunk.document_id in expected_ids:
                matched.add(c.chunk.document_id)
        new_matched = matched - already_credited
        if new_matched:
            matches_by_position[rank] = new_matched
            already_credited.update(new_matched)

    recall_1 = _recall_at_k(expected_ids, matches_by_position, 1)
    recall_3 = _recall_at_k(expected_ids, matches_by_position, 3)
    recall_5 = _recall_at_k(expected_ids, matches_by_position, 5)
    recall_10 = _recall_at_k(expected_ids, matches_by_position, 10)
    first_rel = min(matches_by_position, default=None)
    reciprocal_rank = 1.0 / first_rel if first_rel is not None else 0.0
    ndcg_10 = _ndcg(matches_by_position, len(expected_ids), 10)

    # Exact identifier check
    query_ident = extract_query_identifiers(case.question)
    expected_doc_num = case.required_metadata_scope.get("document_number")
    target_ident: str | None = None
    if expected_doc_num is not None:
        target_ident = normalize_identifier(expected_doc_num)
    elif query_ident.document_numbers:
        target_ident = normalize_identifier(query_ident.document_numbers[0])

    exact_ident_hit: bool | None = None
    if target_ident is not None:
        # Check if the top retrieved result matches the target identifier
        if unique_candidates:
            top_chunk = unique_candidates[0][1].chunk
            exact_ident_hit = (
                top_chunk.document_number is not None
                and normalize_identifier(top_chunk.document_number) == target_ident
            )
        else:
            exact_ident_hit = False

    # Metadata filter check
    metadata_filter_respected: bool | None = None
    if filters is not None:
        respected = True
        for _, c in unique_candidates:
            ch = c.chunk
            if filters.document_ids is not None and ch.document_id not in filters.document_ids:
                respected = False
                break
            if filters.document_types is not None and (
                ch.document_type not in filters.document_types
            ):
                respected = False
                break
            if filters.document_numbers is not None:
                norm_nums = set(filters.normalized_document_numbers() or [])
                if (
                    ch.document_number is None
                    or normalize_identifier(ch.document_number) not in norm_nums
                ):
                    respected = False
                    break
            if filters.issuers is not None:
                low_iss = [i.lower() for i in filters.issuers]
                if ch.issuer is None or ch.issuer.lower() not in low_iss:
                    respected = False
                    break
            if filters.issued_date_from is not None:
                if (
                    ch.issued_date is None
                    or date.fromisoformat(ch.issued_date) < filters.issued_date_from
                ):
                    respected = False
                    break
            if filters.issued_date_to is not None:
                if (
                    ch.issued_date is None
                    or date.fromisoformat(ch.issued_date) > filters.issued_date_to
                ):
                    respected = False
                    break
        metadata_filter_respected = respected

    # Stale version leakage check from chunk provenance vs current_docs_by_id
    stale_leaked = False
    for _, c in unique_candidates:
        doc_ref = current_docs_by_id.get(c.chunk.document_id)
        if (
            doc_ref is None
            or c.chunk.parse_run_id != doc_ref.parse_run_id
            or c.chunk.document_version != doc_ref.document_version
        ):
            stale_leaked = True
            break

    # Wrong document leakage check
    wrong_doc_leaked = False
    forbidden = set(case.forbidden_document_ids)
    for doc_id in retrieved_doc_ids:
        if doc_id in forbidden:
            wrong_doc_leaked = True
            break
    if metadata_filter_respected is False:
        wrong_doc_leaked = True

    return ArchiveCaseResult(
        case_id=case.case_id,
        mode=mode,
        recall_at_1=recall_1,
        recall_at_3=recall_3,
        recall_at_5=recall_5,
        recall_at_10=recall_10,
        reciprocal_rank=reciprocal_rank,
        ndcg_at_10=ndcg_10,
        exact_identifier_hit=exact_ident_hit,
        metadata_filter_respected=metadata_filter_respected,
        stale_version_leaked=stale_leaked,
        wrong_document_leaked=wrong_doc_leaked,
        latency_ms=latency_ms,
        retrieved_document_ids=retrieved_doc_ids,
    )


async def _evaluate_mode_async(
    cases: Sequence[RetrievalQACase],
    *,
    index: ArchiveIndex,
    embedding_provider: EmbeddingProvider,
    reranker: Reranker,
    mode: str,
    top_k: int = 10,
) -> ArchiveModeReport:
    """Async evaluation worker for a single retrieval mode."""
    scope = EvidenceScope(family_id=AUTHORITATIVE_FAMILY_ID, archive_scope=True)
    all_current_docs = index.current_documents(scope)
    current_docs_by_id = {d.document_id: d for d in all_current_docs}

    # For HYBRID_RERANK mode, instantiate the orchestrator
    archive_retriever: ArchiveRetriever | None = None
    if mode == ArchiveRetrievalMode.HYBRID_RERANK:
        archive_retriever = ArchiveRetriever(
            index=index,
            embedding_provider=embedding_provider,
            reranker=reranker,
            lexical_top_k=50,
            dense_top_k=50,
            rerank_top_k=top_k,
        )

    case_results: list[ArchiveCaseResult] = []

    for case in cases:
        filters = _filter_from_case(case)
        candidates: list[ScoredChunk] = []

        started = time.perf_counter()

        if mode == ArchiveRetrievalMode.LEXICAL:
            # Single-retriever lexical mode calls the index directly
            candidates = index.search_lexical(scope, case.question, top_k=top_k, filters=filters)
        elif mode == ArchiveRetrievalMode.DENSE:
            # Single-retriever dense mode embeds query and calls the index directly
            embed_res = await embedding_provider.embed_query(case.question)
            if embed_res.vectors and embed_res.vectors[0]:
                candidates = index.search_dense(
                    scope, embed_res.vectors[0], top_k=top_k, filters=filters
                )
            else:
                candidates = []
        elif mode == ArchiveRetrievalMode.HYBRID:
            # Hybrid mode: lexical + dense from index, fused via archive RRF + identifier boost
            lex_hits = index.search_lexical(scope, case.question, top_k=50, filters=filters)
            embed_res = await embedding_provider.embed_query(case.question)
            dense_hits: list[ScoredChunk] = []
            if embed_res.vectors and embed_res.vectors[0]:
                dense_hits = index.search_dense(
                    scope, embed_res.vectors[0], top_k=50, filters=filters
                )
            allowed_docs = index.current_documents(scope, filters)
            allowed_ids = {d.document_id for d in allowed_docs}
            fused = archive_reciprocal_rank_fusion(
                [lex_hits, dense_hits], scope, allowed_documents=allowed_ids
            )
            # Exact identifier boost on fused list
            ident = extract_query_identifiers(case.question)
            if not ident.is_empty() and fused:
                sorted_cand = sorted(
                    fused,
                    key=lambda c: (
                        -identifier_match_score(
                            ident,
                            chunk_text=c.chunk.text,
                            document_number=c.chunk.document_number,
                        ),
                        c.rank,
                    ),
                )
                fused = [
                    ScoredChunk(
                        chunk=c.chunk,
                        score=c.score,
                        rank=idx,
                        retriever="fused",
                    )
                    for idx, c in enumerate(sorted_cand, start=1)
                ]
            candidates = fused[:top_k]
        elif mode == ArchiveRetrievalMode.HYBRID_RERANK:
            assert archive_retriever is not None
            ret_result = await archive_retriever.retrieve(
                case.question, scope=scope, filters=filters
            )
            candidates = ret_result.candidates[:top_k]
        else:
            raise ValueError(f"unsupported retrieval mode: {mode!r}")

        elapsed_ms = max(0.0, (time.perf_counter() - started) * 1000.0)

        case_res = _score_archive_case(
            case,
            mode=mode,
            candidates=candidates,
            latency_ms=elapsed_ms,
            current_docs_by_id=current_docs_by_id,
            filters=filters,
        )
        case_results.append(case_res)

    # Compute aggregate metrics
    num_cases = len(case_results)
    if num_cases == 0:
        return ArchiveModeReport(
            mode=mode,
            cases=[],
            recall_at_1=0.0,
            recall_at_3=0.0,
            recall_at_5=0.0,
            recall_at_10=0.0,
            mrr=0.0,
            ndcg_at_10=0.0,
            stale_version_leakage=0.0,
            wrong_document_leakage=0.0,
            latency_p50_ms=0.0,
            latency_p95_ms=0.0,
        )

    mean_rec_1 = sum(c.recall_at_1 for c in case_results) / num_cases
    mean_rec_3 = sum(c.recall_at_3 for c in case_results) / num_cases
    mean_rec_5 = sum(c.recall_at_5 for c in case_results) / num_cases
    mean_rec_10 = sum(c.recall_at_10 for c in case_results) / num_cases
    mean_mrr = sum(c.reciprocal_rank for c in case_results) / num_cases
    mean_ndcg = sum(c.ndcg_at_10 for c in case_results) / num_cases

    ident_hits = [
        c.exact_identifier_hit for c in case_results if c.exact_identifier_hit is not None
    ]
    ident_acc = (sum(1.0 for h in ident_hits if h) / len(ident_hits)) if ident_hits else None

    filter_hits = [
        c.metadata_filter_respected for c in case_results if c.metadata_filter_respected is not None
    ]
    filter_acc = (sum(1.0 for h in filter_hits if h) / len(filter_hits)) if filter_hits else None

    stale_leakage = sum(1.0 for c in case_results if c.stale_version_leaked) / num_cases
    wrong_leakage = sum(1.0 for c in case_results if c.wrong_document_leaked) / num_cases

    latencies = [c.latency_ms for c in case_results]
    p50 = _percentile(latencies, 50.0)
    p95 = _percentile(latencies, 95.0)

    # Per-document-type slicing
    per_doc_type: dict[str, dict[str, float]] = {}
    cases_by_type: dict[str, list[ArchiveCaseResult]] = {}
    for case, c_res in zip(cases, case_results, strict=True):
        # Infer document type from expected document or scope
        dtype: str = "unknown"
        if case.expected_document_ids:
            doc_id = case.expected_document_ids[0]
            if doc_id in current_docs_by_id and current_docs_by_id[doc_id].document_type:
                dtype = current_docs_by_id[doc_id].document_type or "unknown"
        elif "document_type" in case.required_metadata_scope:
            dtype = case.required_metadata_scope["document_type"]
        cases_by_type.setdefault(dtype, []).append(c_res)

    for dtype, d_cases in cases_by_type.items():
        n = len(d_cases)
        per_doc_type[dtype] = {
            "recall_at_1": sum(c.recall_at_1 for c in d_cases) / n,
            "recall_at_5": sum(c.recall_at_5 for c in d_cases) / n,
            "recall_at_10": sum(c.recall_at_10 for c in d_cases) / n,
            "mrr": sum(c.reciprocal_rank for c in d_cases) / n,
            "ndcg_at_10": sum(c.ndcg_at_10 for c in d_cases) / n,
            "case_count": float(n),
        }

    return ArchiveModeReport(
        mode=mode,
        cases=case_results,
        recall_at_1=mean_rec_1,
        recall_at_3=mean_rec_3,
        recall_at_5=mean_rec_5,
        recall_at_10=mean_rec_10,
        mrr=mean_mrr,
        ndcg_at_10=mean_ndcg,
        exact_identifier_accuracy=ident_acc,
        metadata_filter_accuracy=filter_acc,
        stale_version_leakage=stale_leakage,
        wrong_document_leakage=wrong_leakage,
        latency_p50_ms=p50,
        latency_p95_ms=p95,
        per_document_type=per_doc_type,
    )


def evaluate_archive_retrieval(
    cases: Sequence[RetrievalQACase],
    *,
    index: ArchiveIndex,
    embedding_provider: EmbeddingProvider,
    reranker: Reranker,
    mode: ArchiveRetrievalMode | str,
) -> ArchiveModeReport:
    """Evaluate archive retrieval for a given mode synchronously."""
    mode_str = str(mode)
    return asyncio.run(
        _evaluate_mode_async(
            cases,
            index=index,
            embedding_provider=embedding_provider,
            reranker=reranker,
            mode=mode_str,
        )
    )


def compare_archive_baselines(
    cases: Sequence[RetrievalQACase],
    *,
    index: ArchiveIndex,
    embedding_provider: EmbeddingProvider,
    reranker: Reranker,
) -> ArchiveBaselineComparison:
    """Run evaluation across all four retrieval modes and return comparison."""
    modes = [
        ArchiveRetrievalMode.LEXICAL,
        ArchiveRetrievalMode.DENSE,
        ArchiveRetrievalMode.HYBRID,
        ArchiveRetrievalMode.HYBRID_RERANK,
    ]
    reports: list[ArchiveModeReport] = []
    for mode in modes:
        report = evaluate_archive_retrieval(
            cases,
            index=index,
            embedding_provider=embedding_provider,
            reranker=reranker,
            mode=mode,
        )
        reports.append(report)
    return ArchiveBaselineComparison(modes=reports)


__all__ = [
    "ArchiveBaselineComparison",
    "ArchiveCaseResult",
    "ArchiveModeReport",
    "ArchiveRetrievalMode",
    "compare_archive_baselines",
    "evaluate_archive_retrieval",
    "load_archive_cases",
]
