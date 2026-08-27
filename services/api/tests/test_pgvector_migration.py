"""Tests for Alembic migration 0005_phase5_pgvector.

Verifies:
1. Empty database upgrade: `upgrade head` from base on empty PG succeeds and creates
   document_chunks.embedding as vector(1024).
2. Phase 4 data preservation: documents, parse_runs (including canonical JSON byte-for-byte),
   and document_chunks text/metadata survive; embedding/version/model are set to NULL.
3. Reindex is triggered: after migration, SqlDocumentIndex.stats() + needs_reindex()
   returns True for FakeEmbeddingProvider.
4. Round trip through the ORM: insert and read back a 1024-float vector via SQLAlchemy ORM.
5. Downgrade: downgrade to 0004_phase4_chunk_index restores JSON; downgrade to base succeeds.
6. SQLite still works: upgrade head then downgrade base succeed on SQLite.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
from alembic.config import Config
from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.orm import Session

from alembic import command
from app.indexing import needs_reindex
from app.models import Document, DocumentChunk, ParseRun
from app.vector_type import EMBEDDING_DIM
from mamagift_retrieval.index import SqlDocumentIndex
from mamagift_retrieval.providers import FakeEmbeddingProvider
from mamagift_retrieval.scope import EvidenceScope

REPO_ROOT = Path(__file__).resolve().parents[3]
ALEMBIC_INI = str(REPO_ROOT / "services" / "api" / "alembic.ini")


def _get_pg_database_url() -> str:
    """Return verified PostgreSQL database URL or skip if unset/unreachable."""
    raw_url = os.environ.get("MAMAGIFT_TEST_DATABASE_URL")
    if not raw_url or not raw_url.strip():
        pytest.skip(
            "MAMAGIFT_TEST_DATABASE_URL is not set; "
            "PostgreSQL+pgvector integration tests are skipped"
        )

    url = raw_url.strip()
    if not url.startswith("postgresql+psycopg://"):
        pytest.skip(
            f"MAMAGIFT_TEST_DATABASE_URL must start with 'postgresql+psycopg://', got: {url}"
        )

    temp_engine = create_engine(url, future=True)
    try:
        with temp_engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:
        pytest.skip(f"MAMAGIFT_TEST_DATABASE_URL is set but PostgreSQL is unreachable: {exc}")
    finally:
        temp_engine.dispose()

    return url


@pytest.fixture
def pg_alembic_config(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[Config, Engine]]:
    """Yield an Alembic config and Engine bound to the PostgreSQL test database at base."""
    url = _get_pg_database_url()
    monkeypatch.setenv("DATABASE_URL", url)
    config = Config(ALEMBIC_INI)

    engine = create_engine(url, future=True)
    try:
        # Start from clean base
        command.downgrade(config, "base")
        yield config, engine
    finally:
        try:
            command.downgrade(config, "base")
        except Exception:
            pass
        engine.dispose()


def _insert_phase4_document(
    conn: Any,
    doc_id: str = "doc_p4",
    filename: str = "quy_che.pdf",
    checksum: str = "sha256_p4_checksum",
) -> dict[str, Any]:
    now = datetime.now(UTC)
    doc_data = {
        "id": doc_id,
        "filename": filename,
        "content_type": "application/pdf",
        "byte_size": 10240,
        "checksum_sha256": checksum,
        "storage_uri": f"local://storage/{doc_id}",
        "status": "READY",
        "document_type": "Quyết định",
        "document_number": "123/QĐ-UBND",
        "title": "Quy chế tuyển sinh",
        "issuer": "UBND TP Hà Nội",
        "issued_date": date(2026, 3, 15),
        "signer": "Nguyễn Văn A",
        "deadline": date(2026, 4, 30),
        "current_parse_run_id": "prun_p4",
        "requires_user_review": False,
        "error_code": None,
        "error_message": None,
        "created_at": now,
        "updated_at": now,
    }
    conn.execute(
        text(
            "INSERT INTO documents (id, filename, content_type, byte_size, "
            "checksum_sha256, storage_uri, status, document_type, document_number, "
            "title, issuer, issued_date, signer, deadline, current_parse_run_id, "
            "requires_user_review, error_code, error_message, created_at, updated_at) "
            "VALUES (:id, :filename, :content_type, :byte_size, :checksum_sha256, "
            ":storage_uri, :status, :document_type, :document_number, :title, "
            ":issuer, :issued_date, :signer, :deadline, :current_parse_run_id, "
            ":requires_user_review, :error_code, :error_message, :created_at, :updated_at)"
        ),
        doc_data,
    )
    return doc_data


def _insert_phase4_parse_run(
    conn: Any,
    run_id: str = "prun_p4",
    doc_id: str = "doc_p4",
    version: int = 1,
) -> dict[str, Any]:
    now = datetime.now(UTC)
    canonical = {
        "document_id": doc_id,
        "document_type": "Quyết định",
        "document_number": "123/QĐ-UBND",
        "title": "Quy chế tuyển sinh",
        "sections": [
            {
                "id": "sec_1",
                "title": "Điều 1",
                "blocks": ["b1", "b2"],
            }
        ],
    }
    inspection = {"quality_score": 0.95, "dpi": 300}
    quality_report = {"valid": True, "issues": []}

    prun_data = {
        "id": run_id,
        "document_id": doc_id,
        "job_id": None,
        "version": version,
        "is_current": True,
        "parser_name": "pymupdf",
        "parser_version": "1.0",
        "configuration_hash": "hash_p4_123",
        "strategy_decided": True,
        "degraded": False,
        "route": "born_digital",
        "schema_version": "1.0",
        "canonical": canonical,
        "inspection": inspection,
        "quality_report": quality_report,
        "started_at": now,
        "finished_at": now,
        "created_at": now,
    }
    conn.execute(
        text(
            "INSERT INTO parse_runs (id, document_id, job_id, version, is_current, "
            "parser_name, parser_version, configuration_hash, strategy_decided, "
            "degraded, route, schema_version, canonical, inspection, quality_report, "
            "started_at, finished_at, created_at) VALUES (:id, :document_id, :job_id, "
            ":version, :is_current, :parser_name, :parser_version, :configuration_hash, "
            ":strategy_decided, :degraded, :route, :schema_version, :canonical, "
            ":inspection, :quality_report, :started_at, :finished_at, :created_at)"
        ),
        {
            **prun_data,
            "canonical": json.dumps(canonical),
            "inspection": json.dumps(inspection),
            "quality_report": json.dumps(quality_report),
        },
    )
    return prun_data


def _insert_phase4_chunks(conn: Any) -> list[dict[str, Any]]:
    now = datetime.now(UTC)
    chunks_data = [
        {
            "id": "chunk_p4_0",
            "document_id": "doc_p4",
            "parse_run_id": "prun_p4",
            "document_version": 1,
            "chunk_index": 0,
            "parent_chunk_id": None,
            "section_path": ["Điều 1"],
            "page_numbers": [1],
            "source_block_ids": ["b1"],
            "text": "Nội dung điều 1 về quy chế tuyển sinh năm học 2026.",
            "token_count": 18,
            "embedding": [0.1, 0.2, 0.3],
            "embedding_model": "bge-m3",
            "embedding_version": "v1",
            "created_at": now,
        },
        {
            "id": "chunk_p4_1",
            "document_id": "doc_p4",
            "parse_run_id": "prun_p4",
            "document_version": 1,
            "chunk_index": 1,
            "parent_chunk_id": "chunk_p4_0",
            "section_path": ["Điều 1", "Khoản 1"],
            "page_numbers": [1, 2],
            "source_block_ids": ["b2", "b3"],
            "text": "Chi tiết đối tượng tuyển sinh bao gồm các học sinh trung học.",
            "token_count": 22,
            "embedding": [0.4, 0.5, 0.6],
            "embedding_model": "bge-m3",
            "embedding_version": "v1",
            "created_at": now,
        },
    ]
    for chunk in chunks_data:
        conn.execute(
            text(
                "INSERT INTO document_chunks (id, document_id, parse_run_id, "
                "document_version, chunk_index, parent_chunk_id, section_path, "
                "page_numbers, source_block_ids, text, token_count, embedding, "
                "embedding_model, embedding_version, created_at) VALUES "
                "(:id, :document_id, :parse_run_id, :document_version, :chunk_index, "
                ":parent_chunk_id, :section_path, :page_numbers, :source_block_ids, "
                ":text, :token_count, :embedding, :embedding_model, :embedding_version, "
                ":created_at)"
            ),
            {
                **chunk,
                "section_path": json.dumps(chunk["section_path"]),
                "page_numbers": json.dumps(chunk["page_numbers"]),
                "source_block_ids": json.dumps(chunk["source_block_ids"]),
                "embedding": json.dumps(chunk["embedding"]),
            },
        )
    return chunks_data


def test_empty_database_upgrade_pg(pg_alembic_config: tuple[Config, Engine]) -> None:
    """Case 1: upgrade head from base creates document_chunks.embedding as vector(1024)."""
    config, engine = pg_alembic_config
    command.upgrade(config, "head")

    inspector = inspect(engine)
    assert "document_chunks" in inspector.get_table_names()

    with engine.connect() as conn:
        col_type = conn.execute(
            text(
                "SELECT format_type(atttypid, atttypmod) AS col_type "
                "FROM pg_attribute "
                "WHERE attrelid = 'document_chunks'::regclass AND attname = 'embedding'"
            )
        ).scalar()
        assert col_type == f"vector({EMBEDDING_DIM})"

        udt_name = conn.execute(
            text(
                "SELECT udt_name FROM information_schema.columns "
                "WHERE table_name = 'document_chunks' AND column_name = 'embedding'"
            )
        ).scalar()
        assert udt_name == "vector"


def test_phase4_data_preservation_pg(pg_alembic_config: tuple[Config, Engine]) -> None:
    """Case 2: Phase 4 data (documents, parse_runs, chunks metadata) preserved across upgrade."""
    config, engine = pg_alembic_config

    # Step 1: Upgrade to Phase 4 schema only
    command.upgrade(config, "0004_phase4_chunk_index")

    # Step 2: Seed real document, parse_run, and chunks with JSON embeddings
    with engine.begin() as conn:
        doc_before = _insert_phase4_document(conn)
        prun_before = _insert_phase4_parse_run(conn)
        chunks_before = _insert_phase4_chunks(conn)

    # Step 3: Upgrade to head (applies 0005_phase5_pgvector)
    command.upgrade(config, "head")

    # Step 4: Verify data preservation
    with engine.connect() as conn:
        # Check documents row field by field
        doc_row = conn.execute(text("SELECT * FROM documents WHERE id = 'doc_p4'")).mappings().one()

        assert doc_row["filename"] == doc_before["filename"]
        assert doc_row["content_type"] == doc_before["content_type"]
        assert doc_row["byte_size"] == doc_before["byte_size"]
        assert doc_row["checksum_sha256"] == doc_before["checksum_sha256"]
        assert doc_row["storage_uri"] == doc_before["storage_uri"]
        assert doc_row["status"] == doc_before["status"]
        assert doc_row["document_type"] == doc_before["document_type"]
        assert doc_row["document_number"] == doc_before["document_number"]
        assert doc_row["title"] == doc_before["title"]
        assert doc_row["issuer"] == doc_before["issuer"]
        assert doc_row["issued_date"] == doc_before["issued_date"]
        assert doc_row["signer"] == doc_before["signer"]
        assert doc_row["deadline"] == doc_before["deadline"]
        assert doc_row["current_parse_run_id"] == doc_before["current_parse_run_id"]
        assert doc_row["requires_user_review"] == doc_before["requires_user_review"]

        # Check parse_runs row, including canonical JSON payload
        prun_row = (
            conn.execute(text("SELECT * FROM parse_runs WHERE id = 'prun_p4'")).mappings().one()
        )

        assert prun_row["document_id"] == prun_before["document_id"]
        assert prun_row["version"] == prun_before["version"]
        assert prun_row["is_current"] == prun_before["is_current"]
        assert prun_row["parser_name"] == prun_before["parser_name"]
        assert prun_row["parser_version"] == prun_before["parser_version"]
        assert prun_row["configuration_hash"] == prun_before["configuration_hash"]
        assert prun_row["strategy_decided"] == prun_before["strategy_decided"]
        assert prun_row["degraded"] == prun_before["degraded"]
        assert prun_row["route"] == prun_before["route"]
        assert prun_row["schema_version"] == prun_before["schema_version"]

        # Parse canonical JSON byte-for-byte / struct-for-struct
        canonical_val = prun_row["canonical"]
        if isinstance(canonical_val, str):
            canonical_val = json.loads(canonical_val)
        assert canonical_val == prun_before["canonical"]

        inspection_val = prun_row["inspection"]
        if isinstance(inspection_val, str):
            inspection_val = json.loads(inspection_val)
        assert inspection_val == prun_before["inspection"]

        quality_report_val = prun_row["quality_report"]
        if isinstance(quality_report_val, str):
            quality_report_val = json.loads(quality_report_val)
        assert quality_report_val == prun_before["quality_report"]

        # Check document_chunks rows
        chunk_rows = (
            conn.execute(
                text(
                    "SELECT * FROM document_chunks "
                    "WHERE document_id = 'doc_p4' ORDER BY chunk_index ASC"
                )
            )
            .mappings()
            .all()
        )

        assert len(chunk_rows) == 2
        for row, before in zip(chunk_rows, chunks_before, strict=True):
            assert row["id"] == before["id"]
            assert row["document_id"] == before["document_id"]
            assert row["parse_run_id"] == before["parse_run_id"]
            assert row["document_version"] == before["document_version"]
            assert row["chunk_index"] == before["chunk_index"]
            assert row["parent_chunk_id"] == before["parent_chunk_id"]
            assert row["text"] == before["text"]
            assert row["token_count"] == before["token_count"]

            sec_path = (
                row["section_path"]
                if isinstance(row["section_path"], list)
                else json.loads(row["section_path"])
            )
            assert sec_path == before["section_path"]

            page_nums = (
                row["page_numbers"]
                if isinstance(row["page_numbers"], list)
                else json.loads(row["page_numbers"])
            )
            assert page_nums == before["page_numbers"]

            source_blocks = (
                row["source_block_ids"]
                if isinstance(row["source_block_ids"], list)
                else json.loads(row["source_block_ids"])
            )
            assert source_blocks == before["source_block_ids"]

            # Vectors and metadata are wiped by migration
            assert row["embedding"] is None
            assert row["embedding_version"] is None
            assert row["embedding_model"] is None


def test_reindex_triggered_after_migration_pg(pg_alembic_config: tuple[Config, Engine]) -> None:
    """Case 3: needs_reindex() returns True after migration to ensure re-embedding occurs."""
    config, engine = pg_alembic_config

    command.upgrade(config, "0004_phase4_chunk_index")
    with engine.begin() as conn:
        _insert_phase4_document(conn)
        _insert_phase4_parse_run(conn)
        _insert_phase4_chunks(conn)

    command.upgrade(config, "head")

    scope = EvidenceScope(
        family_id="mamagift",
        document_id="doc_p4",
        document_version=1,
        parse_run_id="prun_p4",
    )
    with Session(engine) as session:
        sql_index = SqlDocumentIndex(session)
        stats = sql_index.stats(scope)
        assert stats.total_chunks == 2
        assert stats.embedded_chunks == 0
        assert stats.embedding_version is None

        provider = FakeEmbeddingProvider(model_id="bge-m3", embedding_version="bge-m3-v1")
        assert needs_reindex(stats, provider) is True


def test_orm_round_trip_vector_pg(pg_alembic_config: tuple[Config, Engine]) -> None:
    """Case 4: Round trip 1024-float vector through SQLAlchemy ORM on PostgreSQL."""
    config, engine = pg_alembic_config
    command.upgrade(config, "head")

    now = datetime.now(UTC)
    vector_1024 = [float(i) * 0.001 for i in range(EMBEDDING_DIM)]

    with Session(engine) as session:
        doc = Document(
            id="doc_vec_test",
            filename="vec.pdf",
            content_type="application/pdf",
            byte_size=2048,
            checksum_sha256="sha256_vec_test",
            storage_uri="local://storage/vec",
            status="READY",
            created_at=now,
            updated_at=now,
        )
        prun = ParseRun(
            id="prun_vec_test",
            document_id="doc_vec_test",
            version=1,
            is_current=True,
            parser_name="pymupdf",
            parser_version="1.0",
            configuration_hash="hash_vec",
            strategy_decided=True,
            degraded=False,
            route="born_digital",
            schema_version="1.0",
            canonical={},
            inspection={},
            quality_report={},
            started_at=now,
            finished_at=now,
            created_at=now,
        )
        chunk = DocumentChunk(
            id="chunk_vec_1024",
            document_id="doc_vec_test",
            parse_run_id="prun_vec_test",
            document_version=1,
            chunk_index=0,
            parent_chunk_id=None,
            section_path=["Mục I"],
            page_numbers=[1],
            source_block_ids=["b1"],
            text="Vector test chunk with 1024 dimensions.",
            token_count=10,
            embedding=vector_1024,
            embedding_model="bge-m3",
            embedding_version="bge-m3-v1",
            created_at=now,
        )
        session.add_all([doc, prun, chunk])
        session.commit()

    with Session(engine) as session:
        fetched_chunk = session.get(DocumentChunk, "chunk_vec_1024")
        assert fetched_chunk is not None
        assert fetched_chunk.embedding is not None
        assert isinstance(fetched_chunk.embedding, list)
        assert len(fetched_chunk.embedding) == EMBEDDING_DIM
        assert all(isinstance(x, float) for x in fetched_chunk.embedding)
        assert fetched_chunk.embedding == pytest.approx(vector_1024, rel=1e-5)


def test_downgrade_pg(pg_alembic_config: tuple[Config, Engine]) -> None:
    """Case 5: Downgrade from head to 0004 restores JSON column, downgrade to base succeeds."""
    config, engine = pg_alembic_config
    command.upgrade(config, "head")

    # Insert a document and chunk with a 1024-dim vector at head
    now = datetime.now(UTC)
    vector_1024 = [0.05] * EMBEDDING_DIM
    with Session(engine) as session:
        doc = Document(
            id="doc_down",
            filename="down.pdf",
            content_type="application/pdf",
            byte_size=1000,
            checksum_sha256="sha256_down",
            storage_uri="local://storage/down",
            status="READY",
            created_at=now,
            updated_at=now,
        )
        prun = ParseRun(
            id="prun_down",
            document_id="doc_down",
            version=1,
            is_current=True,
            parser_name="pymupdf",
            parser_version="1.0",
            configuration_hash="hash_down",
            strategy_decided=True,
            degraded=False,
            route="born_digital",
            schema_version="1.0",
            canonical={},
            inspection={},
            quality_report={},
            started_at=now,
            finished_at=now,
            created_at=now,
        )
        chunk = DocumentChunk(
            id="chunk_down_1",
            document_id="doc_down",
            parse_run_id="prun_down",
            document_version=1,
            chunk_index=0,
            parent_chunk_id=None,
            section_path=["Mục A"],
            page_numbers=[1],
            source_block_ids=["b1"],
            text="Downgrade chunk test",
            token_count=5,
            embedding=vector_1024,
            embedding_model="bge-m3",
            embedding_version="v1",
            created_at=now,
        )
        session.add_all([doc, prun, chunk])
        session.commit()

    # Downgrade to Phase 4
    command.downgrade(config, "0004_phase4_chunk_index")

    with engine.connect() as conn:
        # Check column is JSON again
        data_type = conn.execute(
            text(
                "SELECT data_type FROM information_schema.columns "
                "WHERE table_name = 'document_chunks' AND column_name = 'embedding'"
            )
        ).scalar()
        assert data_type == "json"

        # Check embedding metadata is cleared and row survived
        row = (
            conn.execute(
                text(
                    "SELECT id, embedding, embedding_version, embedding_model "
                    "FROM document_chunks WHERE id = 'chunk_down_1'"
                )
            )
            .mappings()
            .one()
        )
        assert row["id"] == "chunk_down_1"
        assert row["embedding"] is None
        assert row["embedding_version"] is None
        assert row["embedding_model"] is None

    # Downgrade to base
    command.downgrade(config, "base")
    tables = inspect(engine).get_table_names()
    assert "document_chunks" not in tables


def test_sqlite_upgrade_and_downgrade(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Case 6: SQLite upgrade to head then downgrade to base work cleanly without skip."""
    sqlite_url = f"sqlite:///{tmp_path / 'sqlite_test.db'}"
    monkeypatch.setenv("DATABASE_URL", sqlite_url)
    config = Config(ALEMBIC_INI)

    # Upgrade to head
    command.upgrade(config, "head")
    engine = create_engine(sqlite_url, future=True)
    try:
        tables = inspect(engine).get_table_names()
        assert "document_chunks" in tables

        # Verify ORM insert and readback on SQLite with 1024-dim embedding
        now = datetime.now(UTC)
        vector_1024 = [float(i) * 0.001 for i in range(EMBEDDING_DIM)]
        with Session(engine) as session:
            doc = Document(
                id="doc_sqlite",
                filename="sqlite.pdf",
                content_type="application/pdf",
                byte_size=100,
                checksum_sha256="sha256_sqlite",
                storage_uri="local://sqlite",
                status="READY",
                created_at=now,
                updated_at=now,
            )
            prun = ParseRun(
                id="prun_sqlite",
                document_id="doc_sqlite",
                version=1,
                is_current=True,
                parser_name="pymupdf",
                parser_version="1.0",
                configuration_hash="hash_sq",
                strategy_decided=True,
                degraded=False,
                route="born_digital",
                schema_version="1.0",
                canonical={},
                inspection={},
                quality_report={},
                started_at=now,
                finished_at=now,
                created_at=now,
            )
            chunk = DocumentChunk(
                id="chunk_sqlite_1",
                document_id="doc_sqlite",
                parse_run_id="prun_sqlite",
                document_version=1,
                chunk_index=0,
                parent_chunk_id=None,
                section_path=["Mục SQLite"],
                page_numbers=[1],
                source_block_ids=["b1"],
                text="SQLite chunk test",
                token_count=4,
                embedding=vector_1024,
                embedding_model="bge-m3",
                embedding_version="v1",
                created_at=now,
            )
            session.add_all([doc, prun, chunk])
            session.commit()

        with Session(engine) as session:
            fetched = session.get(DocumentChunk, "chunk_sqlite_1")
            assert fetched is not None
            assert fetched.embedding == pytest.approx(vector_1024, rel=1e-5)

    finally:
        engine.dispose()
        command.downgrade(config, "base")

    # Verify tables are dropped
    engine2 = create_engine(sqlite_url, future=True)
    try:
        tables_after = inspect(engine2).get_table_names()
        assert "document_chunks" not in tables_after
    finally:
        engine2.dispose()
