"""Unit tests for DocumentIndex protocol and SqlDocumentIndex implementation."""

from __future__ import annotations

import math

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db import Base
from app.models import Document
from mamagift_retrieval.chunk import Chunk, ChunkType
from mamagift_retrieval.index import (
    DocumentIndex,
    IndexEntry,
    IndexStats,
    SqlDocumentIndex,
)
from mamagift_retrieval.scope import EvidenceScope


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


def _seed_document(session_factory, doc_id: str) -> None:
    with session_factory() as session:
        with session.begin():
            existing = session.get(Document, doc_id)
            if not existing:
                doc = Document(
                    id=doc_id,
                    filename=f"{doc_id}.pdf",
                    content_type="application/pdf",
                    byte_size=1024,
                    checksum_sha256=f"hash_{doc_id}",
                    storage_uri=f"local://{doc_id}",
                )
                session.add(doc)


def _make_chunk(
    chunk_id: str,
    doc_id: str,
    parse_run_id: str,
    doc_version: int = 1,
    text: str = "Test chunk text",
    parent_chunk_id: str | None = None,
    section_path: list[str] | None = None,
) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        parent_chunk_id=parent_chunk_id,
        document_id=doc_id,
        parse_run_id=parse_run_id,
        document_version=doc_version,
        section_path=section_path or ["Điều 1. Phạm vi điều chỉnh"],
        chunk_type=ChunkType.LEGAL_ARTICLE,
        text=text,
        source_block_ids=[f"block_{chunk_id}"],
        source_page_numbers=[1],
        metadata={},
    )


def test_protocol_conformance(index: SqlDocumentIndex) -> None:
    assert isinstance(index, DocumentIndex)
    assert issubclass(SqlDocumentIndex, DocumentIndex)


def test_replace_and_stats(session_factory, index: SqlDocumentIndex) -> None:
    doc_id = "doc_stats_01"
    run_id = "run_stats_01"
    _seed_document(session_factory, doc_id)

    scope = EvidenceScope(
        family_id="fam_01",
        document_id=doc_id,
        document_version=1,
        parse_run_id=run_id,
    )

    c1 = _make_chunk("c1", doc_id, run_id, 1, text="Chunk một")
    c2 = _make_chunk("c2", doc_id, run_id, 1, text="Chunk hai")

    entries = [
        IndexEntry(
            chunk=c1,
            chunk_index=0,
            token_count=5,
            embedding=[0.1, 0.2, 0.3],
            embedding_model="bge-m3",
            embedding_version="v1",
        ),
        IndexEntry(
            chunk=c2,
            chunk_index=1,
            token_count=5,
            embedding=[0.4, 0.5, 0.6],
            embedding_model="bge-m3",
            embedding_version="v1",
        ),
    ]

    stats_result = index.replace(scope, entries)
    assert isinstance(stats_result, IndexStats)
    assert stats_result.document_id == doc_id
    assert stats_result.parse_run_id == run_id
    assert stats_result.document_version == 1
    assert stats_result.total_chunks == 2
    assert stats_result.embedded_chunks == 2
    assert stats_result.embedding_model == "bge-m3"
    assert stats_result.embedding_version == "v1"

    queried_stats = index.stats(scope)
    assert queried_stats == stats_result


def test_version_isolation_between_parse_runs(session_factory, index: SqlDocumentIndex) -> None:
    doc_id = "doc_isolation_01"
    _seed_document(session_factory, doc_id)

    scope_run1 = EvidenceScope(
        family_id="fam_01",
        document_id=doc_id,
        document_version=1,
        parse_run_id="run_01",
    )
    scope_run2 = EvidenceScope(
        family_id="fam_01",
        document_id=doc_id,
        document_version=2,
        parse_run_id="run_02",
    )

    c_run1 = _make_chunk("chunk_r1", doc_id, "run_01", 1, text="Alpha quy định cũ")
    c_run2 = _make_chunk("chunk_r2", doc_id, "run_02", 2, text="Beta quy định mới")

    index.replace(
        scope_run1,
        [
            IndexEntry(
                chunk=c_run1,
                chunk_index=0,
                embedding=[1.0, 0.0],
                embedding_model="bge-m3",
                embedding_version="v1",
            )
        ],
    )
    index.replace(
        scope_run2,
        [
            IndexEntry(
                chunk=c_run2,
                chunk_index=0,
                embedding=[0.0, 1.0],
                embedding_model="bge-m3",
                embedding_version="v1",
            )
        ],
    )

    # Dense search scoped to run 2 must NEVER return run 1 chunk
    dense_hits_r2 = index.search_dense(scope_run2, [1.0, 0.0], top_k=10)
    assert len(dense_hits_r2) == 1
    assert dense_hits_r2[0].chunk.parse_run_id == "run_02"
    assert dense_hits_r2[0].chunk.chunk_id == "chunk_r2"
    assert dense_hits_r2[0].score == 0.0

    # Dense search scoped to run 1 must NEVER return run 2 chunk
    dense_hits_r1 = index.search_dense(scope_run1, [1.0, 0.0], top_k=10)
    assert len(dense_hits_r1) == 1
    assert dense_hits_r1[0].chunk.parse_run_id == "run_01"
    assert dense_hits_r1[0].chunk.chunk_id == "chunk_r1"
    assert math.isclose(dense_hits_r1[0].score, 1.0)

    # Lexical search scoped to run 2 searching for run 1 keyword returns nothing
    lex_hits_r2 = index.search_lexical(scope_run2, "Alpha", top_k=10)
    assert len(lex_hits_r2) == 0

    # Lexical search scoped to run 1 searching for run 2 keyword returns nothing
    lex_hits_r1 = index.search_lexical(scope_run1, "Beta", top_k=10)
    assert len(lex_hits_r1) == 0


def test_cross_document_isolation(session_factory, index: SqlDocumentIndex) -> None:
    doc_a = "doc_cross_a"
    doc_b = "doc_cross_b"
    _seed_document(session_factory, doc_a)
    _seed_document(session_factory, doc_b)

    scope_a = EvidenceScope(family_id="fam_01", document_id=doc_a, parse_run_id="run_a")
    scope_b = EvidenceScope(family_id="fam_01", document_id=doc_b, parse_run_id="run_b")

    ca = _make_chunk("ca", doc_a, "run_a", 1, text="Văn bản A bí mật")
    cb = _make_chunk("cb", doc_b, "run_b", 1, text="Văn bản B công khai")

    index.replace(
        scope_a,
        [IndexEntry(chunk=ca, chunk_index=0, embedding=[1.0, 0.0], embedding_version="v1")],
    )
    index.replace(
        scope_b,
        [IndexEntry(chunk=cb, chunk_index=0, embedding=[1.0, 0.0], embedding_version="v1")],
    )

    hits_a_dense = index.search_dense(scope_a, [1.0, 0.0], top_k=10)
    assert len(hits_a_dense) == 1
    assert hits_a_dense[0].chunk.document_id == doc_a

    hits_a_lex = index.search_lexical(scope_a, "công khai", top_k=10)
    assert len(hits_a_lex) == 0

    hits_b_dense = index.search_dense(scope_b, [1.0, 0.0], top_k=10)
    assert len(hits_b_dense) == 1
    assert hits_b_dense[0].chunk.document_id == doc_b

    hits_b_lex = index.search_lexical(scope_b, "bí mật", top_k=10)
    assert len(hits_b_lex) == 0


def test_entry_provenance_contradiction_rejected(session_factory, index: SqlDocumentIndex) -> None:
    doc_id = "doc_contradict"
    _seed_document(session_factory, doc_id)

    scope = EvidenceScope(
        family_id="fam_01",
        document_id=doc_id,
        document_version=1,
        parse_run_id="run_01",
    )

    # Document ID contradiction
    c_wrong_doc = _make_chunk("c1", "other_doc", "run_01", 1)
    with pytest.raises(ValueError, match="contradicts scope document_id"):
        index.replace(scope, [IndexEntry(chunk=c_wrong_doc, chunk_index=0)])

    # Parse run ID contradiction
    c_wrong_run = _make_chunk("c2", doc_id, "other_run", 1)
    with pytest.raises(ValueError, match="contradicts scope parse_run_id"):
        index.replace(scope, [IndexEntry(chunk=c_wrong_run, chunk_index=0)])

    # Version contradiction
    c_wrong_ver = _make_chunk("c3", doc_id, "run_01", 2)
    with pytest.raises(ValueError, match="contradicts scope document_version"):
        index.replace(scope, [IndexEntry(chunk=c_wrong_ver, chunk_index=0)])


def test_replace_is_atomic_and_leaves_other_runs_untouched(
    session_factory, index: SqlDocumentIndex
) -> None:
    doc_id = "doc_atomic_01"
    _seed_document(session_factory, doc_id)

    scope_r1 = EvidenceScope(family_id="fam_01", document_id=doc_id, parse_run_id="run_01")
    scope_r2 = EvidenceScope(family_id="fam_01", document_id=doc_id, parse_run_id="run_02")

    c1_1 = _make_chunk("c1_1", doc_id, "run_01", 1, text="r1 chunk 1")
    c1_2 = _make_chunk("c1_2", doc_id, "run_01", 1, text="r1 chunk 2")

    c2_1 = _make_chunk("c2_1", doc_id, "run_02", 2, text="r2 chunk 1")
    c2_2 = _make_chunk("c2_2", doc_id, "run_02", 2, text="r2 chunk 2")
    c2_3 = _make_chunk("c2_3", doc_id, "run_02", 2, text="r2 chunk 3")

    index.replace(
        scope_r1,
        [
            IndexEntry(chunk=c1_1, chunk_index=0, embedding=[1.0, 0.0], embedding_version="v1"),
            IndexEntry(chunk=c1_2, chunk_index=1, embedding=[0.0, 1.0], embedding_version="v1"),
        ],
    )
    index.replace(
        scope_r2,
        [
            IndexEntry(chunk=c2_1, chunk_index=0, embedding=[1.0, 0.0], embedding_version="v1"),
            IndexEntry(chunk=c2_2, chunk_index=1, embedding=[0.0, 1.0], embedding_version="v1"),
            IndexEntry(chunk=c2_3, chunk_index=2, embedding=[0.5, 0.5], embedding_version="v1"),
        ],
    )

    assert index.stats(scope_r1).total_chunks == 2
    assert index.stats(scope_r2).total_chunks == 3

    # Reindexing run 1 with only 1 chunk
    c1_new = _make_chunk("c1_new", doc_id, "run_01", 1, text="r1 updated")
    index.replace(
        scope_r1,
        [IndexEntry(chunk=c1_new, chunk_index=0, embedding=[1.0, 1.0], embedding_version="v1")],
    )

    assert index.stats(scope_r1).total_chunks == 1
    assert index.stats(scope_r2).total_chunks == 3

    # Failed replace due to duplicate chunk_index must roll back and preserve old state
    with pytest.raises(ValueError, match="duplicate chunk_index"):
        index.replace(
            scope_r1,
            [
                IndexEntry(chunk=c1_1, chunk_index=0),
                IndexEntry(chunk=c1_2, chunk_index=0),
            ],
        )

    # run 1 still has 1 chunk after rollback
    assert index.stats(scope_r1).total_chunks == 1


def test_drop_removes_only_scoped_rows(session_factory, index: SqlDocumentIndex) -> None:
    doc1 = "doc_drop_01"
    doc2 = "doc_drop_02"
    _seed_document(session_factory, doc1)
    _seed_document(session_factory, doc2)

    scope1_r1 = EvidenceScope(family_id="fam", document_id=doc1, parse_run_id="d1_r1")
    scope1_r2 = EvidenceScope(family_id="fam", document_id=doc1, parse_run_id="d1_r2")
    scope2_r1 = EvidenceScope(family_id="fam", document_id=doc2, parse_run_id="d2_r1")

    index.replace(
        scope1_r1,
        [IndexEntry(chunk=_make_chunk("d1r1_1", doc1, "d1_r1"), chunk_index=0)],
    )
    index.replace(
        scope1_r2,
        [IndexEntry(chunk=_make_chunk("d1r2_1", doc1, "d1_r2"), chunk_index=0)],
    )
    index.replace(
        scope2_r1,
        [IndexEntry(chunk=_make_chunk("d2r1_1", doc2, "d2_r1"), chunk_index=0)],
    )

    deleted = index.drop(scope1_r1)
    assert deleted == 1

    assert index.stats(scope1_r1).total_chunks == 0
    assert index.stats(scope1_r2).total_chunks == 1
    assert index.stats(scope2_r1).total_chunks == 1


def test_dense_search_exact_cosine_ordering(session_factory, index: SqlDocumentIndex) -> None:
    doc_id = "doc_cosine"
    _seed_document(session_factory, doc_id)

    scope = EvidenceScope(family_id="fam", document_id=doc_id, parse_run_id="r1")

    # query = [1.0, 0.0, 0.0]
    # ca: [1.0, 0.0, 0.0] -> 1.0
    # cb: [1.0, 1.0, 0.0] -> 1 / sqrt(2) ≈ 0.7071
    # cc: [0.0, 1.0, 0.0] -> 0.0
    # cd: [-1.0, 0.0, 0.0] -> -1.0
    ca = _make_chunk("ca", doc_id, "r1", text="Chunk A")
    cb = _make_chunk("cb", doc_id, "r1", text="Chunk B")
    cc = _make_chunk("cc", doc_id, "r1", text="Chunk C")
    cd = _make_chunk("cd", doc_id, "r1", text="Chunk D")

    entries = [
        IndexEntry(chunk=ca, chunk_index=0, embedding=[1.0, 0.0, 0.0], embedding_version="v1"),
        IndexEntry(chunk=cb, chunk_index=1, embedding=[1.0, 1.0, 0.0], embedding_version="v1"),
        IndexEntry(chunk=cc, chunk_index=2, embedding=[0.0, 1.0, 0.0], embedding_version="v1"),
        IndexEntry(chunk=cd, chunk_index=3, embedding=[-1.0, 0.0, 0.0], embedding_version="v1"),
    ]
    index.replace(scope, entries)

    results = index.search_dense(scope, [1.0, 0.0, 0.0], top_k=4)
    assert len(results) == 4

    assert results[0].chunk.chunk_id == "ca"
    assert results[0].rank == 1
    assert results[0].retriever == "dense"
    assert math.isclose(results[0].score, 1.0, rel_tol=1e-5)

    assert results[1].chunk.chunk_id == "cb"
    assert results[1].rank == 2
    assert results[1].retriever == "dense"
    assert math.isclose(results[1].score, 1.0 / math.sqrt(2.0), rel_tol=1e-5)

    assert results[2].chunk.chunk_id == "cc"
    assert results[2].rank == 3
    assert results[2].retriever == "dense"
    assert math.isclose(results[2].score, 0.0, abs_tol=1e-5)

    assert results[3].chunk.chunk_id == "cd"
    assert results[3].rank == 4
    assert results[3].retriever == "dense"
    assert math.isclose(results[3].score, -1.0, rel_tol=1e-5)

    # top_k limit
    top2 = index.search_dense(scope, [1.0, 0.0, 0.0], top_k=2)
    assert [r.chunk.chunk_id for r in top2] == ["ca", "cb"]
    assert [r.rank for r in top2] == [1, 2]


def test_stale_embedding_version_exclusion(session_factory, index: SqlDocumentIndex) -> None:
    doc_id = "doc_stale_emb"
    _seed_document(session_factory, doc_id)

    scope = EvidenceScope(family_id="fam", document_id=doc_id, parse_run_id="r1")

    c1 = _make_chunk("c1", doc_id, "r1", text="Chunk v1")
    c2 = _make_chunk("c2", doc_id, "r1", text="Chunk v2")

    entries = [
        IndexEntry(chunk=c1, chunk_index=0, embedding=[1.0, 0.0], embedding_version="bge-m3-v1"),
        IndexEntry(chunk=c2, chunk_index=1, embedding=[1.0, 0.0], embedding_version="bge-m3-v2"),
    ]
    index.replace(scope, entries)

    # Searching with embedding_version="bge-m3-v2" excludes v1
    v2_results = index.search_dense(scope, [1.0, 0.0], top_k=10, embedding_version="bge-m3-v2")
    assert len(v2_results) == 1
    assert v2_results[0].chunk.chunk_id == "c2"

    # Searching with embedding_version="bge-m3-v1" excludes v2
    v1_results = index.search_dense(scope, [1.0, 0.0], top_k=10, embedding_version="bge-m3-v1")
    assert len(v1_results) == 1
    assert v1_results[0].chunk.chunk_id == "c1"

    # Searching with unknown version excludes all
    v3_results = index.search_dense(scope, [1.0, 0.0], top_k=10, embedding_version="bge-m3-v3")
    assert len(v3_results) == 0


def test_missing_embedding_handling(session_factory, index: SqlDocumentIndex) -> None:
    doc_id = "doc_no_emb"
    _seed_document(session_factory, doc_id)

    scope = EvidenceScope(family_id="fam", document_id=doc_id, parse_run_id="r1")

    c_with = _make_chunk("c_with", doc_id, "r1", text="Văn bản quy định")
    c_without = _make_chunk("c_without", doc_id, "r1", text="Văn bản hướng dẫn")

    entries = [
        IndexEntry(chunk=c_with, chunk_index=0, embedding=[1.0, 0.0], embedding_version="v1"),
        IndexEntry(chunk=c_without, chunk_index=1, embedding=None, embedding_version=None),
    ]
    index.replace(scope, entries)

    dense_results = index.search_dense(scope, [1.0, 0.0], top_k=10)
    assert len(dense_results) == 1
    assert dense_results[0].chunk.chunk_id == "c_with"

    lex_results = index.search_lexical(scope, "hướng dẫn", top_k=10)
    assert len(lex_results) == 1
    assert lex_results[0].chunk.chunk_id == "c_without"
    assert lex_results[0].retriever == "lexical"
    assert lex_results[0].rank == 1


def test_dense_search_dimension_mismatch_raises(session_factory, index: SqlDocumentIndex) -> None:
    doc_id = "doc_dim_err"
    _seed_document(session_factory, doc_id)

    scope = EvidenceScope(family_id="fam", document_id=doc_id, parse_run_id="r1")
    c = _make_chunk("c1", doc_id, "r1")
    index.replace(
        scope,
        [IndexEntry(chunk=c, chunk_index=0, embedding=[1.0, 0.0, 0.0], embedding_version="v1")],
    )

    with pytest.raises(ValueError, match="vector dimension mismatch"):
        index.search_dense(scope, [1.0, 0.0], top_k=5)


def test_lexical_search_scoring_and_ranking(session_factory, index: SqlDocumentIndex) -> None:
    doc_id = "doc_lex_score"
    _seed_document(session_factory, doc_id)

    scope = EvidenceScope(family_id="fam", document_id=doc_id, parse_run_id="r1")

    c1 = _make_chunk("c1", doc_id, "r1", text="Nghị định quy định chi tiết thi hành luật")
    c2 = _make_chunk("c2", doc_id, "r1", text="Nghị định quy định một số điều")
    c3 = _make_chunk("c3", doc_id, "r1", text="Thông tư hướng dẫn thi hành luật")

    index.replace(
        scope,
        [
            IndexEntry(chunk=c1, chunk_index=0),
            IndexEntry(chunk=c2, chunk_index=1),
            IndexEntry(chunk=c3, chunk_index=2),
        ],
    )

    # Query: "Nghị định quy định chi tiết thi hành" (unique tokens: 7)
    # c1 has 7/7 tokens = 1.0
    # c2 has 3/7 tokens ≈ 0.42857
    # c3 has 2/7 tokens ≈ 0.28571
    results = index.search_lexical(scope, "Nghị định quy định chi tiết thi hành", top_k=10)
    assert len(results) == 3
    assert [r.chunk.chunk_id for r in results] == ["c1", "c2", "c3"]
    assert [r.rank for r in results] == [1, 2, 3]
    assert math.isclose(results[0].score, 1.0)
    assert math.isclose(results[1].score, 3.0 / 7.0)
    assert math.isclose(results[2].score, 2.0 / 7.0)


def test_empty_lexical_query_returns_empty(session_factory, index: SqlDocumentIndex) -> None:
    doc_id = "doc_empty_q"
    _seed_document(session_factory, doc_id)

    scope = EvidenceScope(family_id="fam", document_id=doc_id, parse_run_id="r1")
    c = _make_chunk("c1", doc_id, "r1", text="Một số nội dung")
    index.replace(scope, [IndexEntry(chunk=c, chunk_index=0)])

    assert index.search_lexical(scope, "   ", top_k=5) == []
    assert index.search_lexical(scope, "!@#$%^", top_k=5) == []


def test_invalid_inputs_raise(session_factory, index: SqlDocumentIndex) -> None:
    doc_id = "doc_invalid_inputs"
    _seed_document(session_factory, doc_id)

    scope = EvidenceScope(family_id="fam", document_id=doc_id, parse_run_id="r1")
    scope_no_doc = EvidenceScope(family_id="fam", parse_run_id="r1")
    scope_no_run = EvidenceScope(family_id="fam", document_id=doc_id)

    c = _make_chunk("c1", doc_id, "r1")

    # top_k <= 0
    with pytest.raises(ValueError, match="top_k must be a positive integer"):
        index.search_dense(scope, [1.0, 0.0], top_k=0)
    with pytest.raises(ValueError, match="top_k must be a positive integer"):
        index.search_lexical(scope, "query", top_k=-1)

    # Empty query vector
    with pytest.raises(ValueError, match="query_vector cannot be empty"):
        index.search_dense(scope, [], top_k=5)

    # Missing document_id in scope
    with pytest.raises(ValueError, match="scope must specify document_id"):
        index.replace(scope_no_doc, [IndexEntry(chunk=c, chunk_index=0)])
    with pytest.raises(ValueError, match="scope must specify document_id"):
        index.search_dense(scope_no_doc, [1.0, 0.0], top_k=5)
    with pytest.raises(ValueError, match="scope must specify document_id"):
        index.search_lexical(scope_no_doc, "query", top_k=5)
    with pytest.raises(ValueError, match="scope must specify document_id"):
        index.drop(scope_no_doc)
    with pytest.raises(ValueError, match="scope must specify document_id"):
        index.stats(scope_no_doc)

    # Missing parse_run_id in replace
    with pytest.raises(ValueError, match="scope must specify parse_run_id"):
        index.replace(scope_no_run, [IndexEntry(chunk=c, chunk_index=0)])


def test_chunk_tree_validation_in_replace(session_factory, index: SqlDocumentIndex) -> None:
    doc_id = "doc_tree_val"
    _seed_document(session_factory, doc_id)

    scope = EvidenceScope(family_id="fam", document_id=doc_id, parse_run_id="r1")

    # Chunk referencing non-existent parent
    c_orphan = _make_chunk("c_child", doc_id, "r1", parent_chunk_id="non_existent_parent")
    with pytest.raises(ValueError, match="references unknown parent"):
        index.replace(scope, [IndexEntry(chunk=c_orphan, chunk_index=0)])


def test_session_types_support(db_engine, session_factory) -> None:
    doc_id = "doc_session_types"
    _seed_document(session_factory, doc_id)
    scope = EvidenceScope(family_id="fam", document_id=doc_id, parse_run_id="r1")
    c = _make_chunk("c1", doc_id, "r1", text="Test session types")
    entry = IndexEntry(chunk=c, chunk_index=0)

    # 1. sessionmaker
    idx1 = SqlDocumentIndex(session_factory)
    idx1.replace(scope, [entry])
    assert idx1.stats(scope).total_chunks == 1

    # 2. Engine
    idx2 = SqlDocumentIndex(db_engine)
    assert idx2.stats(scope).total_chunks == 1

    # 3. Session directly
    with Session(db_engine) as sess:
        idx3 = SqlDocumentIndex(sess)
        assert idx3.stats(scope).total_chunks == 1

    # 4. Custom callable factory
    idx4 = SqlDocumentIndex(lambda: Session(db_engine))
    assert idx4.stats(scope).total_chunks == 1
