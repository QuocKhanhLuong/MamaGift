"""Deterministic contract tests for the Phase 4 QA orchestration service."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence

import pytest
from mamagift_rag.schema import QaAnswer

from mamagift_contracts.errors import WorkerError, WorkerErrorCode
from mamagift_contracts.llm import ChatMessage
from mamagift_rag.service import QaService
from mamagift_retrieval.chunk import Chunk, ChunkType
from mamagift_retrieval.evidence import EvidenceSet
from mamagift_retrieval.index import IndexEntry, IndexStats
from mamagift_retrieval.providers import FakeChatProvider, FakeEmbeddingProvider
from mamagift_retrieval.rerank import FakeReranker
from mamagift_retrieval.scope import EvidenceScope
from mamagift_retrieval.search.types import ScoredChunk


def _scope(
    *,
    document_id: str = "doc-1",
    document_version: int = 2,
    parse_run_id: str = "run-2",
) -> EvidenceScope:
    return EvidenceScope(
        family_id="mamagift",
        document_id=document_id,
        document_version=document_version,
        parse_run_id=parse_run_id,
    )


def _chunk(
    chunk_id: str,
    *,
    document_id: str = "doc-1",
    document_version: int = 2,
    parse_run_id: str = "run-2",
    text: str = "Điều 1 quy định thời hạn giải quyết hồ sơ.",
) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        document_id=document_id,
        document_version=document_version,
        parse_run_id=parse_run_id,
        chunk_type=ChunkType.LEGAL_ARTICLE,
        text=text,
        source_block_ids=[f"block-{chunk_id}"],
        source_page_numbers=[1],
        section_path=["Điều 1"],
    )


class RecordingIndex:
    """Small scope-aware deterministic fake implementing DocumentIndex."""

    def __init__(
        self,
        chunks: Sequence[Chunk],
        *,
        lexical_chunks: Sequence[Chunk] | None = None,
        dense_chunks: Sequence[Chunk] | None = None,
    ) -> None:
        self.chunks = list(chunks)
        self.lexical_chunks = list(lexical_chunks if lexical_chunks is not None else chunks)
        self.dense_chunks = list(dense_chunks if dense_chunks is not None else chunks)
        self.scopes: list[EvidenceScope] = []

    def replace(self, scope: EvidenceScope, entries: list[IndexEntry]) -> IndexStats:
        raise NotImplementedError

    def stats(self, scope: EvidenceScope) -> IndexStats:
        self.scopes.append(scope)
        return IndexStats(
            document_id=scope.document_id or "",
            parse_run_id=scope.parse_run_id or "",
            document_version=scope.document_version,
            total_chunks=len(self.chunks),
            embedded_chunks=len(self.chunks),
            embedding_model="fake-bge-m3",
            embedding_version="fake-bge-m3-v1",
        )

    def search_lexical(self, scope: EvidenceScope, query: str, top_k: int) -> list[ScoredChunk]:
        self.scopes.append(scope)
        return [
            ScoredChunk(chunk=chunk, score=1.0, rank=index, retriever="lexical")
            for index, chunk in enumerate(self.lexical_chunks[:top_k], start=1)
        ]

    def search_dense(
        self, scope: EvidenceScope, query_vector: list[float], top_k: int
    ) -> list[ScoredChunk]:
        self.scopes.append(scope)
        return [
            ScoredChunk(chunk=chunk, score=1.0, rank=index, retriever="dense")
            for index, chunk in enumerate(self.dense_chunks[:top_k], start=1)
        ]

    def drop(self, scope: EvidenceScope) -> int:
        raise NotImplementedError


def _service(
    index: RecordingIndex,
    chat: FakeChatProvider,
    *,
    chunk_tree: Sequence[Chunk] = (),
) -> QaService:
    return QaService(
        chat_provider=chat,
        embedding_provider=FakeEmbeddingProvider(),
        document_index=index,
        reranker=FakeReranker(ordering=["c1"]),
        chunk_tree=chunk_tree,
    )


def _run(service: QaService, question: str, scope: EvidenceScope) -> QaAnswer:
    return asyncio.run(service.answer(question, scope=scope))


def _answer_json(*, citation_id: str = "c1", document_id: str = "doc-1") -> str:
    return json.dumps(
        {
            "answer": "Hồ sơ được giải quyết trong thời hạn quy định.",
            "status": "answered",
            "citations": [
                {
                    "citation_id": citation_id,
                    "document_id": document_id,
                    "page_number": 1,
                    "block_ids": ["block-c1"],
                    "quote": "Điều 1 quy định thời hạn giải quyết hồ sơ.",
                }
            ],
        }
    )


@pytest.mark.unit
def test_happy_path_citations_are_from_assembled_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    chunk = _chunk("c1")
    index = RecordingIndex([chunk])
    chat = FakeChatProvider(responses=[_answer_json()])
    seen: list[EvidenceSet] = []

    import mamagift_rag.service as service_module

    original = service_module.build_grounded_prompt

    def capture(question: str, evidence: EvidenceSet) -> list[ChatMessage]:
        seen.append(evidence)
        return original(question, evidence)

    monkeypatch.setattr(service_module, "build_grounded_prompt", capture)
    answer = _run(_service(index, chat, chunk_tree=[chunk]), "Thời hạn là bao lâu?", _scope())

    assert answer.status == "answered"
    assert answer.citations
    assert seen
    evidence_ids = {item.citation_id for item in seen[0].evidence}
    assert {item.citation_id for item in answer.citations} <= evidence_ids
    assert len(chat.calls) == 1


@pytest.mark.unit
def test_worker_unavailable_returns_explicit_status_without_partial_answer() -> None:
    chunk = _chunk("c1")
    index = RecordingIndex([chunk])
    chat = FakeChatProvider(responses=[WorkerError(WorkerErrorCode.UNAVAILABLE, "offline")])

    answer = _run(_service(index, chat, chunk_tree=[chunk]), "Thời hạn là bao lâu?", _scope())

    assert answer.status == "ai_worker_unavailable"
    assert answer.citations == []
    assert answer.retrieval.query_id.startswith("qry_")


@pytest.mark.unit
def test_insufficient_evidence_abstains_without_calling_worker() -> None:
    index = RecordingIndex([_chunk("indexed")], lexical_chunks=[], dense_chunks=[])
    chat = FakeChatProvider(responses=[_answer_json()])

    answer = _run(_service(index, chat), "Câu hỏi không có chứng cứ", _scope())

    assert answer.status == "insufficient_evidence"
    assert answer.citations == []
    assert chat.calls == []


@pytest.mark.unit
def test_hallucinated_citation_is_rejected() -> None:
    chunk = _chunk("c1")
    index = RecordingIndex([chunk])
    chat = FakeChatProvider(responses=[_answer_json(citation_id="c999")])

    answer = _run(_service(index, chat, chunk_tree=[chunk]), "Thời hạn là bao lâu?", _scope())

    assert answer.status == "failed"
    assert answer.citations == []
    assert "c999" not in answer.answer


@pytest.mark.unit
def test_scope_is_checked_at_every_retrieval_boundary() -> None:
    chunk = _chunk("other", document_id="doc-2")
    index = RecordingIndex([_chunk("indexed")], lexical_chunks=[chunk], dense_chunks=[chunk])
    chat = FakeChatProvider(responses=[_answer_json()])

    answer = _run(_service(index, chat), "Thời hạn là bao lâu?", _scope())

    assert answer.status == "failed"
    assert chat.calls == []
    assert all(item == _scope() for item in index.scopes)


@pytest.mark.unit
def test_stale_parse_run_is_not_reachable_from_current_query() -> None:
    stale = _chunk("stale", parse_run_id="run-1", document_version=1)
    index = RecordingIndex([_chunk("current")], lexical_chunks=[stale], dense_chunks=[stale])
    chat = FakeChatProvider(responses=[_answer_json()])

    answer = _run(_service(index, chat), "Thời hạn là bao lâu?", _scope())

    assert answer.status == "failed"
    assert chat.calls == []


@pytest.mark.unit
def test_query_id_is_unique_per_request() -> None:
    chunk = _chunk("c1")
    index = RecordingIndex([chunk])
    chat = FakeChatProvider(responses=[_answer_json(), _answer_json()])
    service = _service(index, chat, chunk_tree=[chunk])

    first = _run(service, "Thời hạn là bao lâu?", _scope())
    second = _run(service, "Thời hạn là bao lâu?", _scope())

    assert first.retrieval.query_id != second.retrieval.query_id
    assert first.retrieval.query_id.startswith("qry_")
    assert second.retrieval.query_id.startswith("qry_")
