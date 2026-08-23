"""Deterministic retrieval evaluation for the Phase 4 single-document contract.

This module evaluates retrieval candidates, not generated answers.  It reuses the
Phase 3.5 :class:`RetrievalQACase` shape and the Phase 4 ``ScoredChunk`` result
contract.  A case must pin the complete provenance tuple in
``required_metadata_scope``; otherwise retrieval evaluation would be unable to
distinguish current evidence from stale or foreign evidence.

The harness accepts either the synchronous lexical retriever or the asynchronous
dense retriever.  It never imports a model SDK or performs network I/O; callers
inject an in-repository retriever (normally backed by the deterministic fake
embedding provider for dense evaluation).
"""

from __future__ import annotations

import asyncio
import inspect
import json
import math
import time
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Protocol, cast

from pydantic import BaseModel, ConfigDict, Field

from mamagift_retrieval.chunk import Chunk
from mamagift_retrieval.index.protocol import AUTHORITATIVE_FAMILY_ID
from mamagift_retrieval.scope import EvidenceScope
from mamagift_retrieval.search.types import ScoredChunk

from .schemas import RetrievalQACase


class RetrievalSearch(Protocol):
    """The narrow search seam consumed by the harness."""

    def search(
        self,
        query: str,
        *,
        scope: EvidenceScope,
        top_k: int,
    ) -> Sequence[ScoredChunk] | Awaitable[Sequence[ScoredChunk]]:
        """Return ranked candidates for the exact requested scope."""


RetrieverLike = (
    RetrievalSearch | Callable[..., Sequence[ScoredChunk] | Awaitable[Sequence[ScoredChunk]]]
)


class _SearchCallable(Protocol):
    def __call__(
        self,
        query: str,
        *,
        scope: EvidenceScope,
        top_k: int,
    ) -> Sequence[ScoredChunk] | Awaitable[Sequence[ScoredChunk]]: ...


class RetrievalCaseResult(BaseModel):
    """Machine-readable metrics and diagnostics for one retrieval case."""

    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1)
    retrieved_chunk_ids: list[str] = Field(default_factory=list)
    relevant_chunk_or_block_ids: list[str] = Field(default_factory=list)
    foreign_chunk_ids: list[str] = Field(default_factory=list)
    duplicate_chunk_ids: list[str] = Field(default_factory=list)
    recall_at_1: float = Field(ge=0.0, le=1.0)
    recall_at_3: float = Field(ge=0.0, le=1.0)
    recall_at_5: float = Field(ge=0.0, le=1.0)
    recall_at_10: float = Field(ge=0.0, le=1.0)
    mrr: float = Field(ge=0.0, le=1.0)
    ndcg: float = Field(ge=0.0, le=1.0)
    exact_document_number_retrieval: float | None = Field(default=None, ge=0.0, le=1.0)
    metadata_version_isolation: float = Field(ge=0.0, le=1.0)
    latency_ms: float = Field(ge=0.0)


class RetrievalAggregateMetrics(BaseModel):
    """Macro-averaged retrieval metrics over the evaluated cases."""

    model_config = ConfigDict(extra="forbid")

    case_count: int = Field(ge=0)
    recall_at_1: float = Field(ge=0.0, le=1.0)
    recall_at_3: float = Field(ge=0.0, le=1.0)
    recall_at_5: float = Field(ge=0.0, le=1.0)
    recall_at_10: float = Field(ge=0.0, le=1.0)
    mrr: float = Field(ge=0.0, le=1.0)
    ndcg: float = Field(ge=0.0, le=1.0)
    exact_document_number_retrieval: float | None = Field(default=None, ge=0.0, le=1.0)
    metadata_version_isolation: float = Field(ge=0.0, le=1.0)
    mean_latency_ms: float = Field(ge=0.0)
    max_latency_ms: float = Field(ge=0.0)


class RetrievalEvaluationReport(BaseModel):
    """Stable machine-readable report with a deterministic human rendering."""

    model_config = ConfigDict(extra="forbid")

    retriever: str = Field(min_length=1)
    top_k: int = Field(ge=1)
    cases: list[RetrievalCaseResult]
    metrics: RetrievalAggregateMetrics

    def to_json(self, *, indent: int = 2) -> str:
        """Return the report as stable machine-readable JSON."""
        return self.model_dump_json(indent=indent)

    def to_markdown(self) -> str:
        """Return a compact human-readable report without nondeterministic fields."""
        m = self.metrics
        lines = [
            "# Retrieval evaluation",
            "",
            f"Retriever: `{self.retriever}`  ",
            f"Cases: {m.case_count}  ",
            f"Top-k: {self.top_k}",
            "",
            "| Metric | Value |",
            "| --- | ---: |",
            f"| Recall@1 | {m.recall_at_1:.4f} |",
            f"| Recall@3 | {m.recall_at_3:.4f} |",
            f"| Recall@5 | {m.recall_at_5:.4f} |",
            f"| Recall@10 | {m.recall_at_10:.4f} |",
            f"| MRR | {m.mrr:.4f} |",
            f"| nDCG | {m.ndcg:.4f} |",
            f"| Exact document number | {_format_optional(m.exact_document_number_retrieval)} |",
            f"| Metadata/version isolation | {m.metadata_version_isolation:.4f} |",
            f"| Mean latency (ms) | {m.mean_latency_ms:.3f} |",
            f"| Max latency (ms) | {m.max_latency_ms:.3f} |",
            "",
            "## Cases",
            "",
            "| Case | Recall@1 | Recall@3 | MRR | nDCG | Isolation | Latency (ms) |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
        for case in self.cases:
            lines.append(
                f"| `{case.case_id}` | {case.recall_at_1:.4f} | "
                f"{case.recall_at_3:.4f} | {case.mrr:.4f} | {case.ndcg:.4f} | "
                f"{case.metadata_version_isolation:.4f} | {case.latency_ms:.3f} |"
            )
        return "\n".join(lines) + "\n"


class RetrievalEvaluationHarness:
    """Run deterministic cases against an injected in-repository retriever."""

    def __init__(
        self, retriever: RetrieverLike, *, top_k: int = 10, name: str | None = None
    ) -> None:
        if top_k <= 0:
            raise ValueError("top_k must be positive")
        self._retriever = retriever
        self._top_k = top_k
        self._name = name or type(retriever).__name__

    async def run_async(self, cases: Iterable[RetrievalQACase]) -> RetrievalEvaluationReport:
        """Evaluate cases in input order, awaiting asynchronous retrievers."""
        case_list = list(cases)
        results: list[RetrievalCaseResult] = []
        for case in case_list:
            results.append(await self._run_case(case))
        return _build_report(self._name, self._top_k, results)

    def run(self, cases: Iterable[RetrievalQACase]) -> RetrievalEvaluationReport:
        """Synchronous entry point for CI and command-line harnesses."""
        return asyncio.run(self.run_async(cases))

    async def _run_case(self, case: RetrievalQACase) -> RetrievalCaseResult:
        scope = _scope_for_case(case)
        started = time.perf_counter()
        raw_result = _invoke_search(self._retriever, case.question, scope, self._top_k)
        if inspect.isawaitable(raw_result):
            raw_result = await raw_result
        elapsed_ms = max(0.0, (time.perf_counter() - started) * 1000.0)
        candidates = _validate_result_types(raw_result)
        return _score_case(case, scope, candidates, elapsed_ms, self._top_k)


def evaluate_retrieval(
    cases: Iterable[RetrievalQACase],
    retriever: RetrieverLike,
    *,
    top_k: int = 10,
    name: str | None = None,
) -> RetrievalEvaluationReport:
    """Convenience wrapper for :class:`RetrievalEvaluationHarness`."""
    return RetrievalEvaluationHarness(retriever, top_k=top_k, name=name).run(cases)


def load_retrieval_cases(path: str | Path) -> list[RetrievalQACase]:
    """Load a JSON array (or ``{"cases": [...]}``) of sanitized eval cases."""
    case_path = Path(path)
    try:
        payload = json.loads(case_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{case_path}: invalid JSON: {exc.msg}") from exc
    if isinstance(payload, Mapping):
        payload = payload.get("cases")
    if not isinstance(payload, list) or not payload:
        raise ValueError(f"{case_path}: expected a non-empty JSON case list")
    cases = [RetrievalQACase.model_validate(item) for item in payload]
    case_ids = [case.case_id for case in cases]
    if len(set(case_ids)) != len(case_ids):
        raise ValueError(f"{case_path}: duplicate case_id")
    return cases


def _scope_for_case(case: RetrievalQACase) -> EvidenceScope:
    metadata = case.required_metadata_scope
    document_id = metadata.get("document_id")
    if document_id is None:
        if len(case.expected_document_ids) != 1:
            raise ValueError(f"case {case.case_id!r} must pin one document_id")
        document_id = case.expected_document_ids[0]
    if document_id not in case.expected_document_ids:
        raise ValueError(f"case {case.case_id!r} scope document_id is not expected")

    version_raw = metadata.get("document_version")
    parse_run_id = metadata.get("parse_run_id")
    if version_raw is None or parse_run_id is None or not parse_run_id:
        raise ValueError(
            f"case {case.case_id!r} must pin document_version and parse_run_id "
            "for retrieval isolation"
        )
    try:
        document_version = int(version_raw)
    except ValueError as exc:
        raise ValueError(f"case {case.case_id!r} has non-integer document_version") from exc
    if document_version < 1:
        raise ValueError(f"case {case.case_id!r} document_version must be positive")
    family_id = metadata.get("family_id", AUTHORITATIVE_FAMILY_ID)
    if family_id != AUTHORITATIVE_FAMILY_ID:
        raise ValueError(f"case {case.case_id!r} has unsupported family_id {family_id!r}")

    return EvidenceScope(
        family_id=family_id,
        document_id=document_id,
        document_version=document_version,
        parse_run_id=parse_run_id,
    )


def _invoke_search(
    retriever: RetrieverLike,
    question: str,
    scope: EvidenceScope,
    top_k: int,
) -> Sequence[ScoredChunk] | Awaitable[Sequence[ScoredChunk]]:
    if hasattr(retriever, "search"):
        search = cast(_SearchCallable, retriever.search)
    else:
        search = cast(_SearchCallable, retriever)
    return search(question, scope=scope, top_k=top_k)


def _validate_result_types(results: Sequence[ScoredChunk]) -> list[ScoredChunk]:
    if not isinstance(results, Sequence):
        raise TypeError("retriever search must return a sequence of ScoredChunk values")
    for result in results:
        if not isinstance(result, ScoredChunk):
            raise TypeError("retriever search returned a non-ScoredChunk value")
    return list(results)


def _score_case(
    case: RetrievalQACase,
    scope: EvidenceScope,
    results: Sequence[ScoredChunk],
    latency_ms: float,
    top_k: int,
) -> RetrievalCaseResult:
    unique: list[tuple[int, ScoredChunk]] = []
    seen_ids: set[str] = set()
    duplicate_ids: list[str] = []
    for position, result in enumerate(results, start=1):
        chunk_id = result.chunk.chunk_id
        if chunk_id in seen_ids:
            if chunk_id not in duplicate_ids:
                duplicate_ids.append(chunk_id)
            continue
        seen_ids.add(chunk_id)
        unique.append((position, result))

    expected_ids = _expected_relevance_ids(case)
    matched_by_position: dict[int, set[str]] = {}
    foreign_ids: list[str] = []
    valid_results: list[tuple[int, ScoredChunk]] = []
    for position, result in unique:
        if not _chunk_matches_scope(result.chunk, scope, case.required_metadata_scope):
            foreign_ids.append(result.chunk.chunk_id)
            continue
        valid_results.append((position, result))
        matched = _matched_relevance_ids(case, result.chunk, expected_ids)
        if matched:
            matched_by_position[position] = matched

    recalls = {k: _recall_at_k(expected_ids, matched_by_position, k) for k in (1, 3, 5, 10)}
    first_relevant = min(matched_by_position, default=None)
    mrr = 0.0 if first_relevant is None else 1.0 / first_relevant
    ndcg = _ndcg(matched_by_position, len(expected_ids), top_k)

    expected_number = case.required_metadata_scope.get("document_number")
    exact_number: float | None = None
    if expected_number is not None:
        exact_number = float(
            any(result.chunk.document_number == expected_number for _, result in valid_results)
        )

    return RetrievalCaseResult(
        case_id=case.case_id,
        retrieved_chunk_ids=[result.chunk.chunk_id for _, result in unique],
        relevant_chunk_or_block_ids=sorted(
            {
                identifier
                for identifiers in matched_by_position.values()
                for identifier in identifiers
            }
        ),
        foreign_chunk_ids=foreign_ids,
        duplicate_chunk_ids=duplicate_ids,
        recall_at_1=recalls[1],
        recall_at_3=recalls[3],
        recall_at_5=recalls[5],
        recall_at_10=recalls[10],
        mrr=mrr,
        ndcg=ndcg,
        exact_document_number_retrieval=exact_number,
        metadata_version_isolation=float(not foreign_ids),
        latency_ms=latency_ms,
    )


def _chunk_matches_scope(chunk: Chunk, scope: EvidenceScope, metadata: Mapping[str, str]) -> bool:
    """Check recorded provenance and metadata; caller scope is never trusted over chunk data."""
    if chunk.document_id != scope.document_id:
        return False
    if chunk.document_version != scope.document_version:
        return False
    if chunk.parse_run_id != scope.parse_run_id:
        return False
    for key, expected in metadata.items():
        if key in {
            "family_id",
            "document_id",
            "document_version",
            "parse_run_id",
            # Document number has its own exact-retrieval metric below; retaining
            # a wrong number here as a valid candidate makes that metric observable.
            "document_number",
        }:
            continue
        actual: object = getattr(chunk, key, chunk.metadata.get(key))
        if str(actual) != expected:
            return False
    return True


def _expected_relevance_ids(case: RetrievalQACase) -> set[str]:
    if case.expected_chunk_ids:
        return set(case.expected_chunk_ids)
    if case.expected_block_ids:
        return set(case.expected_block_ids)
    return set(case.expected_document_ids)


def _matched_relevance_ids(
    case: RetrievalQACase,
    chunk: Chunk,
    expected_ids: set[str],
) -> set[str]:
    if case.expected_chunk_ids:
        return {chunk.chunk_id} if chunk.chunk_id in expected_ids else set()
    if case.expected_block_ids:
        return set(chunk.source_block_ids).intersection(expected_ids)
    return {chunk.document_id} if chunk.document_id in expected_ids else set()


def _recall_at_k(expected_ids: set[str], matches: Mapping[int, set[str]], k: int) -> float:
    if not expected_ids:
        return 0.0
    found = {identifier for rank, ids in matches.items() if rank <= k for identifier in ids}
    return len(found) / len(expected_ids)


def _ndcg(matches: Mapping[int, set[str]], expected_count: int, top_k: int) -> float:
    if not matches:
        return 0.0
    dcg = sum(1.0 / math.log2(rank + 1) for rank, ids in matches.items() if rank <= top_k and ids)
    ideal_relevant = min(expected_count, top_k)
    # There is at least one match when this function is called with non-empty matches.
    ideal_dcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_relevant + 1))
    return dcg / ideal_dcg if ideal_dcg else 0.0


def _build_report(
    name: str,
    top_k: int,
    cases: list[RetrievalCaseResult],
) -> RetrievalEvaluationReport:
    count = len(cases)

    def mean(values: Iterable[float]) -> float:
        values_list = list(values)
        return sum(values_list) / len(values_list) if values_list else 0.0

    exact_values = [
        value
        for value in (case.exact_document_number_retrieval for case in cases)
        if value is not None
    ]
    metrics = RetrievalAggregateMetrics(
        case_count=count,
        recall_at_1=mean(case.recall_at_1 for case in cases),
        recall_at_3=mean(case.recall_at_3 for case in cases),
        recall_at_5=mean(case.recall_at_5 for case in cases),
        recall_at_10=mean(case.recall_at_10 for case in cases),
        mrr=mean(case.mrr for case in cases),
        ndcg=mean(case.ndcg for case in cases),
        exact_document_number_retrieval=mean(exact_values) if exact_values else None,
        metadata_version_isolation=mean(case.metadata_version_isolation for case in cases),
        mean_latency_ms=mean(case.latency_ms for case in cases),
        max_latency_ms=max((case.latency_ms for case in cases), default=0.0),
    )
    return RetrievalEvaluationReport(retriever=name, top_k=top_k, cases=cases, metrics=metrics)


def _format_optional(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.4f}"


__all__ = [
    "RetrievalAggregateMetrics",
    "RetrievalCaseResult",
    "RetrievalEvaluationHarness",
    "RetrievalEvaluationReport",
    "RetrievalSearch",
    "evaluate_retrieval",
    "load_retrieval_cases",
]
