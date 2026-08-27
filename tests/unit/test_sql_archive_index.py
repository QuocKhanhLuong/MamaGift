"""Unit tests for SqlArchiveIndex and ArchiveIndex protocol on SQLite in-memory."""

from __future__ import annotations

import inspect
from datetime import UTC, date, datetime
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db import Base
from app.models import Document, DocumentChunk, ParseRun
from mamagift_retrieval.archive import (
    ArchiveFilter,
    ArchiveIndex,
)
from mamagift_retrieval.archive.protocol import AUTHORITATIVE_FAMILY_ID
from mamagift_retrieval.archive.sql_archive_index import SqlArchiveIndex
from mamagift_retrieval.chunk import ChunkType
from mamagift_retrieval.scope import EvidenceScope

NOW = datetime(2026, 8, 27, 12, 0, 0, tzinfo=UTC)


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
    return SqlArchiveIndex(session_factory)


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
    embedding_model: str | None = "bge-m3",
    embedding_version: str | None = "v1",
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
# 1. Protocol Conformance & Signatures
# ============================================================================


def test_protocol_conformance(index: SqlArchiveIndex) -> None:
    assert isinstance(index, ArchiveIndex)
    assert issubclass(SqlArchiveIndex, ArchiveIndex)

    # Check method signatures
    for method_name in ("current_documents", "search_dense", "search_lexical", "stats"):
        assert hasattr(index, method_name)
        sig = inspect.signature(getattr(index, method_name))
        assert "scope" in sig.parameters


# ============================================================================
# 2. Scope Guards Across All Four Methods
# ============================================================================


def test_scope_guards_reject_invalid_scopes(index: SqlArchiveIndex) -> None:
    invalid_scopes = [
        # 1. archive_scope is False
        EvidenceScope(family_id=AUTHORITATIVE_FAMILY_ID, archive_scope=False),
        # 2. pinned document_id
        EvidenceScope(
            family_id=AUTHORITATIVE_FAMILY_ID,
            archive_scope=True,
            document_id="doc_pinned",
        ),
        # 3. pinned parse_run_id
        EvidenceScope(
            family_id=AUTHORITATIVE_FAMILY_ID,
            archive_scope=True,
            parse_run_id="run_pinned",
        ),
        # 4. pinned document_version
        EvidenceScope(
            family_id=AUTHORITATIVE_FAMILY_ID,
            archive_scope=True,
            document_version=1,
        ),
        # 5. non-authoritative family_id
        EvidenceScope(
            family_id="other_family",
            archive_scope=True,
        ),
    ]

    for scope in invalid_scopes:
        with pytest.raises(ValueError):
            index.current_documents(scope)
        with pytest.raises(ValueError):
            index.search_dense(scope, [1.0, 0.0], top_k=5)
        with pytest.raises(ValueError):
            index.search_lexical(scope, "quy định", top_k=5)
        with pytest.raises(ValueError):
            index.stats(scope)


# ============================================================================
# 3. The Current-Version Invariant: Stale Version Excluded
# ============================================================================


def test_stale_version_excluded(
    session_factory: sessionmaker[Session],
    index: SqlArchiveIndex,
    valid_scope: EvidenceScope,
) -> None:
    """Document with v1 (is_current=False) and v2 (is_current=True).

    Assert dense, lexical, current_documents, and stats return ONLY v2 chunks/records.
    """
    doc_id = "doc_ver_test"
    run_v1 = "run_v1"
    run_v2 = "run_v2"

    _seed_document(
        session_factory,
        doc_id,
        current_parse_run_id=run_v2,
        document_number="10/2026/TT-BGDĐT",
        document_type="Thông tư",
    )
    _seed_parse_run(session_factory, run_v1, doc_id, version=1, is_current=False)
    _seed_parse_run(session_factory, run_v2, doc_id, version=2, is_current=True)

    _seed_chunk(
        session_factory,
        "c_v1",
        doc_id,
        run_v1,
        doc_version=1,
        text="Văn bản phiên bản cũ một",
        embedding=[1.0, 0.0],
    )
    _seed_chunk(
        session_factory,
        "c_v2",
        doc_id,
        run_v2,
        doc_version=2,
        text="Văn bản phiên bản mới hai",
        embedding=[0.0, 1.0],
    )

    # 1. current_documents
    docs = index.current_documents(valid_scope)
    assert len(docs) == 1
    assert docs[0].document_id == doc_id
    assert docs[0].parse_run_id == run_v2
    assert docs[0].document_version == 2

    # 2. search_dense
    dense_results = index.search_dense(valid_scope, [1.0, 0.0], top_k=10)
    assert len(dense_results) == 1
    assert dense_results[0].chunk.chunk_id == "c_v2"
    assert dense_results[0].chunk.parse_run_id == run_v2
    assert dense_results[0].chunk.document_version == 2

    # 3. search_lexical
    lexical_results = index.search_lexical(valid_scope, "phiên bản", top_k=10)
    assert len(lexical_results) == 1
    assert lexical_results[0].chunk.chunk_id == "c_v2"

    # Query matching only v1 text returns empty
    v1_only_results = index.search_lexical(valid_scope, "cũ một", top_k=10)
    assert len(v1_only_results) == 0

    # 4. stats
    st = index.stats(valid_scope)
    assert st.total_documents == 1
    assert st.total_chunks == 1
    assert st.embedded_chunks == 1


# ============================================================================
# 4. Both Predicates Required: Mismatched Pointers Must Yield Nothing
# ============================================================================


def test_both_predicates_required(
    session_factory: sessionmaker[Session],
    index: SqlArchiveIndex,
    valid_scope: EvidenceScope,
) -> None:
    """A row where parse_runs.is_current=True but documents.current_parse_run_id points elsewhere.

    Must yield NOTHING from all 4 methods.
    """
    doc_id = "doc_mismatch"
    run_actual = "run_actual"
    run_orphan = "run_orphan"

    # doc points to run_actual, but run_orphan claims is_current=True
    _seed_document(
        session_factory,
        doc_id,
        current_parse_run_id=run_actual,
        document_number="99/QĐ-UBND",
    )
    _seed_parse_run(session_factory, run_actual, doc_id, version=1, is_current=False)
    _seed_parse_run(session_factory, run_orphan, doc_id, version=2, is_current=True)

    _seed_chunk(
        session_factory,
        "c_orphan",
        doc_id,
        run_orphan,
        doc_version=2,
        text="Chunk mồ côi không hợp lệ",
        embedding=[1.0, 0.0],
    )
    _seed_chunk(
        session_factory,
        "c_actual",
        doc_id,
        run_actual,
        doc_version=1,
        text="Chunk hiện tại nhưng run is_current false",
        embedding=[1.0, 0.0],
    )

    # All 4 methods must return empty
    assert index.current_documents(valid_scope) == []
    assert index.search_dense(valid_scope, [1.0, 0.0], top_k=10) == []
    assert index.search_lexical(valid_scope, "Chunk", top_k=10) == []
    stats_res = index.stats(valid_scope)
    assert stats_res.total_documents == 0
    assert stats_res.total_chunks == 0
    assert stats_res.embedded_chunks == 0


# ============================================================================
# 5. Cross-Document Retrieval
# ============================================================================


def test_cross_document_retrieval(
    session_factory: sessionmaker[Session],
    index: SqlArchiveIndex,
    valid_scope: EvidenceScope,
) -> None:
    """Three current documents: retrieval returns chunks across documents."""
    for i in (1, 2, 3):
        doc_id = f"doc_{i}"
        run_id = f"run_{i}"
        _seed_document(
            session_factory,
            doc_id,
            current_parse_run_id=run_id,
            document_type="Quyết định",
            document_number=f"{i}/2026/QĐ-UBND",
        )
        _seed_parse_run(session_factory, run_id, doc_id, version=1, is_current=True)
        _seed_chunk(
            session_factory,
            f"chunk_doc_{i}",
            doc_id,
            run_id,
            text=f"Quy định chung về quản lý tài chính văn bản {i}",
            embedding=[0.5, 0.5],
        )

    # 1. current_documents
    doc_refs = index.current_documents(valid_scope)
    assert len(doc_refs) == 3
    assert [d.document_id for d in doc_refs] == ["doc_1", "doc_2", "doc_3"]

    # 2. search_lexical matches all 3 documents
    lex_res = index.search_lexical(valid_scope, "quản lý tài chính", top_k=10)
    assert len(lex_res) == 3
    assert {r.chunk.document_id for r in lex_res} == {"doc_1", "doc_2", "doc_3"}

    # 3. search_dense matches all 3 documents
    dense_res = index.search_dense(valid_scope, [0.5, 0.5], top_k=10)
    assert len(dense_res) == 3
    assert {r.chunk.document_id for r in dense_res} == {"doc_1", "doc_2", "doc_3"}

    # 4. stats
    st = index.stats(valid_scope)
    assert st.total_documents == 3
    assert st.total_chunks == 3
    assert st.embedded_chunks == 3


# ============================================================================
# 6. Metadata Filters in Isolation & Combined
# ============================================================================


def test_filters_in_isolation(
    session_factory: sessionmaker[Session],
    index: SqlArchiveIndex,
    valid_scope: EvidenceScope,
) -> None:
    """Verify each filter field in isolation.

    Ensures NULL metadata docs are excluded from positive filters.
    """
    # doc 1: full metadata
    _seed_document(
        session_factory,
        "doc_filter_1",
        current_parse_run_id="run_f1",
        document_type="Thông tư",
        document_number="12/2026/TT-BGDĐT",
        issuer="Bộ Giáo dục và Đào tạo",
        issued_date=date(2026, 3, 15),
        requires_user_review=False,
    )
    _seed_parse_run(session_factory, "run_f1", "doc_filter_1", version=1, is_current=True)
    _seed_chunk(
        session_factory,
        "c_f1",
        "doc_filter_1",
        "run_f1",
        text="Tuyển sinh đại học năm 2026",
        embedding=[1.0, 0.0],
    )

    # doc 2: different metadata
    _seed_document(
        session_factory,
        "doc_filter_2",
        current_parse_run_id="run_f2",
        document_type="Nghị định",
        document_number="45/2026/NĐ-CP",
        issuer="Chính phủ",
        issued_date=date(2026, 5, 20),
        requires_user_review=True,
    )
    _seed_parse_run(session_factory, "run_f2", "doc_filter_2", version=1, is_current=True)
    _seed_chunk(
        session_factory,
        "c_f2",
        "doc_filter_2",
        "run_f2",
        text="Tuyển sinh quy định thi cử năm 2026",
        embedding=[0.0, 1.0],
    )

    # doc 3: NULL metadata
    _seed_document(
        session_factory,
        "doc_null_meta",
        current_parse_run_id="run_f3",
        document_type=None,
        document_number=None,
        issuer=None,
        issued_date=None,
        requires_user_review=False,
    )
    _seed_parse_run(session_factory, "run_f3", "doc_null_meta", version=1, is_current=True)
    _seed_chunk(
        session_factory,
        "c_f3",
        "doc_null_meta",
        "run_f3",
        text="Tuyển sinh không có thông tin xuất bản",
        embedding=[0.5, 0.5],
    )

    # 1. Filter by document_ids
    f_ids = ArchiveFilter(document_ids=["doc_filter_1"])
    res = index.current_documents(valid_scope, f_ids)
    assert len(res) == 1 and res[0].document_id == "doc_filter_1"

    # 2. Filter by document_types
    f_type = ArchiveFilter(document_types=["Thông tư"])
    res = index.current_documents(valid_scope, f_type)
    assert len(res) == 1 and res[0].document_id == "doc_filter_1"

    # 3. Filter by issuers (case-insensitive)
    f_issuer = ArchiveFilter(issuers=["bộ giáo dục và đào tạo"])
    res = index.current_documents(valid_scope, f_issuer)
    assert len(res) == 1 and res[0].document_id == "doc_filter_1"

    # 4. Filter by issued_date_from
    f_date_from = ArchiveFilter(issued_date_from=date(2026, 4, 1))
    res = index.current_documents(valid_scope, f_date_from)
    assert len(res) == 1 and res[0].document_id == "doc_filter_2"

    # 5. Filter by issued_date_to
    f_date_to = ArchiveFilter(issued_date_to=date(2026, 4, 1))
    res = index.current_documents(valid_scope, f_date_to)
    assert len(res) == 1 and res[0].document_id == "doc_filter_1"

    # 6. Filter by include_requires_review=False
    f_no_review = ArchiveFilter(include_requires_review=False)
    res = index.current_documents(valid_scope, f_no_review)
    assert len(res) == 2
    assert {r.document_id for r in res} == {"doc_filter_1", "doc_null_meta"}

    # 7. NULL metadata doc never matches positive filters
    assert (
        index.current_documents(valid_scope, ArchiveFilter(document_types=["Không tồn tại"])) == []
    )
    assert index.current_documents(valid_scope, ArchiveFilter(issuers=["Bộ Tài chính"])) == []


# ============================================================================
# 7. Normalised Document Numbers Matching
# ============================================================================


def test_document_numbers_filter_normalised(
    session_factory: sessionmaker[Session],
    index: SqlArchiveIndex,
    valid_scope: EvidenceScope,
) -> None:
    doc_id = "doc_norm_test"
    run_id = "run_norm_test"
    _seed_document(
        session_factory,
        doc_id,
        current_parse_run_id=run_id,
        document_number="19/2026/TT-BGDĐT",
    )
    _seed_parse_run(session_factory, run_id, doc_id, version=1, is_current=True)
    _seed_chunk(session_factory, "c_norm", doc_id, run_id, text="Nội dung thông tư 19")

    # Match with extra spaces, lowercase, slash spacing
    matching_filter = ArchiveFilter(document_numbers=[" 19 / 2026 / tt-bgdđt "])
    results = index.current_documents(valid_scope, matching_filter)
    assert len(results) == 1
    assert results[0].document_id == doc_id

    # Non-matching filter
    non_matching = ArchiveFilter(document_numbers=["20/2026/TT-BGDĐT"])
    assert index.current_documents(valid_scope, non_matching) == []


# ============================================================================
# 8. Empty List Filters Return Empty
# ============================================================================


def test_empty_list_filter_returns_empty(
    session_factory: sessionmaker[Session],
    index: SqlArchiveIndex,
    valid_scope: EvidenceScope,
) -> None:
    doc_id = "doc_empty_list"
    run_id = "run_empty_list"
    _seed_document(
        session_factory,
        doc_id,
        current_parse_run_id=run_id,
        document_type="Quyết định",
    )
    _seed_parse_run(session_factory, run_id, doc_id, version=1, is_current=True)
    _seed_chunk(
        session_factory, "c_empty", doc_id, run_id, text="Nội dung test", embedding=[1.0, 0.0]
    )

    empty_filters = [
        ArchiveFilter(document_types=[]),
        ArchiveFilter(document_ids=[]),
        ArchiveFilter(document_numbers=[]),
        ArchiveFilter(issuers=[]),
    ]

    for f in empty_filters:
        assert index.current_documents(valid_scope, f) == []
        assert index.search_dense(valid_scope, [1.0, 0.0], top_k=5, filters=f) == []
        assert index.search_lexical(valid_scope, "test", top_k=5, filters=f) == []
        st = index.stats(valid_scope, f)
        assert st.total_documents == 0
        assert st.total_chunks == 0
        assert st.embedded_chunks == 0


# ============================================================================
# 9. Date Range Inclusive at Both Ends & NULL Date Excluded
# ============================================================================


def test_date_range_inclusive_and_null_handling(
    session_factory: sessionmaker[Session],
    index: SqlArchiveIndex,
    valid_scope: EvidenceScope,
) -> None:
    docs_to_seed = [
        ("doc_d1", date(2026, 3, 1)),
        ("doc_d2", date(2026, 3, 15)),
        ("doc_d3", date(2026, 3, 31)),
        ("doc_d4", date(2026, 4, 1)),
        ("doc_null_date", None),
    ]

    for doc_id, issued_date in docs_to_seed:
        run_id = f"run_{doc_id}"
        _seed_document(
            session_factory,
            doc_id,
            current_parse_run_id=run_id,
            issued_date=issued_date,
        )
        _seed_parse_run(session_factory, run_id, doc_id, version=1, is_current=True)
        _seed_chunk(session_factory, f"c_{doc_id}", doc_id, run_id, text="Quy định ngày tháng")

    range_filter = ArchiveFilter(
        issued_date_from=date(2026, 3, 1),
        issued_date_to=date(2026, 3, 31),
    )
    res = index.current_documents(valid_scope, range_filter)
    res_ids = [r.document_id for r in res]
    # Inclusive on both ends: doc_d1 (3/1), doc_d2 (3/15), doc_d3 (3/31)
    assert res_ids == ["doc_d1", "doc_d2", "doc_d3"]
    assert "doc_d4" not in res_ids
    assert "doc_null_date" not in res_ids


# ============================================================================
# 10. Returned Chunks Carry Relational Metadata from Documents
# ============================================================================


def test_returned_chunks_carry_metadata(
    session_factory: sessionmaker[Session],
    index: SqlArchiveIndex,
    valid_scope: EvidenceScope,
) -> None:
    doc_id = "doc_meta_chunk"
    run_id = "run_meta_chunk"
    _seed_document(
        session_factory,
        doc_id,
        current_parse_run_id=run_id,
        document_type="Quyết định",
        document_number="57/QĐ-UBND",
        issuer="UBND Thành phố Hà Nội",
        issued_date=date(2026, 2, 15),
        title="Quyết định ban hành kế hoạch",
    )
    _seed_parse_run(session_factory, run_id, doc_id, version=1, is_current=True)
    _seed_chunk(
        session_factory,
        "c_meta",
        doc_id,
        run_id,
        text="Thực hiện theo quyết định 57",
        embedding=[0.8, 0.6],
        section_path=["Điều 5. Trách nhiệm thực hiện"],
    )

    # 1. From search_dense
    dense_res = index.search_dense(valid_scope, [0.8, 0.6], top_k=1)
    assert len(dense_res) == 1
    chunk_dense = dense_res[0].chunk
    assert chunk_dense.document_type == "Quyết định"
    assert chunk_dense.document_number == "57/QĐ-UBND"
    assert chunk_dense.issuer == "UBND Thành phố Hà Nội"
    assert chunk_dense.issued_date == "2026-02-15"
    assert chunk_dense.chunk_type == ChunkType.LEGAL_ARTICLE

    # 2. From search_lexical
    lex_res = index.search_lexical(valid_scope, "quyết định 57", top_k=1)
    assert len(lex_res) == 1
    chunk_lex = lex_res[0].chunk
    assert chunk_lex.document_type == "Quyết định"
    assert chunk_lex.document_number == "57/QĐ-UBND"
    assert chunk_lex.issuer == "UBND Thành phố Hà Nội"
    assert chunk_lex.issued_date == "2026-02-15"


# ============================================================================
# 11. BM25 Exact Identifier Ranking
# ============================================================================


def test_bm25_exact_identifier_ranking(
    session_factory: sessionmaker[Session],
    index: SqlArchiveIndex,
    valid_scope: EvidenceScope,
) -> None:
    """Seed 6 documents with similar document numbers; query exact number ranks target first."""
    docs = [
        (
            "doc_target",
            "19/2026/TT-BGDĐT",
            "Căn cứ theo Thông tư 19/2026/TT-BGDĐT về chế độ đãi ngộ",
        ),
        ("doc_sim1", "19/2025/TT-BGDĐT", "Căn cứ theo Thông tư 19/2025/TT-BGDĐT về tài chính"),
        ("doc_sim2", "20/2026/TT-BGDĐT", "Căn cứ theo Thông tư 20/2026/TT-BGDĐT về tuyển dụng"),
        ("doc_sim3", "19/2026/TT-BTC", "Căn cứ theo Thông tư 19/2026/TT-BTC về thuế"),
        ("doc_sim4", "18/2026/TT-BGDĐT", "Căn cứ theo Thông tư 18/2026/TT-BGDĐT về thi đua"),
        ("doc_other", "57/QĐ-UBND", "Căn cứ theo Quyết định 57/QĐ-UBND về tổ chức cán bộ"),
    ]

    for doc_id, doc_num, text in docs:
        run_id = f"run_{doc_id}"
        _seed_document(
            session_factory,
            doc_id,
            current_parse_run_id=run_id,
            document_number=doc_num,
        )
        _seed_parse_run(session_factory, run_id, doc_id, version=1, is_current=True)
        _seed_chunk(session_factory, f"chunk_{doc_id}", doc_id, run_id, text=text)

    results = index.search_lexical(valid_scope, "19/2026/TT-BGDĐT", top_k=5)
    assert len(results) > 0
    assert results[0].chunk.document_id == "doc_target"
    assert results[0].rank == 1


# ============================================================================
# 12. BM25 Legal Marker Ranking (Điều 7 vs Điều 8)
# ============================================================================


def test_bm25_dieu_marker_ranking(
    session_factory: sessionmaker[Session],
    index: SqlArchiveIndex,
    valid_scope: EvidenceScope,
) -> None:
    doc_id = "doc_dieu"
    run_id = "run_dieu"
    _seed_document(session_factory, doc_id, current_parse_run_id=run_id)
    _seed_parse_run(session_factory, run_id, doc_id, version=1, is_current=True)

    _seed_chunk(
        session_factory,
        "chunk_dieu_7",
        doc_id,
        run_id,
        chunk_index=0,
        text="Điều 7. Quy trình xử lý vi phạm kỷ luật trong cơ quan",
    )
    _seed_chunk(
        session_factory,
        "chunk_dieu_8",
        doc_id,
        run_id,
        chunk_index=1,
        text="Điều 8. Khen thưởng và vinh danh cán bộ xuất sắc trong cơ quan",
    )

    results = index.search_lexical(valid_scope, "Điều 7", top_k=5)
    assert len(results) == 2
    assert results[0].chunk.chunk_id == "chunk_dieu_7"
    assert results[0].rank == 1
    assert results[0].score > results[1].score


# ============================================================================
# 13. Determinism and Dense 1-Based Ranks
# ============================================================================


def test_deterministic_ranking_and_dense_ranks(
    session_factory: sessionmaker[Session],
    index: SqlArchiveIndex,
    valid_scope: EvidenceScope,
) -> None:
    doc_id = "doc_det"
    run_id = "run_det"
    _seed_document(session_factory, doc_id, current_parse_run_id=run_id)
    _seed_parse_run(session_factory, run_id, doc_id, version=1, is_current=True)

    for i in range(5):
        _seed_chunk(
            session_factory,
            f"c_det_{i}",
            doc_id,
            run_id,
            chunk_index=i,
            text=f"Quy định chung về thủ tục phần {i}",
            embedding=[1.0, float(i)],
        )

    # 5 runs of dense search
    dense_runs = [index.search_dense(valid_scope, [1.0, 0.0], top_k=5) for _ in range(5)]
    for r in dense_runs[1:]:
        assert [(c.chunk.chunk_id, c.score, c.rank) for c in r] == [
            (c.chunk.chunk_id, c.score, c.rank) for c in dense_runs[0]
        ]
    assert [c.rank for c in dense_runs[0]] == [1, 2, 3, 4, 5]

    # 5 runs of lexical search
    lex_runs = [index.search_lexical(valid_scope, "thủ tục", top_k=5) for _ in range(5)]
    for r in lex_runs[1:]:
        assert [(c.chunk.chunk_id, c.score, c.rank) for c in r] == [
            (c.chunk.chunk_id, c.score, c.rank) for c in lex_runs[0]
        ]
    assert [c.rank for c in lex_runs[0]] == [1, 2, 3, 4, 5]


# ============================================================================
# 14. Stale Embedding Version Excluded from Dense Search
# ============================================================================


def test_stale_embedding_version_excluded(
    session_factory: sessionmaker[Session],
    valid_scope: EvidenceScope,
) -> None:
    doc_id = "doc_emb_ver"
    run_id = "run_emb_ver"
    _seed_document(session_factory, doc_id, current_parse_run_id=run_id)
    _seed_parse_run(session_factory, run_id, doc_id, version=1, is_current=True)

    _seed_chunk(
        session_factory,
        "c_v1_emb",
        doc_id,
        run_id,
        chunk_index=0,
        text="Chunk phiên bản nhúng v1",
        embedding=[1.0, 0.0],
        embedding_version="v1",
    )
    _seed_chunk(
        session_factory,
        "c_v2_emb",
        doc_id,
        run_id,
        chunk_index=1,
        text="Chunk phiên bản nhúng v2",
        embedding=[0.0, 1.0],
        embedding_version="v2",
    )

    idx_v2 = SqlArchiveIndex(session_factory, embedding_version="v2")
    results = idx_v2.search_dense(valid_scope, [1.0, 0.0], top_k=5)
    assert len(results) == 1
    assert results[0].chunk.chunk_id == "c_v2_emb"


# ============================================================================
# 15. top_k Truncation and Error Handling
# ============================================================================


def test_top_k_truncation_and_errors(
    session_factory: sessionmaker[Session],
    index: SqlArchiveIndex,
    valid_scope: EvidenceScope,
) -> None:
    doc_id = "doc_topk"
    run_id = "run_topk"
    _seed_document(session_factory, doc_id, current_parse_run_id=run_id)
    _seed_parse_run(session_factory, run_id, doc_id, version=1, is_current=True)

    for i in range(5):
        _seed_chunk(
            session_factory,
            f"c_topk_{i}",
            doc_id,
            run_id,
            chunk_index=i,
            text=f"Mẫu nội dung văn bản {i}",
            embedding=[1.0, float(i)],
        )

    # top_k=2 truncates
    res_dense = index.search_dense(valid_scope, [1.0, 0.0], top_k=2)
    assert len(res_dense) == 2

    res_lex = index.search_lexical(valid_scope, "nội dung văn bản", top_k=2)
    assert len(res_lex) == 2

    # top_k <= 0 raises ValueError
    with pytest.raises(ValueError, match="positive integer"):
        index.search_dense(valid_scope, [1.0, 0.0], top_k=0)
    with pytest.raises(ValueError, match="positive integer"):
        index.search_dense(valid_scope, [1.0, 0.0], top_k=-1)
    with pytest.raises(ValueError, match="positive integer"):
        index.search_lexical(valid_scope, "nội dung", top_k=0)
    with pytest.raises(ValueError, match="positive integer"):
        index.search_lexical(valid_scope, "nội dung", top_k=-1)

    # empty query_vector raises ValueError
    with pytest.raises(ValueError, match="query_vector cannot be empty"):
        index.search_dense(valid_scope, [], top_k=5)

    # empty/whitespace lexical query returns []
    assert index.search_lexical(valid_scope, "", top_k=5) == []
    assert index.search_lexical(valid_scope, "   ", top_k=5) == []


# ============================================================================
# 16. Session or Factory Types
# ============================================================================


def test_session_or_factory_types(
    db_engine: Any,
    session_factory: sessionmaker[Session],
    valid_scope: EvidenceScope,
) -> None:
    _seed_document(session_factory, "doc_sess_test", current_parse_run_id="run_sess")
    _seed_parse_run(session_factory, "run_sess", "doc_sess_test", version=1, is_current=True)
    _seed_chunk(session_factory, "c_sess", "doc_sess_test", "run_sess", text="Test session")

    # 1. Engine
    idx_engine = SqlArchiveIndex(db_engine)
    assert len(idx_engine.current_documents(valid_scope)) == 1

    # 2. Session
    with session_factory() as session:
        idx_session = SqlArchiveIndex(session)
        assert len(idx_session.current_documents(valid_scope)) == 1

    # 3. Callable[[], Session]
    idx_callable = SqlArchiveIndex(lambda: session_factory())
    assert len(idx_callable.current_documents(valid_scope)) == 1

    # 4. Invalid type
    idx_invalid = SqlArchiveIndex(12345)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="unsupported session_or_factory type"):
        idx_invalid.current_documents(valid_scope)
