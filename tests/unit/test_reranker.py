"""Contract tests for the provider-neutral Phase 4 reranker seam."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from mamagift_retrieval.chunk import Chunk, ChunkType
from mamagift_retrieval.rerank import CrossEncoderReranker, FakeReranker
from mamagift_retrieval.search.types import ScoredChunk


def _chunk(
    chunk_id: str,
    *,
    document_id: str = "doc-1",
    document_version: int | None = 2,
    parse_run_id: str = "run-2",
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


def _candidates(*ids: str, **kwargs: Any) -> list[ScoredChunk]:
    return [
        ScoredChunk(chunk=_chunk(chunk_id, **kwargs), score=0.5, rank=index, retriever="fused")
        for index, chunk_id in enumerate(ids, start=1)
    ]


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def test_fake_reorders_exactly_as_seeded_and_is_reproducible() -> None:
    candidates = _candidates("c1", "c2", "c3")
    first = _run(FakeReranker(ordering=["c3", "c1", "c2"]).rerank("q", candidates, 3))
    second = _run(FakeReranker(ordering=["c3", "c1", "c2"]).rerank("q", candidates, 3))

    assert [item.chunk.chunk_id for item in first] == ["c3", "c1", "c2"]
    assert first == second


def test_fake_preserves_identity_and_full_provenance_without_duplicates() -> None:
    candidates = _candidates("c1", "c2", "c3")
    result = _run(FakeReranker(ordering=["c3", "c1"]).rerank("q", candidates, 3))

    assert {item.chunk.chunk_id for item in result} == {"c1", "c2", "c3"}
    assert len(result) == len(candidates)
    by_id = {item.chunk.chunk_id: item.chunk for item in candidates}
    assert all(item.chunk is by_id[item.chunk.chunk_id] for item in result)
    assert {
        (item.chunk.document_id, item.chunk.document_version, item.chunk.parse_run_id)
        for item in result
    } == {("doc-1", 2, "run-2")}


def test_fake_output_rank_is_one_based_dense_and_matches_new_order() -> None:
    result = _run(
        FakeReranker(ordering=["c3", "c1", "c2"]).rerank("q", _candidates("c1", "c2", "c3"), 3)
    )

    assert [item.rank for item in result] == [1, 2, 3]
    assert [item.retriever for item in result] == ["reranked"] * 3


def test_top_k_is_applied_after_reranking_and_handles_bounds() -> None:
    reranker = FakeReranker(ordering=["c3", "c1", "c2"])
    candidates = _candidates("c1", "c2", "c3")

    assert [item.chunk.chunk_id for item in _run(reranker.rerank("q", candidates, 2))] == [
        "c3",
        "c1",
    ]
    assert len(_run(reranker.rerank("q", candidates, 99))) == 3
    assert _run(reranker.rerank("q", candidates, 0)) == []
    assert _run(reranker.rerank("q", candidates, -1)) == []


def test_empty_candidate_list() -> None:
    assert _run(FakeReranker(seed=11).rerank("q", [], 5)) == []


def test_duplicate_candidate_identity_is_rejected() -> None:
    candidates = _candidates("c1", "c1")

    with pytest.raises(ValueError, match="unique chunk identities"):
        _run(FakeReranker(seed=1).rerank("q", candidates, 2))


@pytest.mark.parametrize(
    "kwargs",
    [
        {"document_id": "doc-2"},
        {"document_version": 3},
        {"parse_run_id": "run-3"},
    ],
)
def test_candidate_with_disagreeing_scope_is_rejected(kwargs: dict[str, Any]) -> None:
    candidates = _candidates("c1", "c2")
    candidates[1] = ScoredChunk(chunk=_chunk("c2", **kwargs), score=0.5, rank=2, retriever="fused")

    with pytest.raises(ValueError, match="document, version, and parse run"):
        _run(FakeReranker(seed=1).rerank("q", candidates, 2))


def test_fake_reranker_version_is_stable_and_surfaced() -> None:
    first = FakeReranker(seed=7)
    second = FakeReranker(seed=7)

    assert first.reranker_version == "fake-reranker-v1"
    assert first.reranker_version == second.reranker_version


def test_cross_encoder_uses_configured_endpoint_model_and_reranks_before_truncation() -> None:
    seen: dict[str, Any] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "results": [
                    {"index": 2, "score": 0.9},
                    {"index": 0, "score": 0.8},
                    {"index": 1, "score": 0.7},
                ],
                "model": "configured-cross-encoder",
                "reranker_version": "configured-cross-encoder-v9",
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    reranker = CrossEncoderReranker(
        base_url="http://reranker.test/v1",
        model="configured-cross-encoder",
        api_key="secret",
        client=client,
    )
    result = _run(reranker.rerank("query", _candidates("c1", "c2", "c3"), 2))
    _run(client.aclose())

    assert seen["url"] == "http://reranker.test/v1/rerank"
    assert seen["payload"]["model"] == "configured-cross-encoder"
    assert seen["payload"]["top_k"] is None
    assert len(seen["payload"]["documents"]) == 3
    assert [item.chunk.chunk_id for item in result] == ["c3", "c1"]
    assert [item.rank for item in result] == [1, 2]
    assert [item.score for item in result] == [0.9, 0.8]
    assert reranker.reranker_version == "configured-cross-encoder-v1"


def test_cross_encoder_factory_reads_settings_without_importing_concrete_settings() -> None:
    settings = SimpleNamespace(
        ai_worker_base_url="http://settings.test",
        ai_worker_token="token",
        reranker_model="settings-model",
    )
    reranker = CrossEncoderReranker.from_settings(settings)  # type: ignore[arg-type]

    assert reranker.base_url == "http://settings.test"
    assert reranker.model == "settings-model"
    assert reranker.api_key == "token"
    _run(reranker.close())


def test_cross_encoder_rejects_upstream_drop_or_duplicate() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "results": [
                    {"index": 0, "score": 0.9},
                    {"index": 0, "score": 0.8},
                ],
                "model": "model",
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    reranker = CrossEncoderReranker(base_url="http://reranker.test", model="model", client=client)
    with pytest.raises(ValueError, match="each candidate exactly once"):
        _run(reranker.rerank("query", _candidates("c1", "c2", "c3"), 3))
    _run(client.aclose())
