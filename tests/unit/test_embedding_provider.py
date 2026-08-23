"""Unit tests for EmbeddingProvider protocol, FakeEmbeddingProvider, and BgeM3EmbeddingProvider."""

from __future__ import annotations

import asyncio
import json
import math
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from mamagift_contracts.embedding import EmbeddingResult
from mamagift_contracts.errors import WorkerError, WorkerErrorCode
from mamagift_retrieval.providers import (
    BgeM3EmbeddingProvider,
    EmbeddingProvider,
    FakeEmbeddingProvider,
)
from mamagift_retrieval.providers.fake_embedding import _generate_deterministic_vector


def _cosine_similarity(v1: list[float], v2: list[float]) -> float:
    return sum(a * b for a, b in zip(v1, v2, strict=True))


def _l2_norm(v: list[float]) -> float:
    return math.sqrt(sum(x * x for x in v))


# -----------------------------------------------------------------------------
# 1. Protocol & Contract Conformance
# -----------------------------------------------------------------------------


def test_embedding_provider_protocol_conformance() -> None:
    fake = FakeEmbeddingProvider()
    assert isinstance(fake, EmbeddingProvider)

    real = BgeM3EmbeddingProvider(base_url="http://localhost:8090")
    assert isinstance(real, EmbeddingProvider)


def test_embedding_result_contract_fields() -> None:
    result = EmbeddingResult(
        vectors=[[0.1, 0.2, 0.3]],
        model="test-model",
        dimension=3,
        embedding_version="test-v1",
    )
    assert result.vectors == [[0.1, 0.2, 0.3]]
    assert result.model == "test-model"
    assert result.dimension == 3
    assert result.embedding_version == "test-v1"

    # Extra fields forbidden
    with pytest.raises(ValidationError):
        EmbeddingResult(
            vectors=[[0.1]],
            model="m",
            dimension=1,
            embedding_version="v1",
            extra_field="invalid",  # type: ignore[call-arg]
        )


def test_embedding_version_is_documented_and_load_bearing() -> None:
    doc = EmbeddingProvider.__doc__ or ""
    assert "embedding_version" in doc
    assert "load-bearing" in doc or "reindex" in doc


# -----------------------------------------------------------------------------
# 2. FakeEmbeddingProvider Tests
# -----------------------------------------------------------------------------


def test_fake_embedding_provider_properties() -> None:
    provider = FakeEmbeddingProvider(
        model_id="custom-fake",
        dimension=512,
        embedding_version="fake-v2",
    )
    assert provider.model_id == "custom-fake"
    assert provider.dimension == 512
    assert provider.embedding_version == "fake-v2"


def test_fake_embedding_invalid_dimension() -> None:
    with pytest.raises(ValueError, match="Dimension must be a positive integer"):
        _generate_deterministic_vector("hello", 0)

    with pytest.raises(ValueError, match="Dimension must be a positive integer"):
        _generate_deterministic_vector("hello", -10)


def test_fake_embedding_determinism() -> None:
    provider = FakeEmbeddingProvider()
    text = "Ủy ban nhân dân Quận 1, Thành phố Hồ Chí Minh"

    res1 = asyncio.run(provider.embed_documents([text]))
    res2 = asyncio.run(provider.embed_documents([text]))

    assert res1.vectors[0] == res2.vectors[0]
    assert len(res1.vectors[0]) == provider.dimension
    assert res1.embedding_version == provider.embedding_version
    assert res1.model == provider.model_id
    assert res1.dimension == provider.dimension


def test_fake_embedding_distinctness_and_no_collision() -> None:
    provider = FakeEmbeddingProvider()
    text_a = "Văn bản số 123/UBND-VP ngày 15/01/2024"
    text_b = "Văn bản số 124/UBND-VP ngày 15/01/2024"

    res = asyncio.run(provider.embed_documents([text_a, text_b]))
    v_a = res.vectors[0]
    v_b = res.vectors[1]

    assert v_a != v_b
    assert not math.isclose(_cosine_similarity(v_a, v_b), 1.0, rel_tol=1e-5)


def test_fake_embedding_unit_l2_norm() -> None:
    provider = FakeEmbeddingProvider(dimension=256)
    texts = [
        "Hồ sơ thủ tục đăng ký kết hôn có yếu tố nước ngoài",
        "",
        "   ",
        "1234567890",
        "🎉 Đặc biệt có emoji và ký tự đặc biệt #@!$%^&*",
    ]

    res = asyncio.run(provider.embed_documents(texts))
    for v in res.vectors:
        assert len(v) == 256
        norm = _l2_norm(v)
        assert math.isclose(norm, 1.0, rel_tol=1e-5)


def test_fake_embedding_cosine_similarity_semantics() -> None:
    provider = FakeEmbeddingProvider()
    t_target = "Hồ sơ công chứng hợp đồng tặng cho bất động sản"
    t_same = "Hồ sơ công chứng hợp đồng tặng cho bất động sản"
    t_similar = "Hồ sơ công chứng hợp đồng mua bán bất động sản"
    t_different = "Quy trình đăng ký tạm trú theo luật cư trú"

    res = asyncio.run(provider.embed_documents([t_target, t_same, t_similar, t_different]))
    v_target, v_same, v_similar, v_diff = res.vectors

    sim_same = _cosine_similarity(v_target, v_same)
    sim_similar = _cosine_similarity(v_target, v_similar)
    sim_diff = _cosine_similarity(v_target, v_diff)

    assert math.isclose(sim_same, 1.0, rel_tol=1e-5)
    # Similar should have positive overlap (> 0.4) and strictly less than 1.0
    assert 0.4 < sim_similar < 0.99
    # Unrelated should have low similarity (< 0.25)
    assert sim_diff < 0.25
    assert sim_similar > sim_diff


def test_fake_embedding_batch_behavior_n_zero() -> None:
    provider = FakeEmbeddingProvider()
    res = asyncio.run(provider.embed_documents([]))
    assert res.vectors == []
    assert res.model == provider.model_id
    assert res.dimension == provider.dimension
    assert res.embedding_version == provider.embedding_version


def test_fake_embedding_batch_behavior_n_one() -> None:
    provider = FakeEmbeddingProvider()
    text = "Văn bản hướng dẫn thi hành luật đất đai"
    res_batch = asyncio.run(provider.embed_documents([text]))
    res_query = asyncio.run(provider.embed_query(text))

    assert len(res_batch.vectors) == 1
    assert len(res_query.vectors) == 1
    assert res_batch.vectors[0] == res_query.vectors[0]
    assert res_batch.model == provider.model_id
    assert res_batch.dimension == provider.dimension
    assert res_batch.embedding_version == provider.embedding_version
    assert res_query.model == provider.model_id
    assert res_query.dimension == provider.dimension
    assert res_query.embedding_version == provider.embedding_version


def test_fake_embedding_batch_behavior_n_multiple_exact_order() -> None:
    provider = FakeEmbeddingProvider()
    texts = [
        "Đoạn 0: Căn cứ luật tổ chức chính quyền địa phương",
        "Đoạn 1: Quyết định ban hành quy chế làm việc",
        "Đoạn 2: Trách nhiệm của Chánh văn phòng",
        "Đoạn 3: Hiệu lực thi hành kể từ ngày ký",
    ]

    res_batch = asyncio.run(provider.embed_documents(texts))
    assert len(res_batch.vectors) == 4
    assert res_batch.model == provider.model_id
    assert res_batch.dimension == provider.dimension
    assert res_batch.embedding_version == provider.embedding_version

    for i, t in enumerate(texts):
        res_single = asyncio.run(provider.embed_query(t))
        assert res_batch.vectors[i] == res_single.vectors[0]


# -----------------------------------------------------------------------------
# 3. BgeM3EmbeddingProvider Tests (Real Adapter)
# -----------------------------------------------------------------------------


def test_bge_m3_provider_properties_and_defaults() -> None:
    provider = BgeM3EmbeddingProvider(
        base_url="http://ai-worker:8090",
        model_id="BAAI/bge-m3",
        dimension=1024,
        embedding_version="bge-m3-v1.2",
    )
    assert provider.model_id == "BAAI/bge-m3"
    assert provider.dimension == 1024
    assert provider.embedding_version == "bge-m3-v1.2"


def test_bge_m3_constructor_validation() -> None:
    with pytest.raises(ValueError, match="base_url must not be empty"):
        BgeM3EmbeddingProvider(base_url="")

    with pytest.raises(ValueError, match="base_url must not be empty"):
        BgeM3EmbeddingProvider(base_url="   ")

    with pytest.raises(ValueError, match="model_id must not be empty"):
        BgeM3EmbeddingProvider(base_url="http://mock", model_id="")

    with pytest.raises(ValueError, match="Dimension must be a positive integer"):
        BgeM3EmbeddingProvider(base_url="http://mock", dimension=0)

    with pytest.raises(ValueError, match="Dimension must be a positive integer"):
        BgeM3EmbeddingProvider(base_url="http://mock", dimension=-10)

    with pytest.raises(ValueError, match="embedding_version must not be empty"):
        BgeM3EmbeddingProvider(base_url="http://mock", embedding_version="")

    with pytest.raises(ValueError, match="Timeout must be positive"):
        BgeM3EmbeddingProvider(base_url="http://mock", timeout=0)

    with pytest.raises(ValueError, match="Timeout must be positive"):
        BgeM3EmbeddingProvider(base_url="http://mock", timeout=-5.0)


def test_bge_m3_build_url_variations() -> None:
    p1 = BgeM3EmbeddingProvider(base_url="http://host:8090", endpoint="/v1/embeddings")
    assert p1._build_url() == "http://host:8090/v1/embeddings"

    p2 = BgeM3EmbeddingProvider(base_url="http://host:8090/", endpoint="v1/embeddings")
    assert p2._build_url() == "http://host:8090/v1/embeddings"

    p3 = BgeM3EmbeddingProvider(base_url="http://host:8090/v1", endpoint="/v1/embeddings")
    assert p3._build_url() == "http://host:8090/v1/embeddings"

    p4 = BgeM3EmbeddingProvider(base_url="http://host:8090/v1", endpoint="/embeddings")
    assert p4._build_url() == "http://host:8090/v1/embeddings"


def test_bge_m3_batch_n_zero_no_network_call() -> None:
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json={})

    transport = httpx.MockTransport(handler)

    async def _test() -> None:
        async with httpx.AsyncClient(transport=transport) as client:
            provider = BgeM3EmbeddingProvider(
                base_url="http://mock",
                client=client,
                dimension=1024,
                embedding_version="bge-m3-v1",
            )
            res = await provider.embed_documents([])
            assert res.vectors == []
            assert res.dimension == 1024
            assert res.model == "bge-m3"
            assert res.embedding_version == "bge-m3-v1"
            assert not called

    asyncio.run(_test())


def test_bge_m3_batch_n_one_and_query() -> None:
    captured_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        return httpx.Response(
            200,
            json={
                "data": [{"index": 0, "embedding": [0.1] * 1024}],
                "model": "bge-m3",
                "embedding_version": "bge-m3-v1",
            },
        )

    transport = httpx.MockTransport(handler)

    async def _test() -> None:
        async with httpx.AsyncClient(transport=transport) as client:
            provider = BgeM3EmbeddingProvider(
                base_url="http://mock",
                client=client,
                auth_token="secret-token",
                embedding_version="bge-m3-v1",
            )
            res = await provider.embed_query("truy vấn kiểm tra")

            assert len(res.vectors) == 1
            assert len(res.vectors[0]) == 1024
            assert res.model == "bge-m3"
            assert res.dimension == 1024
            assert res.embedding_version == "bge-m3-v1"

            assert len(captured_requests) == 1
            assert captured_requests[0].headers["Authorization"] == "Bearer secret-token"
            body = json.loads(captured_requests[0].content)
            assert body == {"input": ["truy vấn kiểm tra"], "model": "bge-m3"}

    asyncio.run(_test())


def test_bge_m3_batch_ordering_and_sorting_by_index() -> None:
    # Server returns items out of order (index 2, 0, 1)
    vec0 = [0.0] * 1024
    vec0[0] = 1.0
    vec1 = [0.0] * 1024
    vec1[1] = 1.0
    vec2 = [0.0] * 1024
    vec2[2] = 1.0

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": 2, "embedding": vec2},
                    {"index": 0, "embedding": vec0},
                    {"index": 1, "embedding": vec1},
                ],
                "model": "bge-m3",
                "embedding_version": "bge-m3-v1",
            },
        )

    transport = httpx.MockTransport(handler)

    async def _test() -> None:
        async with httpx.AsyncClient(transport=transport) as client:
            provider = BgeM3EmbeddingProvider(
                base_url="http://mock",
                client=client,
                embedding_version="bge-m3-v1",
            )
            res = await provider.embed_documents(["doc0", "doc1", "doc2"])

            assert len(res.vectors) == 3
            # Must be sorted strictly in order 0, 1, 2 matching input texts
            assert res.vectors[0] == vec0
            assert res.vectors[1] == vec1
            assert res.vectors[2] == vec2
            assert res.model == "bge-m3"
            assert res.dimension == 1024
            assert res.embedding_version == "bge-m3-v1"

    asyncio.run(_test())


def test_bge_m3_direct_list_response_format() -> None:
    vec0 = [0.5] * 1024
    vec1 = [0.6] * 1024

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[vec0, vec1],
        )

    transport = httpx.MockTransport(handler)

    async def _test() -> None:
        async with httpx.AsyncClient(transport=transport) as client:
            provider = BgeM3EmbeddingProvider(
                base_url="http://mock",
                client=client,
                embedding_version="bge-m3-v1",
            )
            res = await provider.embed_documents(["t0", "t1"])
            assert res.vectors == [vec0, vec1]
            assert res.model == "bge-m3"
            assert res.dimension == 1024
            assert res.embedding_version == "bge-m3-v1"

    asyncio.run(_test())


def test_bge_m3_duplicate_and_empty_text_inputs() -> None:
    vec0 = [0.1] * 1024
    vec1 = [0.2] * 1024
    vec2 = [0.3] * 1024

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": 0, "embedding": vec0},
                    {"index": 1, "embedding": vec1},
                    {"index": 2, "embedding": vec2},
                ],
                "model": "bge-m3",
            },
        )

    transport = httpx.MockTransport(handler)

    async def _test() -> None:
        async with httpx.AsyncClient(transport=transport) as client:
            provider = BgeM3EmbeddingProvider(base_url="http://mock", client=client)
            # Duplicate text and empty text
            res = await provider.embed_documents(["duplicate", "", "duplicate"])
            assert len(res.vectors) == 3
            assert res.vectors[0] == vec0
            assert res.vectors[1] == vec1
            assert res.vectors[2] == vec2

    asyncio.run(_test())


# -----------------------------------------------------------------------------
# 4. Upstream Response Strict Validation Tests
# -----------------------------------------------------------------------------


def test_bge_m3_error_fewer_embeddings_than_inputs() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        # Returned 1 vector when 2 were requested
        return httpx.Response(
            200,
            json={
                "data": [{"index": 0, "embedding": [0.1] * 1024}],
            },
        )

    transport = httpx.MockTransport(handler)

    async def _test() -> None:
        async with httpx.AsyncClient(transport=transport) as client:
            provider = BgeM3EmbeddingProvider(base_url="http://mock", client=client)
            with pytest.raises(WorkerError) as exc_info:
                await provider.embed_documents(["t1", "t2"])
            assert exc_info.value.code == WorkerErrorCode.UPSTREAM_ERROR
            assert "Embedding count mismatch: expected 2, received 1" in exc_info.value.message

    asyncio.run(_test())


def test_bge_m3_error_more_embeddings_than_inputs() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        # Returned 3 vectors when 2 were requested
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": 0, "embedding": [0.1] * 1024},
                    {"index": 1, "embedding": [0.2] * 1024},
                    {"index": 2, "embedding": [0.3] * 1024},
                ],
            },
        )

    transport = httpx.MockTransport(handler)

    async def _test() -> None:
        async with httpx.AsyncClient(transport=transport) as client:
            provider = BgeM3EmbeddingProvider(base_url="http://mock", client=client)
            with pytest.raises(WorkerError) as exc_info:
                await provider.embed_documents(["t1", "t2"])
            assert exc_info.value.code == WorkerErrorCode.UPSTREAM_ERROR
            assert "Embedding count mismatch: expected 2, received 3" in exc_info.value.message

    asyncio.run(_test())


def test_bge_m3_error_empty_data_for_nonempty_inputs() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": []})

    transport = httpx.MockTransport(handler)

    async def _test() -> None:
        async with httpx.AsyncClient(transport=transport) as client:
            provider = BgeM3EmbeddingProvider(base_url="http://mock", client=client)
            with pytest.raises(WorkerError) as exc_info:
                await provider.embed_documents(["t1", "t2"])
            assert exc_info.value.code == WorkerErrorCode.UPSTREAM_ERROR
            assert "Embedding count mismatch: expected 2, received 0" in exc_info.value.message

    asyncio.run(_test())


def test_bge_m3_error_duplicate_indices() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": 0, "embedding": [0.1] * 1024},
                    {"index": 0, "embedding": [0.2] * 1024},
                ],
            },
        )

    transport = httpx.MockTransport(handler)

    async def _test() -> None:
        async with httpx.AsyncClient(transport=transport) as client:
            provider = BgeM3EmbeddingProvider(base_url="http://mock", client=client)
            with pytest.raises(WorkerError) as exc_info:
                await provider.embed_documents(["t0", "t1"])
            assert exc_info.value.code == WorkerErrorCode.UPSTREAM_ERROR
            assert "do not form a complete permutation" in exc_info.value.message

    asyncio.run(_test())


def test_bge_m3_error_gap_in_indices() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": 0, "embedding": [0.1] * 1024},
                    {"index": 2, "embedding": [0.2] * 1024},
                ],
            },
        )

    transport = httpx.MockTransport(handler)

    async def _test() -> None:
        async with httpx.AsyncClient(transport=transport) as client:
            provider = BgeM3EmbeddingProvider(base_url="http://mock", client=client)
            with pytest.raises(WorkerError) as exc_info:
                await provider.embed_documents(["t0", "t1"])
            assert exc_info.value.code == WorkerErrorCode.UPSTREAM_ERROR
            assert "do not form a complete permutation" in exc_info.value.message

    asyncio.run(_test())


def test_bge_m3_error_out_of_range_index() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": -1, "embedding": [0.1] * 1024},
                    {"index": 0, "embedding": [0.2] * 1024},
                ],
            },
        )

    transport = httpx.MockTransport(handler)

    async def _test() -> None:
        async with httpx.AsyncClient(transport=transport) as client:
            provider = BgeM3EmbeddingProvider(base_url="http://mock", client=client)
            with pytest.raises(WorkerError) as exc_info:
                await provider.embed_documents(["t0", "t1"])
            assert exc_info.value.code == WorkerErrorCode.UPSTREAM_ERROR
            assert "do not form a complete permutation" in exc_info.value.message

    asyncio.run(_test())


def test_bge_m3_error_partial_indices() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        # First item has index, second item lacks index
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": 0, "embedding": [0.1] * 1024},
                    {"embedding": [0.2] * 1024},
                ],
            },
        )

    transport = httpx.MockTransport(handler)

    async def _test() -> None:
        async with httpx.AsyncClient(transport=transport) as client:
            provider = BgeM3EmbeddingProvider(base_url="http://mock", client=client)
            with pytest.raises(WorkerError) as exc_info:
                await provider.embed_documents(["t0", "t1"])
            assert exc_info.value.code == WorkerErrorCode.UPSTREAM_ERROR
            assert "carries partial indices" in exc_info.value.message

    asyncio.run(_test())


def test_bge_m3_error_non_integer_index() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": "0", "embedding": [0.1] * 1024},
                    {"index": 1, "embedding": [0.2] * 1024},
                ],
            },
        )

    transport = httpx.MockTransport(handler)

    async def _test() -> None:
        async with httpx.AsyncClient(transport=transport) as client:
            provider = BgeM3EmbeddingProvider(base_url="http://mock", client=client)
            with pytest.raises(WorkerError) as exc_info:
                await provider.embed_documents(["t0", "t1"])
            assert exc_info.value.code == WorkerErrorCode.UPSTREAM_ERROR
            assert "is not an integer" in exc_info.value.message

    asyncio.run(_test())


def test_bge_m3_error_ragged_dimension() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        # First vector 1024-dim, second vector 512-dim
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": 0, "embedding": [0.1] * 1024},
                    {"index": 1, "embedding": [0.2] * 512},
                ],
            },
        )

    transport = httpx.MockTransport(handler)

    async def _test() -> None:
        async with httpx.AsyncClient(transport=transport) as client:
            provider = BgeM3EmbeddingProvider(base_url="http://mock", client=client, dimension=1024)
            with pytest.raises(WorkerError) as exc_info:
                await provider.embed_documents(["t0", "t1"])
            assert exc_info.value.code == WorkerErrorCode.UPSTREAM_ERROR
            assert (
                "Embedding dimension mismatch at index 1: expected 1024, received 512"
                in exc_info.value.message
            )

    asyncio.run(_test())


def test_bge_m3_error_wrong_dimension() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        # Returned 512 dimension when 1024 was declared
        return httpx.Response(
            200,
            json={
                "data": [{"index": 0, "embedding": [0.1] * 512}],
            },
        )

    transport = httpx.MockTransport(handler)

    async def _test() -> None:
        async with httpx.AsyncClient(transport=transport) as client:
            provider = BgeM3EmbeddingProvider(base_url="http://mock", client=client, dimension=1024)
            with pytest.raises(WorkerError) as exc_info:
                await provider.embed_documents(["t1"])
            assert exc_info.value.code == WorkerErrorCode.UPSTREAM_ERROR
            assert (
                "Embedding dimension mismatch at index 0: expected 1024, received 512"
                in exc_info.value.message
            )

    asyncio.run(_test())


def test_bge_m3_error_model_mismatch_top_level() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "text-embedding-ada-002",
                "data": [{"index": 0, "embedding": [0.1] * 1024}],
            },
        )

    transport = httpx.MockTransport(handler)

    async def _test() -> None:
        async with httpx.AsyncClient(transport=transport) as client:
            provider = BgeM3EmbeddingProvider(
                base_url="http://mock", client=client, model_id="bge-m3"
            )
            with pytest.raises(WorkerError) as exc_info:
                await provider.embed_documents(["t1"])
            assert exc_info.value.code == WorkerErrorCode.UPSTREAM_ERROR
            assert (
                "Embedding model mismatch: expected 'bge-m3', received 'text-embedding-ada-002'"
                in exc_info.value.message
            )

    asyncio.run(_test())


def test_bge_m3_error_model_mismatch_item_level() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": [{"index": 0, "model": "other-bge", "embedding": [0.1] * 1024}],
            },
        )

    transport = httpx.MockTransport(handler)

    async def _test() -> None:
        async with httpx.AsyncClient(transport=transport) as client:
            provider = BgeM3EmbeddingProvider(
                base_url="http://mock", client=client, model_id="bge-m3"
            )
            with pytest.raises(WorkerError) as exc_info:
                await provider.embed_documents(["t1"])
            assert exc_info.value.code == WorkerErrorCode.UPSTREAM_ERROR
            assert (
                "Embedding model mismatch at item 0: expected 'bge-m3', received 'other-bge'"
                in exc_info.value.message
            )

    asyncio.run(_test())


def test_bge_m3_error_embedding_version_mismatch_top_level() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "embedding_version": "bge-m3-v2",
                "data": [{"index": 0, "embedding": [0.1] * 1024}],
            },
        )

    transport = httpx.MockTransport(handler)

    async def _test() -> None:
        async with httpx.AsyncClient(transport=transport) as client:
            provider = BgeM3EmbeddingProvider(
                base_url="http://mock", client=client, embedding_version="bge-m3-v1"
            )
            with pytest.raises(WorkerError) as exc_info:
                await provider.embed_documents(["t1"])
            assert exc_info.value.code == WorkerErrorCode.UPSTREAM_ERROR
            assert (
                "Embedding version mismatch: expected 'bge-m3-v1', received 'bge-m3-v2'"
                in exc_info.value.message
            )

    asyncio.run(_test())


def test_bge_m3_error_embedding_version_mismatch_item_level() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": [{"index": 0, "embedding_version": "bge-m3-v2", "embedding": [0.1] * 1024}],
            },
        )

    transport = httpx.MockTransport(handler)

    async def _test() -> None:
        async with httpx.AsyncClient(transport=transport) as client:
            provider = BgeM3EmbeddingProvider(
                base_url="http://mock", client=client, embedding_version="bge-m3-v1"
            )
            with pytest.raises(WorkerError) as exc_info:
                await provider.embed_documents(["t1"])
            assert exc_info.value.code == WorkerErrorCode.UPSTREAM_ERROR
            assert (
                "Embedding version mismatch at item 0: expected 'bge-m3-v1', received 'bge-m3-v2'"
                in exc_info.value.message
            )

    asyncio.run(_test())


def test_bge_m3_error_missing_embedding_field() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"data": [{"index": 0}]},
        )

    transport = httpx.MockTransport(handler)

    async def _test() -> None:
        async with httpx.AsyncClient(transport=transport) as client:
            provider = BgeM3EmbeddingProvider(base_url="http://mock", client=client)
            with pytest.raises(WorkerError) as exc_info:
                await provider.embed_documents(["t1"])
            assert exc_info.value.code == WorkerErrorCode.UPSTREAM_ERROR
            assert "Missing 'embedding' field" in exc_info.value.message

    asyncio.run(_test())


def test_bge_m3_error_non_numeric_vector_element() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        invalid_vec: list[Any] = [0.1] * 1024
        invalid_vec[5] = "not-a-number"
        return httpx.Response(
            200,
            json={"data": [{"index": 0, "embedding": invalid_vec}]},
        )

    transport = httpx.MockTransport(handler)

    async def _test() -> None:
        async with httpx.AsyncClient(transport=transport) as client:
            provider = BgeM3EmbeddingProvider(base_url="http://mock", client=client)
            with pytest.raises(WorkerError) as exc_info:
                await provider.embed_documents(["t1"])
            assert exc_info.value.code == WorkerErrorCode.UPSTREAM_ERROR
            assert "contains non-numeric values" in exc_info.value.message

    asyncio.run(_test())


# -----------------------------------------------------------------------------
# 5. Network & HTTP Status Error Tests
# -----------------------------------------------------------------------------


def test_bge_m3_unauthorized_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "Invalid API token"})

    transport = httpx.MockTransport(handler)

    async def _test() -> None:
        async with httpx.AsyncClient(transport=transport) as client:
            provider = BgeM3EmbeddingProvider(base_url="http://mock", client=client)
            with pytest.raises(WorkerError) as exc_info:
                await provider.embed_documents(["test"])
            assert exc_info.value.code == WorkerErrorCode.UNAUTHORIZED
            assert not exc_info.value.retryable
            assert exc_info.value.status_code == 401

    asyncio.run(_test())


def test_bge_m3_bad_request_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "Invalid parameters"})

    transport = httpx.MockTransport(handler)

    async def _test() -> None:
        async with httpx.AsyncClient(transport=transport) as client:
            provider = BgeM3EmbeddingProvider(base_url="http://mock", client=client)
            with pytest.raises(WorkerError) as exc_info:
                await provider.embed_documents(["test"])
            assert exc_info.value.code == WorkerErrorCode.BAD_REQUEST
            assert not exc_info.value.retryable
            assert exc_info.value.status_code == 400

    asyncio.run(_test())


def test_bge_m3_model_not_found_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "Model bge-m3 not found"})

    transport = httpx.MockTransport(handler)

    async def _test() -> None:
        async with httpx.AsyncClient(transport=transport) as client:
            provider = BgeM3EmbeddingProvider(base_url="http://mock", client=client)
            with pytest.raises(WorkerError) as exc_info:
                await provider.embed_documents(["test"])
            assert exc_info.value.code == WorkerErrorCode.MODEL_NOT_LOADED
            assert not exc_info.value.retryable
            assert exc_info.value.status_code == 404

    asyncio.run(_test())


def test_bge_m3_service_unavailable_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "Service overloaded"})

    transport = httpx.MockTransport(handler)

    async def _test() -> None:
        async with httpx.AsyncClient(transport=transport) as client:
            provider = BgeM3EmbeddingProvider(base_url="http://mock", client=client)
            with pytest.raises(WorkerError) as exc_info:
                await provider.embed_documents(["test"])
            assert exc_info.value.code == WorkerErrorCode.UNAVAILABLE
            assert exc_info.value.retryable
            assert exc_info.value.status_code == 503

    asyncio.run(_test())


def test_bge_m3_upstream_server_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="Internal server crash")

    transport = httpx.MockTransport(handler)

    async def _test() -> None:
        async with httpx.AsyncClient(transport=transport) as client:
            provider = BgeM3EmbeddingProvider(base_url="http://mock", client=client)
            with pytest.raises(WorkerError) as exc_info:
                await provider.embed_documents(["test"])
            assert exc_info.value.code == WorkerErrorCode.UPSTREAM_ERROR
            assert exc_info.value.retryable
            assert exc_info.value.status_code == 500

    asyncio.run(_test())


def test_bge_m3_timeout_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("Request timed out")

    transport = httpx.MockTransport(handler)

    async def _test() -> None:
        async with httpx.AsyncClient(transport=transport, base_url="http://mock") as client:
            provider = BgeM3EmbeddingProvider(base_url="http://mock", client=client, timeout=5.0)
            with pytest.raises(WorkerError) as exc_info:
                await provider.embed_documents(["test"])
            assert exc_info.value.code == WorkerErrorCode.TIMEOUT
            assert exc_info.value.retryable
            assert exc_info.value.status_code == 504

    asyncio.run(_test())


def test_bge_m3_connection_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused")

    transport = httpx.MockTransport(handler)

    async def _test() -> None:
        async with httpx.AsyncClient(transport=transport, base_url="http://mock") as client:
            provider = BgeM3EmbeddingProvider(base_url="http://mock", client=client)
            with pytest.raises(WorkerError) as exc_info:
                await provider.embed_documents(["test"])
            assert exc_info.value.code == WorkerErrorCode.UNAVAILABLE
            assert exc_info.value.retryable
            assert exc_info.value.status_code == 503

    asyncio.run(_test())


def test_bge_m3_invalid_json_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>Not JSON</html>")

    transport = httpx.MockTransport(handler)

    async def _test() -> None:
        async with httpx.AsyncClient(transport=transport) as client:
            provider = BgeM3EmbeddingProvider(base_url="http://mock", client=client)
            with pytest.raises(WorkerError) as exc_info:
                await provider.embed_documents(["test"])
            assert exc_info.value.code == WorkerErrorCode.UPSTREAM_ERROR
            assert exc_info.value.retryable

    asyncio.run(_test())


def test_bge_m3_invalid_response_structure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": "not a list"})

    transport = httpx.MockTransport(handler)

    async def _test() -> None:
        async with httpx.AsyncClient(transport=transport) as client:
            provider = BgeM3EmbeddingProvider(base_url="http://mock", client=client)
            with pytest.raises(WorkerError) as exc_info:
                await provider.embed_documents(["test"])
            assert exc_info.value.code == WorkerErrorCode.UPSTREAM_ERROR

    asyncio.run(_test())


def test_bge_m3_context_manager_and_close() -> None:
    async def _test() -> None:
        async with BgeM3EmbeddingProvider(base_url="http://localhost:8090") as provider:
            assert provider.model_id == "bge-m3"
        assert provider._client is None or provider._client.is_closed

    asyncio.run(_test())
