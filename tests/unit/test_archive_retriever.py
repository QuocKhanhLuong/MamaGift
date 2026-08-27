"""Unit tests for ArchiveRetriever (Phase 5 / Task C1)."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db import Base
from app.models import Document, DocumentChunk, ParseRun
from mamagift_contracts.embedding import EmbeddingResult
from mamagift_retrieval.archive import (
    ArchiveDocumentRef,
    ArchiveFilter,
)
from mamagift_retrieval.archive.protocol import AUTHORITATIVE_FAMILY_ID
from mamagift_retrieval.archive.retriever import (
    ArchiveEmbeddingVersionMismatchError,
    ArchiveRetrievalResult,
    ArchiveRetriever,
)
from mamagift_retrieval.archive.sql_archive_index import SqlArchiveIndex
from mamagift_retrieval.providers import FakeEmbeddingProvider
from mamagift_retrieval.rerank.protocol import (
    validate_archive_rerank_candidates,
)
from mamagift_retrieval.scope import EvidenceScope
from mamagift_retrieval.search.types import ScoredChunk

NOW = datetime(2026, 8, 27, 12, 0, 0, tzinfo=UTC)


class CountingEmbeddingProvider:
    """EmbeddingProvider wrapper that tracks embed_query and embed_documents calls."""

    def __init__(self, inner: FakeEmbeddingProvider) -> None:
        self._inner = inner
        self.embed_query_count = 0
        self.embed_documents_count = 0

    @property
    def model_id(self) -> str:
        return self._inner.model_id

    @property
    def dimension(self) -> int:
        return self._inner.dimension

    @property
    def embedding_version(self) -> str:
        return self._inner.embedding_version

    async def embed_documents(self, texts: list[str]) -> EmbeddingResult:
        self.embed_documents_count += 1
        return await self._inner.embed_documents(texts)

    async def embed_query(self, text: str) -> EmbeddingResult:
        self.embed_query_count += 1
        return await self._inner.embed_query(text)


class FakeArchiveReranker:
    """Deterministic fake reranker that supports archive multi-document candidates."""

    def __init__(
        self,
        ordering: Sequence[str] | None = None,
        *,
        reranker_version: str = "fake-archive-reranker-v1",
    ) -> None:
        self._ordering = list(ordering) if ordering is not None else None
        self._reranker_version = reranker_version
        self.call_count = 0

    @property
    def reranker_version(self) -> str:
        return self._reranker_version

    async def rerank(
        self,
        query: str,
        candidates: list[ScoredChunk],
        top_k: int,
    ) -> list[ScoredChunk]:
        self.call_count += 1
        validate_archive_rerank_candidates(candidates)
        if not candidates or top_k <= 0:
            return []

        if self._ordering is not None:
            by_id = {c.chunk.chunk_id: c for c in candidates}
            ordered: list[ScoredChunk] = []
            seen: set[str] = set()
            for cid in self._ordering:
                if cid in by_id and cid not in seen:
                    ordered.append(by_id[cid])
                    seen.add(cid)
            for c in candidates:
                if c.chunk.chunk_id not in seen:
                    ordered.append(c)
                    seen.add(c.chunk.chunk_id)
        else:
            ordered = list(candidates)

        total = len(ordered)
        reranked = [
            ScoredChunk(
                chunk=cand.chunk,
                score=float(total - pos + 1),
                rank=pos,
                retriever="reranked",
            )
            for pos, cand in enumerate(ordered, start=1)
        ]
        return reranked[:top_k]


@pytest.fixture
def db_engine():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def session_factory(db_engine):
    return sessionmaker(bind=db_engine, expire_on_commit=False, future=True)


@pytest.fixture
def index(session_factory) -> SqlArchiveIndex:
    return SqlArchiveIndex(session_factory, embedding_version="fake-bge-m3-v1")


@pytest.fixture
def base_embedding_provider() -> FakeEmbeddingProvider:
    return FakeEmbeddingProvider(
        model_id="fake-bge-m3",
        dimension=1024,
        embedding_version="fake-bge-m3-v1",
    )


@pytest.fixture
def counting_embedding_provider(base_embedding_provider) -> CountingEmbeddingProvider:
    return CountingEmbeddingProvider(base_embedding_provider)


@pytest.fixture
def reranker() -> FakeArchiveReranker:
    return FakeArchiveReranker()


@pytest.fixture
def valid_scope() -> EvidenceScope:
    return EvidenceScope(
        family_id=AUTHORITATIVE_FAMILY_ID,
        archive_scope=True,
    )


def _seed_document(
    session_factory: sessionmaker[Session],
    doc_id: str,
    *,
    current_parse_run_id: str | None = None,
    document_type: str | None = None,
    document_number: str | None = None,
    title: str | None = None,
    issuer: str | None = None,
    issued_date: date | None = None,
    requires_user_review: bool = False,
) -> Document:
    with session_factory() as session:
        with session.begin():
            doc = Document(
                id=doc_id,
                filename=f"{doc_id}.pdf",
                content_type="application/pdf",
                byte_size=2048,
                checksum_sha256=f"sha256_{doc_id}",
                storage_uri=f"local://storage/{doc_id}",
                document_type=document_type,
                document_number=document_number,
                title=title,
                issuer=issuer,
                issued_date=issued_date,
                current_parse_run_id=current_parse_run_id,
                requires_user_review=requires_user_review,
                created_at=NOW,
                updated_at=NOW,
            )
            session.add(doc)
    return doc


def _seed_parse_run(
    session_factory: sessionmaker[Session],
    run_id: str,
    doc_id: str,
    *,
    version: int = 1,
    is_current: bool = True,
) -> ParseRun:
    with session_factory() as session:
        with session.begin():
            prun = ParseRun(
                id=run_id,
                document_id=doc_id,
                version=version,
                is_current=is_current,
                parser_name="pymupdf",
                parser_version="1.0",
                configuration_hash="hash_01",
                strategy_decided=True,
                degraded=False,
                route="born_digital",
                schema_version="1.0",
                canonical={},
                inspection={},
                quality_report={},
                started_at=NOW,
                finished_at=NOW,
                created_at=NOW,
            )
            session.add(prun)
    return prun


def _seed_chunk(
    session_factory: sessionmaker[Session],
    chunk_id: str,
    doc_id: str,
    parse_run_id: str,
    *,
    doc_version: int = 1,
    chunk_index: int = 0,
    text: str = "Test chunk text",
    embedding: list[float] | None = None,
    embedding_model: str | None = "fake-bge-m3",
    embedding_version: str | None = "fake-bge-m3-v1",
    section_path: list[str] | None = None,
    page_numbers: list[int] | None = None,
    source_block_ids: list[str] | None = None,
) -> DocumentChunk:
    with session_factory() as session:
        with session.begin():
            chunk = DocumentChunk(
                id=chunk_id,
                document_id=doc_id,
                parse_run_id=parse_run_id,
                document_version=doc_version,
                chunk_index=chunk_index,
                section_path=section_path or ["Điều 1. Phạm vi điều chỉnh"],
                page_numbers=page_numbers or [1],
                source_block_ids=source_block_ids or [f"blk_{chunk_id}"],
                text=text,
                token_count=len(text.split()),
                embedding=embedding,
                embedding_model=embedding_model,
                embedding_version=embedding_version,
                created_at=NOW,
            )
            session.add(chunk)
    return chunk


# ============================================================================
# 1. Constructor and Properties
# ============================================================================


def test_init_and_properties(
    index: SqlArchiveIndex,
    counting_embedding_provider: CountingEmbeddingProvider,
    reranker: FakeArchiveReranker,
) -> None:
    retriever = ArchiveRetriever(
        index=index,
        embedding_provider=counting_embedding_provider,
        reranker=reranker,
        lexical_top_k=20,
        dense_top_k=25,
        rerank_top_k=8,
    )
    assert retriever.index is index
    assert retriever.embedding_provider is counting_embedding_provider
    assert retriever.reranker is reranker
    assert retriever.lexical_top_k == 20
    assert retriever.dense_top_k == 25
    assert retriever.rerank_top_k == 8

    # Non-positive top_k raises
    with pytest.raises(ValueError, match="top_k values must be positive"):
        ArchiveRetriever(
            index=index,
            embedding_provider=counting_embedding_provider,
            reranker=reranker,
            lexical_top_k=0,
        )
    with pytest.raises(ValueError, match="top_k values must be positive"):
        ArchiveRetriever(
            index=index,
            embedding_provider=counting_embedding_provider,
            reranker=reranker,
            dense_top_k=-1,
        )
    with pytest.raises(ValueError, match="top_k values must be positive"):
        ArchiveRetriever(
            index=index,
            embedding_provider=counting_embedding_provider,
            reranker=reranker,
            rerank_top_k=0,
        )


# ============================================================================
# 2. Scope Validation
# ============================================================================


def test_validate_archive_scope_enforced(
    index: SqlArchiveIndex,
    counting_embedding_provider: CountingEmbeddingProvider,
    reranker: FakeArchiveReranker,
) -> None:
    retriever = ArchiveRetriever(
        index=index,
        embedding_provider=counting_embedding_provider,
        reranker=reranker,
    )

    invalid_scopes = [
        # archive_scope is False
        EvidenceScope(family_id=AUTHORITATIVE_FAMILY_ID, archive_scope=False),
        # pinned document_id
        EvidenceScope(
            family_id=AUTHORITATIVE_FAMILY_ID,
            archive_scope=True,
            document_id="doc_pinned",
        ),
        # pinned parse_run_id
        EvidenceScope(
            family_id=AUTHORITATIVE_FAMILY_ID,
            archive_scope=True,
            parse_run_id="run_pinned",
        ),
        # pinned document_version
        EvidenceScope(
            family_id=AUTHORITATIVE_FAMILY_ID,
            archive_scope=True,
            document_version=1,
        ),
        # non-authoritative family_id
        EvidenceScope(
            family_id="wrong_family",
            archive_scope=True,
        ),
    ]

    for scope in invalid_scopes:
        with pytest.raises(ValueError):
            asyncio.run(retriever.retrieve("tuyển sinh", scope=scope))


# ============================================================================
# 3. Happy Path: 3 Current Documents Cross-Document Retrieval
# ============================================================================


def test_happy_path_cross_document_retrieval(
    session_factory: sessionmaker[Session],
    index: SqlArchiveIndex,
    base_embedding_provider: FakeEmbeddingProvider,
    valid_scope: EvidenceScope,
) -> None:
    async def _test() -> None:
        t1 = "Quy định hướng dẫn tuyển sinh đại học chính quy năm 2026"
        t2 = "Kế hoạch phân bổ chỉ tiêu tuyển sinh cao đẳng sư phạm năm 2026"
        t3 = "Hướng dẫn chế độ chính sách học bổng cho sinh viên tuyển sinh mới"

        emb_res = await base_embedding_provider.embed_documents([t1, t2, t3])

        # Seed 3 documents
        for i, (text, vec) in enumerate(zip([t1, t2, t3], emb_res.vectors, strict=True), start=1):
            doc_id = f"doc_{i}"
            run_id = f"run_{i}"
            _seed_document(
                session_factory,
                doc_id,
                current_parse_run_id=run_id,
                document_type="Thông tư",
                document_number=f"{i}/2026/TT-BGDĐT",
            )
            _seed_parse_run(session_factory, run_id, doc_id, version=1, is_current=True)
            _seed_chunk(
                session_factory,
                f"c_{doc_id}",
                doc_id,
                run_id,
                text=text,
                embedding=vec,
            )

        reranker = FakeArchiveReranker()
        retriever = ArchiveRetriever(
            index=index,
            embedding_provider=base_embedding_provider,
            reranker=reranker,
            lexical_top_k=10,
            dense_top_k=10,
            rerank_top_k=10,
        )

        result = await retriever.retrieve("tuyển sinh năm 2026", scope=valid_scope)

        assert isinstance(result, ArchiveRetrievalResult)
        assert len(result.documents) == 3
        assert result.allowed_document_ids == ["doc_1", "doc_2", "doc_3"]
        assert result.lexical_count == 3
        assert result.dense_count == 3
        assert len(result.candidates) == 3

        # Returns candidates from more than one document
        retrieved_docs = {c.chunk.document_id for c in result.candidates}
        assert len(retrieved_docs) > 1
        assert retrieved_docs == {"doc_1", "doc_2", "doc_3"}

        # Dense 1-based ranks and retriever="reranked"
        assert [c.rank for c in result.candidates] == [1, 2, 3]
        assert all(c.retriever == "reranked" for c in result.candidates)

    asyncio.run(_test())


# ============================================================================
# 4. Stale Parse-Run Chunks Never Appear
# ============================================================================


def test_stale_parse_run_chunks_never_appear(
    session_factory: sessionmaker[Session],
    index: SqlArchiveIndex,
    base_embedding_provider: FakeEmbeddingProvider,
    valid_scope: EvidenceScope,
) -> None:
    async def _test() -> None:
        doc_id = "doc_stale_test"
        run_v1 = "run_stale_v1"
        run_v2 = "run_stale_v2"

        _seed_document(
            session_factory,
            doc_id,
            current_parse_run_id=run_v2,
            document_number="10/2026/TT-BGDĐT",
        )
        _seed_parse_run(session_factory, run_v1, doc_id, version=1, is_current=False)
        _seed_parse_run(session_factory, run_v2, doc_id, version=2, is_current=True)

        t_v1 = "Quy định đào tạo phiên bản cũ v1 đã hết hiệu lực"
        t_v2 = "Quy định đào tạo phiên bản mới v2 đang có hiệu lực thi hành"
        emb_res = await base_embedding_provider.embed_documents([t_v1, t_v2])

        _seed_chunk(
            session_factory,
            "chunk_stale_v1",
            doc_id,
            run_v1,
            doc_version=1,
            text=t_v1,
            embedding=emb_res.vectors[0],
        )
        _seed_chunk(
            session_factory,
            "chunk_current_v2",
            doc_id,
            run_v2,
            doc_version=2,
            text=t_v2,
            embedding=emb_res.vectors[1],
        )

        retriever = ArchiveRetriever(
            index=index,
            embedding_provider=base_embedding_provider,
            reranker=FakeArchiveReranker(),
        )

        result = await retriever.retrieve("đào tạo", scope=valid_scope)

        assert len(result.candidates) == 1
        assert result.candidates[0].chunk.chunk_id == "chunk_current_v2"
        assert result.candidates[0].chunk.parse_run_id == run_v2
        assert result.candidates[0].chunk.document_version == 2
        assert result.documents[0].parse_run_id == run_v2

    asyncio.run(_test())


# ============================================================================
# 5. Allow-List Built Before Retrieval & Filter Enforced
# ============================================================================


def test_allow_list_built_before_retrieval_and_filtered(
    session_factory: sessionmaker[Session],
    index: SqlArchiveIndex,
    base_embedding_provider: FakeEmbeddingProvider,
    valid_scope: EvidenceScope,
) -> None:
    async def _test() -> None:
        # Seed 3 documents: 1 Thông tư, 2 Quyết định
        for i in range(1, 4):
            doc_id = f"doc_f_{i}"
            run_id = f"run_f_{i}"
            dtype = "Thông tư" if i == 1 else "Quyết định"
            _seed_document(
                session_factory,
                doc_id,
                current_parse_run_id=run_id,
                document_type=dtype,
                document_number=f"{i}/2026/TT-BGDĐT" if i == 1 else f"{i}/2026/QĐ-UBND",
            )
            _seed_parse_run(session_factory, run_id, doc_id, version=1, is_current=True)
            _seed_chunk(
                session_factory,
                f"c_f_{i}",
                doc_id,
                run_id,
                text=f"Nội dung quy định quản lý ngân sách {i}",
                embedding=[0.5, 0.5] + [0.0] * 1022,
            )

        retriever = ArchiveRetriever(
            index=index,
            embedding_provider=base_embedding_provider,
            reranker=FakeArchiveReranker(),
        )

        filt = ArchiveFilter(document_types=["Thông tư"])
        result = await retriever.retrieve("quản lý ngân sách", scope=valid_scope, filters=filt)

        # Allow-list contains exactly doc_f_1
        assert result.allowed_document_ids == ["doc_f_1"]
        assert len(result.documents) == 1
        assert result.documents[0].document_id == "doc_f_1"
        assert result.documents[0].document_type == "Thông tư"

        # No candidates from other documents
        assert len(result.candidates) == 1
        assert result.candidates[0].chunk.document_id == "doc_f_1"

    asyncio.run(_test())


# ============================================================================
# 6. Identifier Boost Reorders But Never Changes Membership
# ============================================================================


def test_identifier_boost_reorders_without_changing_membership(
    session_factory: sessionmaker[Session],
    index: SqlArchiveIndex,
    base_embedding_provider: FakeEmbeddingProvider,
    valid_scope: EvidenceScope,
) -> None:
    async def _test() -> None:
        # Seed 3 documents with distinct document numbers
        docs_info = [
            (
                "doc_id_1",
                "19/2026/TT-BGDĐT",
                "Hướng dẫn công tác khen thưởng học sinh giỏi toàn quốc",
            ),
            (
                "doc_id_2",
                "57/QĐ-UBND",
                "Hướng dẫn công tác khen thưởng cán bộ xuất sắc ngành giáo dục",
            ),
            ("doc_id_3", "12/KH-UBND", "Hướng dẫn công tác khen thưởng phong trào thi đua cơ sở"),
        ]

        texts = [d[2] for d in docs_info]
        emb_res = await base_embedding_provider.embed_documents(texts)

        for (doc_id, doc_num, text), vec in zip(docs_info, emb_res.vectors, strict=True):
            run_id = f"run_{doc_id}"
            _seed_document(
                session_factory,
                doc_id,
                current_parse_run_id=run_id,
                document_number=doc_num,
            )
            _seed_parse_run(session_factory, run_id, doc_id, version=1, is_current=True)
            _seed_chunk(
                session_factory,
                f"chunk_{doc_id}",
                doc_id,
                run_id,
                text=text,
                embedding=vec,
            )

        retriever = ArchiveRetriever(
            index=index,
            embedding_provider=base_embedding_provider,
            reranker=FakeArchiveReranker(),
            lexical_top_k=10,
            dense_top_k=10,
            rerank_top_k=10,
        )

        # Query without document number
        res_generic = await retriever.retrieve("khen thưởng giáo dục", scope=valid_scope)
        # Query with exact document number for doc 2
        res_boosted = await retriever.retrieve(
            "khen thưởng giáo dục theo 57/QĐ-UBND", scope=valid_scope
        )

        generic_chunk_ids = {c.chunk.chunk_id for c in res_generic.candidates}
        boosted_chunk_ids = {c.chunk.chunk_id for c in res_boosted.candidates}

        # Assert SET EQUALITY: boost NEVER adds or removes a candidate
        assert generic_chunk_ids == boosted_chunk_ids
        assert len(generic_chunk_ids) == 3

        # In boosted query, the document whose number was named is rank 1
        assert res_boosted.candidates[0].chunk.document_id == "doc_id_2"
        assert res_boosted.candidates[0].chunk.chunk_id == "chunk_doc_id_2"
        assert res_boosted.candidates[0].rank == 1

        # Ranks are dense 1..N with no gaps or duplicates
        assert [c.rank for c in res_boosted.candidates] == [1, 2, 3]

    asyncio.run(_test())


# ============================================================================
# 7. Dense 1..N Ranks After Boost
# ============================================================================


def test_ranks_after_boost_are_dense_1_to_n(
    session_factory: sessionmaker[Session],
    index: SqlArchiveIndex,
    base_embedding_provider: FakeEmbeddingProvider,
    valid_scope: EvidenceScope,
) -> None:
    async def _test() -> None:
        for i in range(5):
            doc_id = f"doc_dense_rank_{i}"
            run_id = f"run_dense_rank_{i}"
            _seed_document(
                session_factory,
                doc_id,
                current_parse_run_id=run_id,
                document_number=f"{i + 10}/2026/TT-BGDĐT",
            )
            _seed_parse_run(session_factory, run_id, doc_id, version=1, is_current=True)
            _seed_chunk(
                session_factory,
                f"c_dense_rank_{i}",
                doc_id,
                run_id,
                text=f"Nội dung kiểm tra thanh tra giáo dục mục {i}",
                embedding=[1.0, float(i)] + [0.0] * 1022,
            )

        retriever = ArchiveRetriever(
            index=index,
            embedding_provider=base_embedding_provider,
            reranker=FakeArchiveReranker(),
            rerank_top_k=5,
        )

        res = await retriever.retrieve(
            "thanh tra giáo dục theo 13/2026/TT-BGDĐT", scope=valid_scope
        )
        ranks = [c.rank for c in res.candidates]
        assert ranks == [1, 2, 3, 4, 5]

    asyncio.run(_test())


# ============================================================================
# 8. Embedding Version Mismatch Raises
# ============================================================================


def test_embedding_version_mismatch_raises(
    session_factory: sessionmaker[Session],
    valid_scope: EvidenceScope,
) -> None:
    async def _test() -> None:
        # Index configured with v2
        index = SqlArchiveIndex(session_factory, embedding_version="bge-m3-v2")

        doc_id = "doc_mismatch"
        run_id = "run_mismatch"
        _seed_document(session_factory, doc_id, current_parse_run_id=run_id)
        _seed_parse_run(session_factory, run_id, doc_id, version=1, is_current=True)
        _seed_chunk(
            session_factory,
            "c_mismatch",
            doc_id,
            run_id,
            text="Văn bản có embedding v2",
            embedding=[1.0, 0.0] + [0.0] * 1022,
            embedding_version="bge-m3-v2",
        )

        # Provider configured with v1
        provider_v1 = FakeEmbeddingProvider(
            model_id="fake-bge-m3",
            dimension=1024,
            embedding_version="bge-m3-v1",
        )

        retriever = ArchiveRetriever(
            index=index,
            embedding_provider=provider_v1,
            reranker=FakeArchiveReranker(),
        )

        with pytest.raises(ArchiveEmbeddingVersionMismatchError) as exc_info:
            await retriever.retrieve("văn bản", scope=valid_scope)

        err = exc_info.value
        assert err.provider_version == "bge-m3-v1"
        assert err.index_version == "bge-m3-v2"
        assert "Embedding version mismatch" in str(err)
        assert "bge-m3-v1" in str(err)
        assert "bge-m3-v2" in str(err)

    asyncio.run(_test())


# ============================================================================
# 9. Archive With Chunks But NO Embeddings Still Returns Lexical Results
# ============================================================================


def test_archive_without_embeddings_returns_lexical_gracefully(
    session_factory: sessionmaker[Session],
    index: SqlArchiveIndex,
    counting_embedding_provider: CountingEmbeddingProvider,
    valid_scope: EvidenceScope,
) -> None:
    async def _test() -> None:
        doc_id = "doc_no_emb"
        run_id = "run_no_emb"
        _seed_document(session_factory, doc_id, current_parse_run_id=run_id)
        _seed_parse_run(session_factory, run_id, doc_id, version=1, is_current=True)
        _seed_chunk(
            session_factory,
            "c_no_emb",
            doc_id,
            run_id,
            text="Quy định tuyển sinh không có vector embedding",
            embedding=None,
            embedding_version=None,
        )

        retriever = ArchiveRetriever(
            index=index,
            embedding_provider=counting_embedding_provider,
            reranker=FakeArchiveReranker(),
        )

        res = await retriever.retrieve("tuyển sinh", scope=valid_scope)

        assert len(res.candidates) == 1
        assert res.candidates[0].chunk.chunk_id == "c_no_emb"
        assert res.lexical_count == 1
        assert res.dense_count == 0
        # embed_query is skipped when embedded_chunks == 0
        assert counting_embedding_provider.embed_query_count == 0

    asyncio.run(_test())


# ============================================================================
# 10. Empty / Whitespace Query Handling
# ============================================================================


def test_empty_and_whitespace_query(
    session_factory: sessionmaker[Session],
    index: SqlArchiveIndex,
    counting_embedding_provider: CountingEmbeddingProvider,
    valid_scope: EvidenceScope,
) -> None:
    async def _test() -> None:
        doc_id = "doc_empty_q"
        run_id = "run_empty_q"
        _seed_document(session_factory, doc_id, current_parse_run_id=run_id)
        _seed_parse_run(session_factory, run_id, doc_id, version=1, is_current=True)
        _seed_chunk(
            session_factory,
            "c_eq",
            doc_id,
            run_id,
            text="Nội dung bài viết",
            embedding=[1.0] + [0.0] * 1023,
        )

        retriever = ArchiveRetriever(
            index=index,
            embedding_provider=counting_embedding_provider,
            reranker=FakeArchiveReranker(),
        )

        for empty_q in ["", "   ", "\t", "\n", " \t \n "]:
            res = await retriever.retrieve(empty_q, scope=valid_scope)
            assert res.candidates == []
            assert len(res.documents) == 1
            assert res.documents[0].document_id == doc_id
            assert res.allowed_document_ids == [doc_id]
            assert res.lexical_count == 0
            assert res.dense_count == 0

        # Provider was not called for empty queries
        assert counting_embedding_provider.embed_query_count == 0

    asyncio.run(_test())


# ============================================================================
# 11. Empty Archive Returns Immediately Without Calling Provider
# ============================================================================


def test_empty_archive_returns_empty_without_calling_provider(
    index: SqlArchiveIndex,
    counting_embedding_provider: CountingEmbeddingProvider,
    valid_scope: EvidenceScope,
) -> None:
    async def _test() -> None:
        reranker = FakeArchiveReranker()
        retriever = ArchiveRetriever(
            index=index,
            embedding_provider=counting_embedding_provider,
            reranker=reranker,
        )

        res = await retriever.retrieve("bất kỳ câu hỏi nào", scope=valid_scope)

        assert res.candidates == []
        assert res.documents == []
        assert res.allowed_document_ids == []
        assert res.lexical_count == 0
        assert res.dense_count == 0
        assert counting_embedding_provider.embed_query_count == 0
        assert counting_embedding_provider.embed_documents_count == 0
        assert reranker.call_count == 0

    asyncio.run(_test())


# ============================================================================
# 12. embed_query Used and embed_documents Never Called
# ============================================================================


def test_embed_query_used_and_embed_documents_never_called(
    session_factory: sessionmaker[Session],
    index: SqlArchiveIndex,
    counting_embedding_provider: CountingEmbeddingProvider,
    valid_scope: EvidenceScope,
) -> None:
    async def _test() -> None:
        doc_id = "doc_embed_call"
        run_id = "run_embed_call"
        _seed_document(session_factory, doc_id, current_parse_run_id=run_id)
        _seed_parse_run(session_factory, run_id, doc_id, version=1, is_current=True)
        _seed_chunk(
            session_factory,
            "c_ec",
            doc_id,
            run_id,
            text="Chính sách học bổng sinh viên",
            embedding=[1.0] + [0.0] * 1023,
        )

        retriever = ArchiveRetriever(
            index=index,
            embedding_provider=counting_embedding_provider,
            reranker=FakeArchiveReranker(),
        )

        await retriever.retrieve("học bổng", scope=valid_scope)

        assert counting_embedding_provider.embed_query_count == 1
        assert counting_embedding_provider.embed_documents_count == 0

    asyncio.run(_test())


# ============================================================================
# 13. Determinism: Two Identical Calls Return Identical Order
# ============================================================================


def test_retrieval_determinism(
    session_factory: sessionmaker[Session],
    index: SqlArchiveIndex,
    base_embedding_provider: FakeEmbeddingProvider,
    valid_scope: EvidenceScope,
) -> None:
    async def _test() -> None:
        for i in range(4):
            doc_id = f"doc_det_{i}"
            run_id = f"run_det_{i}"
            _seed_document(
                session_factory,
                doc_id,
                current_parse_run_id=run_id,
                document_number=f"{i}/2026/QĐ-UBND",
            )
            _seed_parse_run(session_factory, run_id, doc_id, version=1, is_current=True)
            _seed_chunk(
                session_factory,
                f"c_det_{i}",
                doc_id,
                run_id,
                text=f"Nội dung quy định xác thực và kiểm toán hồ sơ {i}",
                embedding=[1.0, float(i)] + [0.0] * 1022,
            )

        retriever = ArchiveRetriever(
            index=index,
            embedding_provider=base_embedding_provider,
            reranker=FakeArchiveReranker(),
        )

        res1 = await retriever.retrieve("kiểm toán hồ sơ", scope=valid_scope)
        res2 = await retriever.retrieve("kiểm toán hồ sơ", scope=valid_scope)

        cids1 = [c.chunk.chunk_id for c in res1.candidates]
        cids2 = [c.chunk.chunk_id for c in res2.candidates]
        assert cids1 == cids2

        ranks1 = [c.rank for c in res1.candidates]
        ranks2 = [c.rank for c in res2.candidates]
        assert ranks1 == ranks2

    asyncio.run(_test())


# ============================================================================
# 14. Independent Current-Version Re-Check Defense Against Leaks
# ============================================================================


def test_independent_current_version_recheck_raises_on_leak(
    valid_scope: EvidenceScope,
    base_embedding_provider: FakeEmbeddingProvider,
) -> None:
    async def _test() -> None:
        # Mock index that leaks a chunk from an un-allowed document
        allowed_ref = ArchiveDocumentRef(
            document_id="doc_allowed",
            parse_run_id="run_allowed",
            document_version=1,
            requires_user_review=False,
        )

        class LeakingArchiveIndex:
            def current_documents(self, scope, filters=None):
                return [allowed_ref]

            def stats(self, scope, filters=None):
                from mamagift_retrieval.archive.protocol import ArchiveIndexStats

                return ArchiveIndexStats(
                    total_documents=1,
                    total_chunks=1,
                    embedded_chunks=1,
                    embedding_version="fake-bge-m3-v1",
                )

            def search_lexical(self, scope, query, top_k, filters=None):
                from mamagift_retrieval.chunk import Chunk, ChunkType

                leaked_chunk = Chunk(
                    chunk_id="c_leaked",
                    document_id="doc_LEAKED_OUTSIDE",
                    parse_run_id="run_leaked",
                    document_version=1,
                    chunk_type=ChunkType.PARAGRAPH,
                    text="leaked text",
                    source_block_ids=["b1"],
                    source_page_numbers=[1],
                )
                return [
                    ScoredChunk(
                        chunk=leaked_chunk,
                        score=1.0,
                        rank=1,
                        retriever="lexical",
                    )
                ]

            def search_dense(self, scope, query_vector, top_k, filters=None):
                return []

        retriever = ArchiveRetriever(
            index=LeakingArchiveIndex(),  # type: ignore[arg-type]
            embedding_provider=base_embedding_provider,
            reranker=FakeArchiveReranker(),
        )

        with pytest.raises(ValueError, match="is not in allowed current documents"):
            await retriever.retrieve("test", scope=valid_scope)

    asyncio.run(_test())


# ============================================================================
# 15. Additional Defense and Edge Case Tests
# ============================================================================


def test_dense_leak_raises_value_error(
    valid_scope: EvidenceScope,
    base_embedding_provider: FakeEmbeddingProvider,
) -> None:
    async def _test() -> None:
        allowed_ref = ArchiveDocumentRef(
            document_id="doc_allowed",
            parse_run_id="run_allowed",
            document_version=1,
            requires_user_review=False,
        )

        class DenseLeakingArchiveIndex:
            def current_documents(self, scope, filters=None):
                return [allowed_ref]

            def stats(self, scope, filters=None):
                from mamagift_retrieval.archive.protocol import ArchiveIndexStats

                return ArchiveIndexStats(
                    total_documents=1,
                    total_chunks=1,
                    embedded_chunks=1,
                    embedding_version="fake-bge-m3-v1",
                )

            def search_lexical(self, scope, query, top_k, filters=None):
                return []

            def search_dense(self, scope, query_vector, top_k, filters=None):
                from mamagift_retrieval.chunk import Chunk, ChunkType

                leaked_chunk = Chunk(
                    chunk_id="c_dense_leaked",
                    document_id="doc_LEAKED_DENSE",
                    parse_run_id="run_leaked",
                    document_version=1,
                    chunk_type=ChunkType.PARAGRAPH,
                    text="dense leaked text",
                    source_block_ids=["b1"],
                    source_page_numbers=[1],
                )
                return [
                    ScoredChunk(
                        chunk=leaked_chunk,
                        score=0.9,
                        rank=1,
                        retriever="dense",
                    )
                ]

        retriever = ArchiveRetriever(
            index=DenseLeakingArchiveIndex(),  # type: ignore[arg-type]
            embedding_provider=base_embedding_provider,
            reranker=FakeArchiveReranker(),
        )

        with pytest.raises(ValueError, match="is not in allowed current documents"):
            await retriever.retrieve("test", scope=valid_scope)

    asyncio.run(_test())


def test_reranker_leak_raises_value_error(
    session_factory: sessionmaker[Session],
    index: SqlArchiveIndex,
    base_embedding_provider: FakeEmbeddingProvider,
    valid_scope: EvidenceScope,
) -> None:
    async def _test() -> None:
        doc_id = "doc_rerank_leak"
        run_id = "run_rerank_leak"
        _seed_document(session_factory, doc_id, current_parse_run_id=run_id)
        _seed_parse_run(session_factory, run_id, doc_id, version=1, is_current=True)
        _seed_chunk(
            session_factory,
            "c_rl",
            doc_id,
            run_id,
            text="Valid chunk in allowed document",
            embedding=[1.0] + [0.0] * 1023,
        )

        class LeakingReranker:
            @property
            def reranker_version(self) -> str:
                return "leaking-reranker-v1"

            async def rerank(self, query, candidates, top_k):
                from mamagift_retrieval.chunk import Chunk, ChunkType

                leaked_chunk = Chunk(
                    chunk_id="c_reranker_leaked",
                    document_id="doc_RERANKER_INVENTED",
                    parse_run_id="run_bad",
                    document_version=1,
                    chunk_type=ChunkType.PARAGRAPH,
                    text="invented chunk",
                    source_block_ids=["b1"],
                    source_page_numbers=[1],
                )
                return [
                    ScoredChunk(
                        chunk=leaked_chunk,
                        score=1.0,
                        rank=1,
                        retriever="reranked",
                    )
                ]

        retriever = ArchiveRetriever(
            index=index,
            embedding_provider=base_embedding_provider,
            reranker=LeakingReranker(),  # type: ignore[arg-type]
        )

        with pytest.raises(ValueError, match="is not in allowed current documents"):
            await retriever.retrieve("test", scope=valid_scope)

    asyncio.run(_test())


def test_embedding_result_version_mismatch_raises(
    session_factory: sessionmaker[Session],
    index: SqlArchiveIndex,
    valid_scope: EvidenceScope,
) -> None:
    async def _test() -> None:
        doc_id = "doc_res_mismatch"
        run_id = "run_res_mismatch"
        _seed_document(session_factory, doc_id, current_parse_run_id=run_id)
        _seed_parse_run(session_factory, run_id, doc_id, version=1, is_current=True)
        _seed_chunk(
            session_factory,
            "c_rm",
            doc_id,
            run_id,
            text="Chunk text",
            embedding=[1.0] + [0.0] * 1023,
            embedding_version="fake-bge-m3-v1",
        )

        class BadResultEmbeddingProvider:
            @property
            def model_id(self) -> str:
                return "fake-bge-m3"

            @property
            def dimension(self) -> int:
                return 1024

            @property
            def embedding_version(self) -> str:
                return "fake-bge-m3-v1"

            async def embed_documents(self, texts: list[str]) -> EmbeddingResult:
                raise NotImplementedError

            async def embed_query(self, text: str) -> EmbeddingResult:
                return EmbeddingResult(
                    vectors=[[1.0] + [0.0] * 1023],
                    model="fake-bge-m3",
                    dimension=1024,
                    embedding_version="unexpected-version-returned",
                )

        retriever = ArchiveRetriever(
            index=index,
            embedding_provider=BadResultEmbeddingProvider(),  # type: ignore[arg-type]
            reranker=FakeArchiveReranker(),
        )

        with pytest.raises(ArchiveEmbeddingVersionMismatchError) as exc_info:
            await retriever.retrieve("query", scope=valid_scope)

        err = exc_info.value
        assert err.provider_version == "fake-bge-m3-v1"
        assert err.index_version == "unexpected-version-returned"

    asyncio.run(_test())


def test_filter_matches_nothing_returns_empty_immediately(
    session_factory: sessionmaker[Session],
    index: SqlArchiveIndex,
    counting_embedding_provider: CountingEmbeddingProvider,
    valid_scope: EvidenceScope,
) -> None:
    async def _test() -> None:
        doc_id = "doc_fn"
        run_id = "run_fn"
        _seed_document(session_factory, doc_id, current_parse_run_id=run_id)
        _seed_parse_run(session_factory, run_id, doc_id, version=1, is_current=True)
        _seed_chunk(
            session_factory,
            "c_fn",
            doc_id,
            run_id,
            text="Valid document",
            embedding=[1.0] + [0.0] * 1023,
        )

        retriever = ArchiveRetriever(
            index=index,
            embedding_provider=counting_embedding_provider,
            reranker=FakeArchiveReranker(),
        )

        empty_filter = ArchiveFilter(document_ids=[])
        res = await retriever.retrieve("query", scope=valid_scope, filters=empty_filter)

        assert res.candidates == []
        assert res.documents == []
        assert res.allowed_document_ids == []
        assert res.lexical_count == 0
        assert res.dense_count == 0
        # Provider never called
        assert counting_embedding_provider.embed_query_count == 0

    asyncio.run(_test())


def test_rerank_top_k_truncation(
    session_factory: sessionmaker[Session],
    index: SqlArchiveIndex,
    base_embedding_provider: FakeEmbeddingProvider,
    valid_scope: EvidenceScope,
) -> None:
    async def _test() -> None:
        for i in range(5):
            doc_id = f"doc_topk_{i}"
            run_id = f"run_topk_{i}"
            _seed_document(session_factory, doc_id, current_parse_run_id=run_id)
            _seed_parse_run(session_factory, run_id, doc_id, version=1, is_current=True)
            _seed_chunk(
                session_factory,
                f"c_topk_{i}",
                doc_id,
                run_id,
                text=f"Quy định số {i} về ngân sách",
                embedding=[1.0, float(i)] + [0.0] * 1022,
            )

        retriever = ArchiveRetriever(
            index=index,
            embedding_provider=base_embedding_provider,
            reranker=FakeArchiveReranker(),
            lexical_top_k=10,
            dense_top_k=10,
            rerank_top_k=2,
        )

        res = await retriever.retrieve("ngân sách", scope=valid_scope)
        assert len(res.candidates) == 2
        assert [c.rank for c in res.candidates] == [1, 2]
        assert len(res.documents) == 5
        assert res.lexical_count == 5
        assert res.dense_count == 5

    asyncio.run(_test())
