"""Unit tests for DenseRetriever (Phase 4 / Task C2)."""

from __future__ import annotations

import asyncio
import math
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import Document
from mamagift_contracts.embedding import EmbeddingResult
from mamagift_retrieval.chunk import Chunk, ChunkType
from mamagift_retrieval.index import IndexEntry, SqlDocumentIndex
from mamagift_retrieval.providers import FakeEmbeddingProvider
from mamagift_retrieval.scope import EvidenceScope
from mamagift_retrieval.search import DenseRetriever, EmbeddingVersionMismatchError, ScoredChunk


@pytest.fixture
def db_engine():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def session_factory(db_engine):
    return sessionmaker(bind=db_engine, expire_on_commit=False, future=True)


@pytest.fixture
def index(session_factory) -> SqlDocumentIndex:
    return SqlDocumentIndex(session_factory)


@pytest.fixture
def embedding_provider() -> FakeEmbeddingProvider:
    return FakeEmbeddingProvider(
        model_id="fake-bge-m3",
        dimension=1024,
        embedding_version="fake-bge-m3-v1",
    )


@pytest.fixture
def retriever(index: SqlDocumentIndex, embedding_provider: FakeEmbeddingProvider) -> DenseRetriever:
    return DenseRetriever(index=index, embedding_provider=embedding_provider)


def _seed_document(session_factory, doc_id: str) -> None:
    with session_factory() as session:
        with session.begin():
            existing = session.get(Document, doc_id)
            if not existing:
                doc = Document(
                    id=doc_id,
                    filename=f"{doc_id}.pdf",
                    content_type="application/pdf",
                    byte_size=2048,
                    checksum_sha256=f"hash_{doc_id}",
                    storage_uri=f"local://{doc_id}",
                )
                session.add(doc)


def _make_chunk(
    chunk_id: str,
    doc_id: str,
    parse_run_id: str,
    doc_version: int = 1,
    text: str = "Nội dung văn bản",
) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        parent_chunk_id=None,
        document_id=doc_id,
        parse_run_id=parse_run_id,
        document_version=doc_version,
        section_path=["Điều 1. Phạm vi"],
        chunk_type=ChunkType.LEGAL_ARTICLE,
        text=text,
        source_block_ids=[f"block_{chunk_id}"],
        source_page_numbers=[1],
        metadata={},
    )


def test_unambiguous_nearest_chunk_returned_first(
    session_factory,
    index: SqlDocumentIndex,
    embedding_provider: FakeEmbeddingProvider,
    retriever: DenseRetriever,
) -> None:
    async def _test() -> None:
        doc_id = "doc_nearest_01"
        run_id = "run_nearest_01"
        _seed_document(session_factory, doc_id)

        scope = EvidenceScope(
            family_id="fam_01",
            document_id=doc_id,
            document_version=1,
            parse_run_id=run_id,
        )

        t1 = "Kế hoạch phân bổ ngân sách nhà nước cho chuyển đổi số năm 2026"
        t2 = "Quy định về xử lý kỷ luật cán bộ công chức vi phạm trật tự an toàn giao thông"
        t3 = "Hướng dẫn quy trình cấp giấy phép xây dựng nhà ở riêng lẻ tại đô thị"

        c1 = _make_chunk("chunk_budget", doc_id, run_id, 1, text=t1)
        c2 = _make_chunk("chunk_discipline", doc_id, run_id, 1, text=t2)
        c3 = _make_chunk("chunk_construction", doc_id, run_id, 1, text=t3)

        emb_res = await embedding_provider.embed_documents([t1, t2, t3])

        index.replace(
            scope,
            [
                IndexEntry(
                    chunk=c1,
                    chunk_index=0,
                    embedding=emb_res.vectors[0],
                    embedding_model=embedding_provider.model_id,
                    embedding_version=embedding_provider.embedding_version,
                ),
                IndexEntry(
                    chunk=c2,
                    chunk_index=1,
                    embedding=emb_res.vectors[1],
                    embedding_model=embedding_provider.model_id,
                    embedding_version=embedding_provider.embedding_version,
                ),
                IndexEntry(
                    chunk=c3,
                    chunk_index=2,
                    embedding=emb_res.vectors[2],
                    embedding_model=embedding_provider.model_id,
                    embedding_version=embedding_provider.embedding_version,
                ),
            ],
        )

        query = "Kế hoạch ngân sách chuyển đổi số 2026"
        results = await retriever.search(query=query, scope=scope, top_k=3)

        assert len(results) == 3
        assert results[0].chunk.chunk_id == "chunk_budget"
        assert results[0].rank == 1
        assert results[0].retriever == "dense"
        assert isinstance(results[0], ScoredChunk)
        assert results[0].score > results[1].score
        assert results[0].score > results[2].score

    asyncio.run(_test())


def test_exact_cosine_ordering(
    session_factory,
    index: SqlDocumentIndex,
) -> None:
    async def _test() -> None:
        doc_id = "doc_cosine_exact"
        run_id = "run_cosine_exact"
        _seed_document(session_factory, doc_id)

        scope = EvidenceScope(
            family_id="fam_01",
            document_id=doc_id,
            document_version=1,
            parse_run_id=run_id,
        )

        ca = _make_chunk("ca", doc_id, run_id, 1, text="Chunk A")
        cb = _make_chunk("cb", doc_id, run_id, 1, text="Chunk B")
        cc = _make_chunk("cc", doc_id, run_id, 1, text="Chunk C")
        cd = _make_chunk("cd", doc_id, run_id, 1, text="Chunk D")

        index.replace(
            scope,
            [
                IndexEntry(
                    chunk=ca,
                    chunk_index=0,
                    embedding=[1.0, 0.0, 0.0],
                    embedding_version="fake-bge-m3-v1",
                ),
                IndexEntry(
                    chunk=cb,
                    chunk_index=1,
                    embedding=[1.0, 1.0, 0.0],
                    embedding_version="fake-bge-m3-v1",
                ),
                IndexEntry(
                    chunk=cc,
                    chunk_index=2,
                    embedding=[0.0, 1.0, 0.0],
                    embedding_version="fake-bge-m3-v1",
                ),
                IndexEntry(
                    chunk=cd,
                    chunk_index=3,
                    embedding=[-1.0, 0.0, 0.0],
                    embedding_version="fake-bge-m3-v1",
                ),
            ],
        )

        mock_provider = MagicMock()
        mock_provider.embedding_version = "fake-bge-m3-v1"
        mock_provider.embed_query = AsyncMock(
            return_value=EmbeddingResult(
                vectors=[[1.0, 0.0, 0.0]],
                model="fake-bge-m3",
                dimension=3,
                embedding_version="fake-bge-m3-v1",
            )
        )

        custom_retriever = DenseRetriever(index=index, embedding_provider=mock_provider)
        results = await custom_retriever.search(query="test query", scope=scope, top_k=4)

        assert len(results) == 4
        assert [r.chunk.chunk_id for r in results] == ["ca", "cb", "cc", "cd"]
        assert [r.rank for r in results] == [1, 2, 3, 4]
        assert all(r.retriever == "dense" for r in results)
        assert math.isclose(results[0].score, 1.0, rel_tol=1e-5)
        assert math.isclose(results[1].score, 1.0 / math.sqrt(2.0), rel_tol=1e-5)
        assert math.isclose(results[2].score, 0.0, abs_tol=1e-5)
        assert math.isclose(results[3].score, -1.0, rel_tol=1e-5)

    asyncio.run(_test())


def test_deterministic_ordering_and_stable_tie_break(
    session_factory,
    index: SqlDocumentIndex,
) -> None:
    async def _test() -> None:
        doc_id = "doc_tie_01"
        run_id = "run_tie_01"
        _seed_document(session_factory, doc_id)

        scope = EvidenceScope(
            family_id="fam_01",
            document_id=doc_id,
            document_version=1,
            parse_run_id=run_id,
        )

        c_gamma = _make_chunk("chunk_gamma", doc_id, run_id, 1, text="Chunk Gamma")
        c_alpha = _make_chunk("chunk_alpha", doc_id, run_id, 1, text="Chunk Alpha")
        c_beta = _make_chunk("chunk_beta", doc_id, run_id, 1, text="Chunk Beta")

        index.replace(
            scope,
            [
                IndexEntry(
                    chunk=c_gamma,
                    chunk_index=0,
                    embedding=[1.0, 0.0],
                    embedding_version="fake-bge-m3-v1",
                ),
                IndexEntry(
                    chunk=c_alpha,
                    chunk_index=1,
                    embedding=[1.0, 0.0],
                    embedding_version="fake-bge-m3-v1",
                ),
                IndexEntry(
                    chunk=c_beta,
                    chunk_index=2,
                    embedding=[1.0, 0.0],
                    embedding_version="fake-bge-m3-v1",
                ),
            ],
        )

        mock_provider = MagicMock()
        mock_provider.embedding_version = "fake-bge-m3-v1"
        mock_provider.embed_query = AsyncMock(
            return_value=EmbeddingResult(
                vectors=[[1.0, 0.0]],
                model="fake-bge-m3",
                dimension=2,
                embedding_version="fake-bge-m3-v1",
            )
        )

        custom_retriever = DenseRetriever(index=index, embedding_provider=mock_provider)

        # 10 repeated runs must yield identical ordering and ranks
        for _ in range(10):
            results = await custom_retriever.search(query="query", scope=scope, top_k=3)
            assert len(results) == 3
            assert [r.chunk.chunk_id for r in results] == [
                "chunk_alpha",
                "chunk_beta",
                "chunk_gamma",
            ]
            assert [r.rank for r in results] == [1, 2, 3]
            assert results[0].score == results[1].score == results[2].score

    asyncio.run(_test())


def test_empty_index_and_empty_query(
    session_factory,
    index: SqlDocumentIndex,
    retriever: DenseRetriever,
) -> None:
    async def _test() -> None:
        doc_id = "doc_empty_01"
        _seed_document(session_factory, doc_id)

        scope = EvidenceScope(
            family_id="fam_01",
            document_id=doc_id,
            document_version=1,
            parse_run_id="run_empty",
        )

        # 1. Empty index (no chunks indexed) - returns [] without calling embed_query
        mock_prov1 = MagicMock()
        mock_prov1.embedding_version = "fake-bge-m3-v1"
        mock_prov1.embed_query = AsyncMock()
        retriever_empty = DenseRetriever(index=index, embedding_provider=mock_prov1)
        assert await retriever_empty.search(query="thông tư", scope=scope, top_k=5) == []
        mock_prov1.embed_query.assert_not_called()

        # 2. Empty query string - returns [] without calling embed_query
        c = _make_chunk("c1", doc_id, "run_empty", 1, text="Nội dung điều 1")
        index.replace(
            scope,
            [
                IndexEntry(
                    chunk=c,
                    chunk_index=0,
                    embedding=[1.0, 0.0],
                    embedding_version="fake-bge-m3-v1",
                )
            ],
        )

        mock_prov2 = MagicMock()
        mock_prov2.embedding_version = "fake-bge-m3-v1"
        mock_prov2.embed_query = AsyncMock()
        retriever_with_data = DenseRetriever(index=index, embedding_provider=mock_prov2)

        assert await retriever_with_data.search(query="", scope=scope, top_k=5) == []
        assert await retriever_with_data.search(query="   \t\n", scope=scope, top_k=5) == []
        mock_prov2.embed_query.assert_not_called()

        # 3. Index with 0 embedded chunks (embedded_chunks == 0)
        # returns [] without calling embed_query
        scope_no_emb = EvidenceScope(
            family_id="fam_01",
            document_id=doc_id,
            document_version=2,
            parse_run_id="run_no_emb",
        )
        c_unemb = _make_chunk("c_unemb", doc_id, "run_no_emb", 2, text="Chưa embed")
        index.replace(
            scope_no_emb,
            [
                IndexEntry(
                    chunk=c_unemb,
                    chunk_index=0,
                    embedding=None,
                    embedding_version=None,
                )
            ],
        )
        mock_prov3 = MagicMock()
        mock_prov3.embedding_version = "fake-bge-m3-v1"
        mock_prov3.embed_query = AsyncMock()
        retriever_no_emb = DenseRetriever(index=index, embedding_provider=mock_prov3)

        assert await retriever_no_emb.search(query="nội dung", scope=scope_no_emb, top_k=5) == []
        mock_prov3.embed_query.assert_not_called()

    asyncio.run(_test())


def test_embedding_version_mismatch_surfaced(
    session_factory,
    index: SqlDocumentIndex,
    retriever: DenseRetriever,
) -> None:
    async def _test() -> None:
        doc_id = "doc_mismatch_01"
        run_id = "run_mismatch_01"
        _seed_document(session_factory, doc_id)

        scope = EvidenceScope(
            family_id="fam_01",
            document_id=doc_id,
            document_version=1,
            parse_run_id=run_id,
        )

        c = _make_chunk("c1", doc_id, run_id, 1, text="Văn bản cũ")
        index.replace(
            scope,
            [
                IndexEntry(
                    chunk=c,
                    chunk_index=0,
                    embedding=[1.0, 0.0],
                    embedding_model="bge-m3",
                    embedding_version="bge-m3-v1-old",
                )
            ],
        )

        # Retriever uses "fake-bge-m3-v1" while indexed chunk has "bge-m3-v1-old"
        with pytest.raises(EmbeddingVersionMismatchError) as exc_info:
            await retriever.search(query="văn bản", scope=scope, top_k=5)

        err = exc_info.value
        assert err.provider_version == "fake-bge-m3-v1"
        assert err.index_version == "bge-m3-v1-old"
        assert "Embedding version mismatch" in str(err)

    asyncio.run(_test())


def test_embedding_result_version_mismatch_surfaced(
    session_factory,
    index: SqlDocumentIndex,
) -> None:
    async def _test() -> None:
        doc_id = "doc_res_mismatch"
        run_id = "run_res_mismatch"
        _seed_document(session_factory, doc_id)

        scope = EvidenceScope(
            family_id="fam_01",
            document_id=doc_id,
            document_version=1,
            parse_run_id=run_id,
        )

        c = _make_chunk("c1", doc_id, run_id, 1, text="Văn bản")
        index.replace(
            scope,
            [
                IndexEntry(
                    chunk=c,
                    chunk_index=0,
                    embedding=[1.0, 0.0],
                    embedding_version="v1",
                )
            ],
        )

        mock_provider = MagicMock()
        mock_provider.embedding_version = "v1"
        # Provider returns result with mismatched version
        mock_provider.embed_query = AsyncMock(
            return_value=EmbeddingResult(
                vectors=[[1.0, 0.0]],
                model="fake-bge-m3",
                dimension=2,
                embedding_version="v2-unexpected",
            )
        )

        retriever = DenseRetriever(index=index, embedding_provider=mock_provider)
        with pytest.raises(EmbeddingVersionMismatchError) as exc_info:
            await retriever.search(query="văn bản", scope=scope, top_k=5)

        assert exc_info.value.provider_version == "v1"
        assert exc_info.value.index_version == "v2-unexpected"

    asyncio.run(_test())


def test_scope_isolation_document_and_version_and_parserun(
    session_factory,
    index: SqlDocumentIndex,
    retriever: DenseRetriever,
) -> None:
    async def _test() -> None:
        doc_a = "doc_iso_a"
        doc_b = "doc_iso_b"
        _seed_document(session_factory, doc_a)
        _seed_document(session_factory, doc_b)

        scope_a_r1 = EvidenceScope(
            family_id="fam_01",
            document_id=doc_a,
            document_version=1,
            parse_run_id="run_a1",
        )
        scope_a_r2 = EvidenceScope(
            family_id="fam_01",
            document_id=doc_a,
            document_version=2,
            parse_run_id="run_a2",
        )
        scope_b_r1 = EvidenceScope(
            family_id="fam_01",
            document_id=doc_b,
            document_version=1,
            parse_run_id="run_b1",
        )

        ca_r1 = _make_chunk("ca_r1", doc_a, "run_a1", 1, text="Phiên bản 1 của văn bản A")
        ca_r2 = _make_chunk("ca_r2", doc_a, "run_a2", 2, text="Phiên bản 2 của văn bản A")
        cb_r1 = _make_chunk("cb_r1", doc_b, "run_b1", 1, text="Văn bản B hoàn toàn khác")

        emb_provider = retriever.embedding_provider
        emb_res = await emb_provider.embed_documents([ca_r1.text, ca_r2.text, cb_r1.text])

        index.replace(
            scope_a_r1,
            [
                IndexEntry(
                    chunk=ca_r1,
                    chunk_index=0,
                    embedding=emb_res.vectors[0],
                    embedding_version=emb_provider.embedding_version,
                )
            ],
        )
        index.replace(
            scope_a_r2,
            [
                IndexEntry(
                    chunk=ca_r2,
                    chunk_index=0,
                    embedding=emb_res.vectors[1],
                    embedding_version=emb_provider.embedding_version,
                )
            ],
        )
        index.replace(
            scope_b_r1,
            [
                IndexEntry(
                    chunk=cb_r1,
                    chunk_index=0,
                    embedding=emb_res.vectors[2],
                    embedding_version=emb_provider.embedding_version,
                )
            ],
        )

        # Search scoped to Doc A, Run 2: must ONLY return ca_r2
        results_a2 = await retriever.search(query="văn bản", scope=scope_a_r2, top_k=10)
        assert len(results_a2) == 1
        assert results_a2[0].chunk.chunk_id == "ca_r2"
        assert results_a2[0].chunk.document_id == doc_a
        assert results_a2[0].chunk.document_version == 2
        assert results_a2[0].chunk.parse_run_id == "run_a2"

        # Search scoped to Doc B: must ONLY return cb_r1
        results_b = await retriever.search(query="văn bản", scope=scope_b_r1, top_k=10)
        assert len(results_b) == 1
        assert results_b[0].chunk.chunk_id == "cb_r1"
        assert results_b[0].chunk.document_id == doc_b

    asyncio.run(_test())


def test_embed_query_is_called_not_embed_documents(
    session_factory,
    index: SqlDocumentIndex,
) -> None:
    async def _test() -> None:
        doc_id = "doc_embed_call"
        _seed_document(session_factory, doc_id)

        scope = EvidenceScope(
            family_id="fam_01",
            document_id=doc_id,
            document_version=1,
            parse_run_id="run_call",
        )

        c = _make_chunk("c1", doc_id, "run_call", 1, text="Test text")
        index.replace(
            scope,
            [
                IndexEntry(
                    chunk=c,
                    chunk_index=0,
                    embedding=[1.0, 0.0],
                    embedding_version="fake-bge-m3-v1",
                )
            ],
        )

        mock_provider = MagicMock()
        mock_provider.embedding_version = "fake-bge-m3-v1"
        mock_provider.embed_query = AsyncMock(
            return_value=EmbeddingResult(
                vectors=[[1.0, 0.0]],
                model="fake-bge-m3",
                dimension=2,
                embedding_version="fake-bge-m3-v1",
            )
        )
        mock_provider.embed_documents = AsyncMock()

        retriever = DenseRetriever(index=index, embedding_provider=mock_provider)
        results = await retriever.search(query="query text", scope=scope, top_k=5)

        assert len(results) == 1
        mock_provider.embed_query.assert_awaited_once_with("query text")
        mock_provider.embed_documents.assert_not_called()

    asyncio.run(_test())


def test_input_validations_raise(
    session_factory,
    index: SqlDocumentIndex,
    retriever: DenseRetriever,
) -> None:
    async def _test() -> None:
        scope_valid = EvidenceScope(
            family_id="fam_01",
            document_id="doc_val",
            document_version=1,
            parse_run_id="run_val",
        )
        scope_missing_doc = EvidenceScope(
            family_id="fam_01",
            document_version=1,
            parse_run_id="run_val",
        )

        # top_k <= 0 raises ValueError
        with pytest.raises(ValueError, match="top_k must be a positive integer"):
            await retriever.search(query="test", scope=scope_valid, top_k=0)

        with pytest.raises(ValueError, match="top_k must be a positive integer"):
            await retriever.search(query="test", scope=scope_valid, top_k=-1)

        # scope missing document_id raises ValueError without calling index
        mock_index = MagicMock()
        mock_retriever = DenseRetriever(
            index=mock_index, embedding_provider=retriever.embedding_provider
        )
        with pytest.raises(ValueError, match="scope must specify document_id"):
            await mock_retriever.search(query="test", scope=scope_missing_doc, top_k=5)
        mock_index.stats.assert_not_called()

    asyncio.run(_test())


def test_provenance_contradiction_defense() -> None:
    async def _test() -> None:
        scope = EvidenceScope(
            family_id="fam_01",
            document_id="doc_orig",
            document_version=1,
            parse_run_id="run_orig",
        )

        bad_chunk = _make_chunk("c_leaked", "doc_other", "run_other", 1, text="Leaked")

        mock_index = MagicMock()
        mock_index.stats.return_value = MagicMock(
            total_chunks=1,
            embedded_chunks=1,
            embedding_version="v1",
        )
        # Index incorrectly returns chunk from another document
        mock_index.search_dense.return_value = [
            ScoredChunk(chunk=bad_chunk, score=0.95, rank=1, retriever="dense")
        ]

        mock_provider = MagicMock()
        mock_provider.embedding_version = "v1"
        mock_provider.embed_query = AsyncMock(
            return_value=EmbeddingResult(
                vectors=[[1.0, 0.0]],
                model="fake-bge-m3",
                dimension=2,
                embedding_version="v1",
            )
        )

        retriever = DenseRetriever(index=mock_index, embedding_provider=mock_provider)

        with pytest.raises(ValueError, match="violates requested EvidenceScope"):
            await retriever.search(query="test", scope=scope, top_k=5)

    asyncio.run(_test())


def test_empty_embedding_vector_returns_empty(
    session_factory,
    index: SqlDocumentIndex,
) -> None:
    async def _test() -> None:
        doc_id = "doc_empty_vec"
        _seed_document(session_factory, doc_id)

        scope = EvidenceScope(
            family_id="fam_01",
            document_id=doc_id,
            document_version=1,
            parse_run_id="run_vec",
        )

        c = _make_chunk("c1", doc_id, "run_vec", 1, text="Chunk")
        index.replace(
            scope,
            [
                IndexEntry(
                    chunk=c,
                    chunk_index=0,
                    embedding=[1.0, 0.0],
                    embedding_version="v1",
                )
            ],
        )

        mock_provider = MagicMock()
        mock_provider.embedding_version = "v1"
        mock_provider.embed_query = AsyncMock(
            return_value=EmbeddingResult(
                vectors=[],
                model="fake-bge-m3",
                dimension=2,
                embedding_version="v1",
            )
        )

        retriever = DenseRetriever(index=index, embedding_provider=mock_provider)
        assert await retriever.search(query="query", scope=scope, top_k=5) == []

    asyncio.run(_test())


def test_properties_exposure(
    index: SqlDocumentIndex, embedding_provider: FakeEmbeddingProvider
) -> None:
    retriever = DenseRetriever(index=index, embedding_provider=embedding_provider)
    assert retriever.index is index
    assert retriever.embedding_provider is embedding_provider
