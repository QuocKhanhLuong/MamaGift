"""Contract tests for archive-scoped rerank candidate validation."""

from __future__ import annotations

import asyncio

import pytest

from mamagift_retrieval.chunk import Chunk, ChunkType
from mamagift_retrieval.rerank import FakeReranker
from mamagift_retrieval.rerank.protocol import (
    validate_archive_rerank_candidates,
    validate_rerank_candidates,
)
from mamagift_retrieval.search.types import ScoredChunk


def _chunk(
    chunk_id: str,
    *,
    document_id: str = "doc-1",
    document_version: int | None = 1,
    parse_run_id: str = "run-1",
) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        document_id=document_id,
        parse_run_id=parse_run_id,
        document_version=document_version,
        chunk_type=ChunkType.PARAGRAPH,
        text=f"text for {chunk_id}",
        source_block_ids=[f"block-{chunk_id}"],
        source_page_numbers=[1],
    )


def test_multi_document_candidates_pass_archive_and_fail_single_doc_validator() -> None:
    candidates = [
        ScoredChunk(
            chunk=_chunk("c1", document_id="doc-1", document_version=1, parse_run_id="run-1"),
            score=0.9,
            rank=1,
            retriever="dense",
        ),
        ScoredChunk(
            chunk=_chunk("c2", document_id="doc-2", document_version=1, parse_run_id="run-2"),
            score=0.8,
            rank=2,
            retriever="lexical",
        ),
    ]
    # Archive validator accepts candidates spanning multiple documents
    validate_archive_rerank_candidates(candidates)

    # Single-document validator rejects multi-document candidates
    with pytest.raises(ValueError, match="document, version, and parse run"):
        validate_rerank_candidates(candidates)


def test_duplicate_chunk_id_raises() -> None:
    candidates = [
        ScoredChunk(
            chunk=_chunk("c1", document_id="doc-1", document_version=1, parse_run_id="run-1"),
            score=0.9,
            rank=1,
            retriever="dense",
        ),
        ScoredChunk(
            chunk=_chunk("c1", document_id="doc-1", document_version=1, parse_run_id="run-1"),
            score=0.8,
            rank=2,
            retriever="lexical",
        ),
    ]
    with pytest.raises(ValueError, match="unique chunk identities"):
        validate_archive_rerank_candidates(candidates)


def test_two_parse_runs_of_same_document_in_one_batch_raises() -> None:
    candidates = [
        ScoredChunk(
            chunk=_chunk("c1", document_id="doc-1", document_version=1, parse_run_id="run-1"),
            score=0.9,
            rank=1,
            retriever="dense",
        ),
        ScoredChunk(
            chunk=_chunk("c2", document_id="doc-1", document_version=2, parse_run_id="run-2"),
            score=0.8,
            rank=2,
            retriever="lexical",
        ),
    ]
    with pytest.raises(ValueError) as exc_info:
        validate_archive_rerank_candidates(candidates)

    err_msg = str(exc_info.value)
    assert "doc-1" in err_msg
    assert "run-1" in err_msg
    assert "run-2" in err_msg


def test_two_different_documents_with_different_parse_runs_is_fine() -> None:
    candidates = [
        ScoredChunk(
            chunk=_chunk("c1", document_id="doc-A", document_version=1, parse_run_id="run-A"),
            score=0.9,
            rank=1,
            retriever="dense",
        ),
        ScoredChunk(
            chunk=_chunk("c2", document_id="doc-B", document_version=3, parse_run_id="run-B"),
            score=0.8,
            rank=2,
            retriever="lexical",
        ),
        ScoredChunk(
            chunk=_chunk("c3", document_id="doc-A", document_version=1, parse_run_id="run-A"),
            score=0.7,
            rank=3,
            retriever="dense",
        ),
    ]
    # No exception raised for multiple documents with their own consistent parse runs
    validate_archive_rerank_candidates(candidates)


def test_missing_provenance_raises() -> None:
    cand_none_version = [
        ScoredChunk(
            chunk=_chunk("c1", document_id="doc-1", document_version=None, parse_run_id="run-1"),
            score=0.9,
            rank=1,
            retriever="dense",
        )
    ]
    with pytest.raises(ValueError, match="document_version"):
        validate_archive_rerank_candidates(cand_none_version)

    cand_empty_parse_run = [
        ScoredChunk(
            chunk=Chunk.model_construct(
                chunk_id="c2",
                document_id="doc-1",
                parse_run_id="",
                document_version=1,
                chunk_type=ChunkType.PARAGRAPH,
                text="text",
                source_block_ids=["b1"],
                source_page_numbers=[1],
            ),
            score=0.9,
            rank=1,
            retriever="dense",
        )
    ]
    with pytest.raises(ValueError, match="parse_run_id"):
        validate_archive_rerank_candidates(cand_empty_parse_run)

    cand_empty_doc_id = [
        ScoredChunk(
            chunk=Chunk.model_construct(
                chunk_id="c3",
                document_id="",
                parse_run_id="run-1",
                document_version=1,
                chunk_type=ChunkType.PARAGRAPH,
                text="text",
                source_block_ids=["b1"],
                source_page_numbers=[1],
            ),
            score=0.9,
            rank=1,
            retriever="dense",
        )
    ]
    with pytest.raises(ValueError, match="document_id"):
        validate_archive_rerank_candidates(cand_empty_doc_id)


def test_allowed_documents_filtering() -> None:
    candidates = [
        ScoredChunk(
            chunk=_chunk("c1", document_id="doc-1", document_version=1, parse_run_id="run-1"),
            score=0.9,
            rank=1,
            retriever="dense",
        ),
        ScoredChunk(
            chunk=_chunk("c2", document_id="doc-2", document_version=1, parse_run_id="run-2"),
            score=0.8,
            rank=2,
            retriever="lexical",
        ),
    ]
    # Allowed set contains both -> passes
    validate_archive_rerank_candidates(candidates, allowed_documents={"doc-1", "doc-2"})

    # Allowed set missing doc-2 -> raises naming c2 and doc-2
    with pytest.raises(ValueError) as exc_info:
        validate_archive_rerank_candidates(candidates, allowed_documents={"doc-1"})
    assert "c2" in str(exc_info.value)
    assert "doc-2" in str(exc_info.value)


def test_empty_candidate_list_accepted() -> None:
    # An empty candidate list is accepted and raises nothing
    validate_archive_rerank_candidates([])
    validate_archive_rerank_candidates([], allowed_documents={"doc-1"})


def test_fake_reranker_single_document_path_untouched() -> None:
    candidates = [
        ScoredChunk(
            chunk=_chunk("c1", document_id="doc-1", document_version=1, parse_run_id="run-1"),
            score=0.5,
            rank=1,
            retriever="fused",
        ),
        ScoredChunk(
            chunk=_chunk("c2", document_id="doc-1", document_version=1, parse_run_id="run-1"),
            score=0.4,
            rank=2,
            retriever="fused",
        ),
    ]
    reranker = FakeReranker(ordering=["c2", "c1"])
    result = asyncio.run(reranker.rerank("query", candidates, 2))
    assert [item.chunk.chunk_id for item in result] == ["c2", "c1"]
    assert [item.rank for item in result] == [1, 2]
    assert [item.retriever for item in result] == ["reranked", "reranked"]
