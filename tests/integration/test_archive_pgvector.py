"""Integration tests for SqlArchiveIndex and pgvector on live PostgreSQL 16.

Covers:
1. Exact cosine distance ordering via pgvector over 1024-dim vectors.
2. Stale-version exclusion on PostgreSQL.
3. top_k truncation on PostgreSQL.
4. Agreement between dense and lexical retrieval over active documents.
5. Metadata filters with pgvector execution on PostgreSQL.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.models import Document, DocumentChunk, ParseRun
from mamagift_retrieval.archive import (
    ArchiveFilter,
    ArchiveIndexStats,
)
from mamagift_retrieval.archive.constants import EMBEDDING_DIM
from mamagift_retrieval.archive.protocol import AUTHORITATIVE_FAMILY_ID
from mamagift_retrieval.archive.sql_archive_index import SqlArchiveIndex
from mamagift_retrieval.scope import EvidenceScope

NOW = datetime(2026, 8, 27, 12, 0, 0, tzinfo=UTC)


def _vec(prefix: list[float], dim: int = EMBEDDING_DIM) -> list[float]:
    """Pad a short float vector prefix to full EMBEDDING_DIM with zeros."""
    if len(prefix) > dim:
        raise ValueError(f"prefix length {len(prefix)} exceeds dimension {dim}")
    return prefix + [0.0] * (dim - len(prefix))


@pytest.fixture
def archive_scope() -> EvidenceScope:
    return EvidenceScope(
        family_id=AUTHORITATIVE_FAMILY_ID,
        archive_scope=True,
    )


def _seed_pg_document(
    session: Session,
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
    doc = Document(
        id=doc_id,
        filename=f"{doc_id}.pdf",
        content_type="application/pdf",
        byte_size=4096,
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
    session.flush()
    return doc


def _seed_pg_parse_run(
    session: Session,
    run_id: str,
    doc_id: str,
    *,
    version: int = 1,
    is_current: bool = True,
) -> ParseRun:
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
    session.flush()
    return prun


def _seed_pg_chunk(
    session: Session,
    chunk_id: str,
    doc_id: str,
    parse_run_id: str,
    *,
    doc_version: int = 1,
    chunk_index: int = 0,
    text: str = "Nội dung văn bản quy phạm pháp luật",
    embedding: list[float] | None = None,
    embedding_model: str | None = "bge-m3",
    embedding_version: str | None = "v1",
    section_path: list[str] | None = None,
) -> DocumentChunk:
    chunk = DocumentChunk(
        id=chunk_id,
        document_id=doc_id,
        parse_run_id=parse_run_id,
        document_version=doc_version,
        chunk_index=chunk_index,
        section_path=section_path or ["Điều 1. Phạm vi điều chỉnh"],
        page_numbers=[1],
        source_block_ids=[f"blk_{chunk_id}"],
        text=text,
        token_count=len(text.split()),
        embedding=embedding,
        embedding_model=embedding_model,
        embedding_version=embedding_version,
        created_at=NOW,
    )
    session.add(chunk)
    session.flush()
    return chunk


# ============================================================================
# 1. Real Cosine Distance Search on PostgreSQL via pgvector
# ============================================================================


def test_pgvector_dense_search_ordering(
    pg_session_factory: sessionmaker[Session],
    archive_scope: EvidenceScope,
) -> None:
    """Seed 3 current documents with 1024-dim embeddings; assert real cosine order and scores."""
    index = SqlArchiveIndex(pg_session_factory)

    # q: [1.0, 0.0, ...]
    # v1 (doc_1): identical to q -> angle 0, cos sim 1.0, score = 1.0
    # v2 (doc_2): angle 45 deg -> cos sim ~0.7071, score ~0.7071
    # v3 (doc_3): orthogonal -> angle 90 deg, cos sim 0.0, score = 0.0
    q = _vec([1.0, 0.0])
    v1 = _vec([1.0, 0.0])
    v2 = _vec([0.70710678, 0.70710678])
    v3 = _vec([0.0, 1.0])

    with pg_session_factory() as session:
        with session.begin():
            # Seed in non-sorted order: 3, 1, 2
            for doc_id, run_id, vec, doc_num in (
                ("doc_3", "run_3", v3, "03/2026/TT-BGDĐT"),
                ("doc_1", "run_1", v1, "01/2026/TT-BGDĐT"),
                ("doc_2", "run_2", v2, "02/2026/TT-BGDĐT"),
            ):
                _seed_pg_document(
                    session,
                    doc_id,
                    current_parse_run_id=run_id,
                    document_number=doc_num,
                    document_type="Thông tư",
                )
                _seed_pg_parse_run(session, run_id, doc_id, version=1, is_current=True)
                _seed_pg_chunk(
                    session,
                    f"c_{doc_id}",
                    doc_id,
                    run_id,
                    embedding=vec,
                    text=f"Nội dung quy định tại văn bản {doc_id}",
                )

    results = index.search_dense(archive_scope, q, top_k=10)
    assert len(results) == 3

    # Assert expected ordering
    doc_order = [r.chunk.document_id for r in results]
    assert doc_order == ["doc_1", "doc_2", "doc_3"]

    # Assert 1-based ranks
    assert [r.rank for r in results] == [1, 2, 3]
    assert all(r.retriever == "dense" for r in results)

    # Assert mathematical score precision
    assert pytest.approx(results[0].score, abs=1e-4) == 1.0
    assert pytest.approx(results[1].score, abs=1e-4) == 0.7071
    assert pytest.approx(results[2].score, abs=1e-4) == 0.0


# ============================================================================
# 2. Stale-Version Invariant on PostgreSQL
# ============================================================================


def test_pgvector_stale_version_excluded(
    pg_session_factory: sessionmaker[Session],
    archive_scope: EvidenceScope,
) -> None:
    """Document with v1 (is_current=False) and v2 (is_current=True) on PostgreSQL."""
    index = SqlArchiveIndex(pg_session_factory)
    doc_id = "doc_pg_stale"
    run_v1 = "run_pg_v1"
    run_v2 = "run_pg_v2"

    with pg_session_factory() as session:
        with session.begin():
            _seed_pg_document(
                session,
                doc_id,
                current_parse_run_id=run_v2,
                document_number="88/2026/NĐ-CP",
                document_type="Nghị định",
            )
            _seed_pg_parse_run(session, run_v1, doc_id, version=1, is_current=False)
            _seed_pg_parse_run(session, run_v2, doc_id, version=2, is_current=True)

            _seed_pg_chunk(
                session,
                "c_pg_v1",
                doc_id,
                run_v1,
                doc_version=1,
                text="Quy định cũ phiên bản 1",
                embedding=_vec([1.0, 0.0]),
            )
            _seed_pg_chunk(
                session,
                "c_pg_v2",
                doc_id,
                run_v2,
                doc_version=2,
                text="Quy định mới phiên bản 2",
                embedding=_vec([0.0, 1.0]),
            )

    # Dense search returns ONLY v2
    dense_res = index.search_dense(archive_scope, _vec([1.0, 0.0]), top_k=10)
    assert len(dense_res) == 1
    assert dense_res[0].chunk.chunk_id == "c_pg_v2"
    assert dense_res[0].chunk.document_version == 2
    assert dense_res[0].chunk.parse_run_id == run_v2

    # Current documents returns only v2
    docs = index.current_documents(archive_scope)
    assert len(docs) == 1
    assert docs[0].document_id == doc_id
    assert docs[0].parse_run_id == run_v2
    assert docs[0].document_version == 2

    # Stats returns only v2
    stats_res = index.stats(archive_scope)
    assert isinstance(stats_res, ArchiveIndexStats)
    assert stats_res.total_documents == 1
    assert stats_res.total_chunks == 1
    assert stats_res.embedded_chunks == 1


# ============================================================================
# 3. top_k Truncation on PostgreSQL
# ============================================================================


def test_pgvector_top_k_truncation(
    pg_session_factory: sessionmaker[Session],
    archive_scope: EvidenceScope,
) -> None:
    """top_k=2 returns exactly 2 rows from a 4-document collection on PostgreSQL."""
    index = SqlArchiveIndex(pg_session_factory)

    with pg_session_factory() as session:
        with session.begin():
            for i in range(1, 5):
                doc_id = f"doc_trunc_{i}"
                run_id = f"run_trunc_{i}"
                _seed_pg_document(
                    session,
                    doc_id,
                    current_parse_run_id=run_id,
                    document_number=f"{i}/2026/QĐ-UBND",
                )
                _seed_pg_parse_run(session, run_id, doc_id, version=1, is_current=True)
                _seed_pg_chunk(
                    session,
                    f"c_trunc_{i}",
                    doc_id,
                    run_id,
                    embedding=_vec([float(i) / 10.0, 1.0]),
                )

    results = index.search_dense(archive_scope, _vec([1.0, 0.0]), top_k=2)
    assert len(results) == 2
    assert [r.rank for r in results] == [1, 2]


# ============================================================================
# 4. Dense and Lexical Agreement on Active Documents
# ============================================================================


def test_dense_and_lexical_document_agreement(
    pg_session_factory: sessionmaker[Session],
    archive_scope: EvidenceScope,
) -> None:
    """Dense and lexical search find the same active current document set."""
    index = SqlArchiveIndex(pg_session_factory)

    with pg_session_factory() as session:
        with session.begin():
            for i in range(1, 4):
                doc_id = f"doc_agree_{i}"
                run_id = f"run_agree_{i}"
                _seed_pg_document(
                    session,
                    doc_id,
                    current_parse_run_id=run_id,
                    document_type="Quyết định",
                    document_number=f"{i}/2026/QĐ-UBND",
                )
                _seed_pg_parse_run(session, run_id, doc_id, version=1, is_current=True)
                _seed_pg_chunk(
                    session,
                    f"c_agree_{i}",
                    doc_id,
                    run_id,
                    text=f"Tiêu chuẩn đánh giá và xếp loại công chức viên chức số {i}",
                    embedding=_vec([1.0, float(i) * 0.1]),
                )

    dense_results = index.search_dense(archive_scope, _vec([1.0, 0.0]), top_k=10)
    lexical_results = index.search_lexical(archive_scope, "tiêu chuẩn đánh giá", top_k=10)

    dense_doc_ids = {r.chunk.document_id for r in dense_results}
    lexical_doc_ids = {r.chunk.document_id for r in lexical_results}

    assert dense_doc_ids == {"doc_agree_1", "doc_agree_2", "doc_agree_3"}
    assert lexical_doc_ids == {"doc_agree_1", "doc_agree_2", "doc_agree_3"}
    assert dense_doc_ids == lexical_doc_ids


# ============================================================================
# 5. Metadata Filters with pgvector on PostgreSQL
# ============================================================================


def test_pgvector_metadata_filters(
    pg_session_factory: sessionmaker[Session],
    archive_scope: EvidenceScope,
) -> None:
    """Verify ArchiveFilter combinations work with pgvector queries on PostgreSQL."""
    index = SqlArchiveIndex(pg_session_factory)

    with pg_session_factory() as session:
        with session.begin():
            # Doc 1: Matching
            _seed_pg_document(
                session,
                "doc_pg_f1",
                current_parse_run_id="run_pg_f1",
                document_type="Thông tư",
                document_number="19/2026/TT-BGDĐT",
                issuer="Bộ Giáo dục và Đào tạo",
                issued_date=date(2026, 3, 31),
                requires_user_review=False,
            )
            _seed_pg_parse_run(session, "run_pg_f1", "doc_pg_f1", version=1, is_current=True)
            _seed_pg_chunk(
                session,
                "c_pg_f1",
                "doc_pg_f1",
                "run_pg_f1",
                text="Tuyển sinh năm học mới",
                embedding=_vec([1.0, 0.0]),
            )

            # Doc 2: Different type
            _seed_pg_document(
                session,
                "doc_pg_f2",
                current_parse_run_id="run_pg_f2",
                document_type="Nghị định",
                document_number="20/2026/NĐ-CP",
                issuer="Chính phủ",
                issued_date=date(2026, 4, 15),
                requires_user_review=False,
            )
            _seed_pg_parse_run(session, "run_pg_f2", "doc_pg_f2", version=1, is_current=True)
            _seed_pg_chunk(
                session,
                "c_pg_f2",
                "doc_pg_f2",
                "run_pg_f2",
                text="Tuyển sinh quy định chung",
                embedding=_vec([0.9, 0.1]),
            )

    # 1. Filter by document_type and normalized document_number
    f1 = ArchiveFilter(
        document_types=["Thông tư"],
        document_numbers=[" 19 / 2026 / tt-bgdđt "],
    )
    dense_f1 = index.search_dense(archive_scope, _vec([1.0, 0.0]), top_k=10, filters=f1)
    assert len(dense_f1) == 1
    assert dense_f1[0].chunk.document_id == "doc_pg_f1"

    # 2. Filter by issuer (case-insensitive on Postgres)
    f2 = ArchiveFilter(issuers=["bộ giáo dục và đào tạo"])
    dense_f2 = index.search_dense(archive_scope, _vec([1.0, 0.0]), top_k=10, filters=f2)
    assert len(dense_f2) == 1
    assert dense_f2[0].chunk.document_id == "doc_pg_f1"

    # 3. Filter by date range
    f3 = ArchiveFilter(
        issued_date_from=date(2026, 4, 1),
        issued_date_to=date(2026, 4, 30),
    )
    dense_f3 = index.search_dense(archive_scope, _vec([1.0, 0.0]), top_k=10, filters=f3)
    assert len(dense_f3) == 1
    assert dense_f3[0].chunk.document_id == "doc_pg_f2"
