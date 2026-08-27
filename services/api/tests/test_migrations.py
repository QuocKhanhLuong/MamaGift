"""Migration tests.

Migrations are applied from an empty database, their constraints are exercised, and
they are rolled back again, so the suite is repeatable against the CI PostgreSQL
service as well as SQLite (`docs/09_CODEX_EXECUTION.md` section 10).
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from alembic import command
from app.models import Document, DocumentChunk, ParseRun
from app.vector_type import EMBEDDING_DIM

ALEMBIC_INI = "services/api/alembic.ini"

# From 0005_phase5_pgvector onward, document_chunks.embedding is a real `vector(1024)` on
# PostgreSQL, so a hand-written 3-element literal is rejected by the database itself. Keep the
# distinctive leading values these assertions were written around and zero-pad to the declared
# dimension: the round trip is still exact, and it now exercises the shipped column type.
SAMPLE_EMBEDDING: list[float] = [0.12, -0.34, 0.56] + [0.0] * (EMBEDDING_DIM - 3)
ORM_EMBEDDING: list[float] = [0.1, 0.2] + [0.0] * (EMBEDDING_DIM - 2)

EXPECTED_TABLES = {
    "app_metadata",
    "documents",
    "jobs",
    "parse_runs",
    "feedback_events",
    "document_chunks",
}


@pytest.fixture
def database_url(tmp_path, monkeypatch: pytest.MonkeyPatch) -> str:
    url = os.environ.get("MAMAGIFT_TEST_DATABASE_URL") or f"sqlite:///{tmp_path / 'migration.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    return url


@pytest.fixture
def upgraded(database_url: str):
    config = Config(ALEMBIC_INI)
    command.upgrade(config, "head")
    engine = create_engine(database_url, future=True)
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def set_sqlite_pragma(dbapi_connection: object, connection_record: object) -> None:
            cursor = dbapi_connection.cursor()  # type: ignore[union-attr]
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    try:
        yield engine
    finally:
        engine.dispose()
        command.downgrade(config, "base")


def _insert_document(
    connection,
    doc_id: str = "doc_1",
    filename: str = "a.pdf",
    checksum: str | None = None,
) -> None:
    now = datetime.now(UTC)
    connection.execute(
        text(
            "INSERT INTO documents (id, filename, content_type, byte_size, "
            "checksum_sha256, storage_uri, status, requires_user_review, "
            "created_at, updated_at) VALUES "
            "(:id, :filename, 'application/pdf', 10, :checksum, :uri, "
            "'UPLOADED', :flag, :now, :now)"
        ),
        {
            "id": doc_id,
            "filename": filename,
            "checksum": checksum or f"sha_{doc_id}",
            "uri": f"local://{doc_id}",
            "flag": False,
            "now": now,
        },
    )


def _insert_parse_run(
    connection,
    run_id: str = "prun_1",
    doc_id: str = "doc_1",
    version: int = 1,
) -> None:
    now = datetime.now(UTC)
    connection.execute(
        text(
            "INSERT INTO parse_runs (id, document_id, version, is_current, parser_name, "
            "parser_version, configuration_hash, strategy_decided, degraded, route, "
            "schema_version, canonical, inspection, quality_report, started_at, finished_at, "
            "created_at) VALUES (:id, :doc_id, :version, :flag, 'pymupdf', '1.0', 'hash', :flag, "
            ":flag, 'born_digital', '1.0', '{}', '{}', '{}', :now, :now, :now)"
        ),
        {"id": run_id, "doc_id": doc_id, "version": version, "now": now, "flag": False},
    )


def test_migrations_apply_from_empty_database(upgraded) -> None:
    tables = set(inspect(upgraded).get_table_names())
    assert EXPECTED_TABLES <= tables


def test_document_columns_match_the_api_contract(upgraded) -> None:
    columns = {column["name"] for column in inspect(upgraded).get_columns("documents")}
    assert {
        "id",
        "filename",
        "checksum_sha256",
        "storage_uri",
        "status",
        "document_type",
        "document_number",
        "title",
        "issuer",
        "issued_date",
        "signer",
        "deadline",
        "current_parse_run_id",
        "created_at",
        "updated_at",
    } <= columns


def test_checksum_is_unique(upgraded) -> None:
    with upgraded.begin() as connection:
        _insert_document(connection, "doc_1", "a.pdf", "abc")

    with pytest.raises(IntegrityError):
        with upgraded.begin() as connection:
            _insert_document(connection, "doc_2", "b.pdf", "abc")


def test_job_idempotency_key_is_unique(upgraded) -> None:
    now = datetime.now(UTC)
    with upgraded.begin() as connection:
        _insert_document(connection, "doc_1", "a.pdf")
        connection.execute(
            text(
                "INSERT INTO jobs (id, document_id, kind, status, attempt, max_attempts, "
                "idempotency_key, created_at, updated_at) VALUES "
                "('job_1', 'doc_1', 'parse', 'QUEUED', 0, 3, 'doc_1:parse:v1', :now, :now)"
            ),
            {"now": now},
        )

    with pytest.raises(IntegrityError):
        with upgraded.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO jobs (id, document_id, kind, status, attempt, max_attempts, "
                    "idempotency_key, created_at, updated_at) VALUES "
                    "('job_2', 'doc_1', 'parse', 'QUEUED', 0, 3, 'doc_1:parse:v1', :now, :now)"
                ),
                {"now": now},
            )


def test_parse_run_version_is_unique_per_document(upgraded) -> None:
    with upgraded.begin() as connection:
        _insert_document(connection, "doc_1", "a.pdf")
        _insert_parse_run(connection, "prun_1", "doc_1", 1)

    with pytest.raises(IntegrityError):
        with upgraded.begin() as connection:
            _insert_parse_run(connection, "prun_2", "doc_1", 1)


def test_feedback_event_round_trip(upgraded) -> None:
    now = datetime.now(UTC)
    with upgraded.begin() as connection:
        _insert_document(connection, "doc_1", "a.pdf")
        connection.execute(
            text(
                "INSERT INTO feedback_events (id, document_id, feedback_type, field_id, "
                "corrected_value, created_at) VALUES "
                "('fb_1', 'doc_1', 'critical_field_correction', 'field_deadline_1', "
                "'2026-08-25', :now)"
            ),
            {"now": now},
        )

    with upgraded.connect() as connection:
        row = connection.execute(
            text("SELECT corrected_value FROM feedback_events WHERE id = 'fb_1'")
        ).one()
    assert row.corrected_value == "2026-08-25"


def test_document_chunks_columns_match_the_persistence_contract(upgraded) -> None:
    columns = {
        column["name"]: column for column in inspect(upgraded).get_columns("document_chunks")
    }
    expected_not_null = {
        "id",
        "document_id",
        "parse_run_id",
        "document_version",
        "chunk_index",
        "section_path",
        "page_numbers",
        "source_block_ids",
        "text",
        "token_count",
        "created_at",
    }
    expected_nullable = {
        "parent_chunk_id",
        "embedding",
        "embedding_model",
        "embedding_version",
    }
    assert (expected_not_null | expected_nullable) <= set(columns.keys())

    for col_name in expected_not_null:
        assert columns[col_name]["nullable"] is False, f"Column {col_name} should be NOT NULL"

    for col_name in expected_nullable:
        assert columns[col_name]["nullable"] is True, f"Column {col_name} should be nullable"


def test_document_chunks_indexes_and_unique_constraints_exist(upgraded) -> None:
    inspector = inspect(upgraded)
    indexes = inspector.get_indexes("document_chunks")
    compound_indexes = [
        idx for idx in indexes if idx["column_names"] == ["document_id", "parse_run_id"]
    ]
    assert len(compound_indexes) == 1
    assert compound_indexes[0]["name"] == "ix_document_chunks_document_id_parse_run_id"

    unique_constraints = inspector.get_unique_constraints("document_chunks")
    unique_cols = [uc["column_names"] for uc in unique_constraints]
    unique_index_cols = [idx["column_names"] for idx in indexes if idx.get("unique")]
    all_unique = unique_cols + unique_index_cols
    assert ["parse_run_id", "chunk_index"] in all_unique

    pr_unique_constraints = inspector.get_unique_constraints("parse_runs")
    pr_unique_cols = [uc["column_names"] for uc in pr_unique_constraints]
    pr_indexes = inspector.get_indexes("parse_runs")
    pr_unique_index_cols = [idx["column_names"] for idx in pr_indexes if idx.get("unique")]
    pr_all_unique = pr_unique_cols + pr_unique_index_cols
    assert ["id", "document_id", "version"] in pr_all_unique

    fks = inspector.get_foreign_keys("document_chunks")
    pr_fks = [
        fk
        for fk in fks
        if fk["referred_table"] == "parse_runs"
        and fk["constrained_columns"] == ["parse_run_id", "document_id", "document_version"]
        and fk["referred_columns"] == ["id", "document_id", "version"]
    ]
    assert len(pr_fks) == 1
    assert pr_fks[0].get("options", {}).get("ondelete") == "CASCADE"


def test_document_chunks_unique_constraint_enforced(upgraded) -> None:
    now = datetime.now(UTC)
    with upgraded.begin() as connection:
        _insert_document(connection, "doc_1", "a.pdf")
        _insert_parse_run(connection, "prun_1", "doc_1", 1)
        connection.execute(
            text(
                "INSERT INTO document_chunks (id, document_id, parse_run_id, "
                "document_version, chunk_index, parent_chunk_id, section_path, "
                "page_numbers, source_block_ids, text, token_count, embedding, "
                "embedding_model, embedding_version, created_at) VALUES "
                "('chunk_1', 'doc_1', 'prun_1', 1, 0, NULL, '[]', '[1]', '[\"b1\"]', "
                "'Sample text', 10, NULL, NULL, NULL, :now)"
            ),
            {"now": now},
        )

    with pytest.raises(IntegrityError):
        with upgraded.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO document_chunks (id, document_id, parse_run_id, "
                    "document_version, chunk_index, parent_chunk_id, section_path, "
                    "page_numbers, source_block_ids, text, token_count, embedding, "
                    "embedding_model, embedding_version, created_at) VALUES "
                    "('chunk_2', 'doc_1', 'prun_1', 1, 0, NULL, '[]', '[1]', '[\"b2\"]', "
                    "'Duplicate chunk index', 12, NULL, NULL, NULL, :now)"
                ),
                {"now": now},
            )


def test_document_chunks_cross_document_provenance_rejected(upgraded) -> None:
    """A chunk cannot reference a parse run belonging to a different document."""
    now = datetime.now(UTC)
    with upgraded.begin() as connection:
        _insert_document(connection, "doc_1", "a.pdf")
        _insert_parse_run(connection, "prun_doc1", "doc_1", 1)
        _insert_document(connection, "doc_2", "b.pdf")
        _insert_parse_run(connection, "prun_doc2", "doc_2", 1)

    with pytest.raises(IntegrityError):
        with upgraded.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO document_chunks (id, document_id, parse_run_id, "
                    "document_version, chunk_index, parent_chunk_id, section_path, "
                    "page_numbers, source_block_ids, text, token_count, embedding, "
                    "embedding_model, embedding_version, created_at) VALUES "
                    "('chunk_mismatch', 'doc_1', 'prun_doc2', 1, 0, NULL, '[]', '[1]', '[\"b1\"]', "
                    "'Cross-document chunk', 10, NULL, NULL, NULL, :now)"
                ),
                {"now": now},
            )


def test_document_chunks_wrong_version_provenance_rejected(upgraded) -> None:
    """A chunk's document_version must match the version in its parse run."""
    now = datetime.now(UTC)
    with upgraded.begin() as connection:
        _insert_document(connection, "doc_1", "a.pdf")
        _insert_parse_run(connection, "prun_1", "doc_1", 1)

    # Arbitrary / non-existent version
    with pytest.raises(IntegrityError):
        with upgraded.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO document_chunks (id, document_id, parse_run_id, "
                    "document_version, chunk_index, parent_chunk_id, section_path, "
                    "page_numbers, source_block_ids, text, token_count, embedding, "
                    "embedding_model, embedding_version, created_at) VALUES "
                    "('chunk_wrong_v999', 'doc_1', 'prun_1', 999, 0, NULL, '[]', "
                    "'[1]', '[\"b1\"]', 'Wrong version 999', 10, NULL, NULL, NULL, :now)"
                ),
                {"now": now},
            )

    # Disagreeing version (version 2 when parse run is version 1)
    with pytest.raises(IntegrityError):
        with upgraded.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO document_chunks (id, document_id, parse_run_id, "
                    "document_version, chunk_index, parent_chunk_id, section_path, "
                    "page_numbers, source_block_ids, text, token_count, embedding, "
                    "embedding_model, embedding_version, created_at) VALUES "
                    "('chunk_wrong_v2', 'doc_1', 'prun_1', 2, 0, NULL, '[]', '[1]', '[\"b1\"]', "
                    "'Wrong version 2', 10, NULL, NULL, NULL, :now)"
                ),
                {"now": now},
            )


def test_document_chunks_nonexistent_parse_run_rejected(upgraded) -> None:
    """A chunk cannot reference a parse run that does not exist."""
    now = datetime.now(UTC)
    with upgraded.begin() as connection:
        _insert_document(connection, "doc_1", "a.pdf")

    with pytest.raises(IntegrityError):
        with upgraded.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO document_chunks (id, document_id, parse_run_id, "
                    "document_version, chunk_index, parent_chunk_id, section_path, "
                    "page_numbers, source_block_ids, text, token_count, embedding, "
                    "embedding_model, embedding_version, created_at) VALUES "
                    "('chunk_ghost', 'doc_1', 'prun_ghost', 1, 0, NULL, '[]', '[1]', '[\"b1\"]', "
                    "'Ghost parse run', 10, NULL, NULL, NULL, :now)"
                ),
                {"now": now},
            )


def test_document_chunks_null_required_columns_rejected(upgraded) -> None:
    """NOT NULL constraints are strictly enforced on all required columns."""
    now = datetime.now(UTC)
    with upgraded.begin() as connection:
        _insert_document(connection, "doc_1", "a.pdf")
        _insert_parse_run(connection, "prun_1", "doc_1", 1)

    # NULL parse_run_id
    with pytest.raises(IntegrityError):
        with upgraded.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO document_chunks (id, document_id, parse_run_id, "
                    "document_version, chunk_index, parent_chunk_id, section_path, "
                    "page_numbers, source_block_ids, text, token_count, embedding, "
                    "embedding_model, embedding_version, created_at) VALUES "
                    "('chunk_null_prun', 'doc_1', NULL, 1, 0, NULL, '[]', '[1]', '[\"b1\"]', "
                    "'Null prun', 10, NULL, NULL, NULL, :now)"
                ),
                {"now": now},
            )

    # NULL document_version
    with pytest.raises(IntegrityError):
        with upgraded.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO document_chunks (id, document_id, parse_run_id, "
                    "document_version, chunk_index, parent_chunk_id, section_path, "
                    "page_numbers, source_block_ids, text, token_count, embedding, "
                    "embedding_model, embedding_version, created_at) VALUES "
                    "('chunk_null_ver', 'doc_1', 'prun_1', NULL, 0, NULL, '[]', '[1]', '[\"b1\"]', "
                    "'Null ver', 10, NULL, NULL, NULL, :now)"
                ),
                {"now": now},
            )

    # NULL text
    with pytest.raises(IntegrityError):
        with upgraded.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO document_chunks (id, document_id, parse_run_id, "
                    "document_version, chunk_index, parent_chunk_id, section_path, "
                    "page_numbers, source_block_ids, text, token_count, embedding, "
                    "embedding_model, embedding_version, created_at) VALUES "
                    "('chunk_null_txt', 'doc_1', 'prun_1', 1, 0, NULL, '[]', '[1]', '[\"b1\"]', "
                    "NULL, 10, NULL, NULL, NULL, :now)"
                ),
                {"now": now},
            )


def test_document_chunks_two_parse_runs_coexist_without_collision(upgraded) -> None:
    now = datetime.now(UTC)
    with upgraded.begin() as connection:
        _insert_document(connection, "doc_1", "a.pdf")
        _insert_parse_run(connection, "prun_1", "doc_1", 1)
        _insert_parse_run(connection, "prun_2", "doc_1", 2)

        # Parse run 1 (version 1)
        connection.execute(
            text(
                "INSERT INTO document_chunks (id, document_id, parse_run_id, "
                "document_version, chunk_index, parent_chunk_id, section_path, "
                "page_numbers, source_block_ids, text, token_count, embedding, "
                "embedding_model, embedding_version, created_at) VALUES "
                "('chunk_v1_0', 'doc_1', 'prun_1', 1, 0, NULL, '[]', '[1]', '[\"b1\"]', "
                "'Version 1 Chunk 0', 10, NULL, NULL, NULL, :now), "
                "('chunk_v1_1', 'doc_1', 'prun_1', 1, 1, 'chunk_v1_0', '[\"Sec 1\"]', "
                "'[1]', '[\"b2\"]', 'Version 1 Chunk 1', 15, NULL, NULL, NULL, :now)"
            ),
            {"now": now},
        )
        # Parse run 2 (version 2) - reparse with same chunk indices 0 and 1
        connection.execute(
            text(
                "INSERT INTO document_chunks (id, document_id, parse_run_id, "
                "document_version, chunk_index, parent_chunk_id, section_path, "
                "page_numbers, source_block_ids, text, token_count, embedding, "
                "embedding_model, embedding_version, created_at) VALUES "
                "('chunk_v2_0', 'doc_1', 'prun_2', 2, 0, NULL, '[]', '[1]', '[\"b1\"]', "
                "'Version 2 Chunk 0', 12, NULL, NULL, NULL, :now), "
                "('chunk_v2_1', 'doc_1', 'prun_2', 2, 1, 'chunk_v2_0', '[\"Sec 1\"]', "
                "'[1]', '[\"b2\"]', 'Version 2 Chunk 1', 18, NULL, NULL, NULL, :now)"
            ),
            {"now": now},
        )

    with upgraded.connect() as connection:
        rows_v1 = connection.execute(
            text(
                "SELECT id, text, document_version FROM document_chunks "
                "WHERE document_id = 'doc_1' AND parse_run_id = 'prun_1' "
                "ORDER BY chunk_index ASC"
            )
        ).fetchall()
        rows_v2 = connection.execute(
            text(
                "SELECT id, text, document_version FROM document_chunks "
                "WHERE document_id = 'doc_1' AND parse_run_id = 'prun_2' "
                "ORDER BY chunk_index ASC"
            )
        ).fetchall()

    assert len(rows_v1) == 2
    assert rows_v1[0].id == "chunk_v1_0"
    assert rows_v1[0].text == "Version 1 Chunk 0"
    assert rows_v1[0].document_version == 1
    assert rows_v1[1].id == "chunk_v1_1"
    assert rows_v1[1].text == "Version 1 Chunk 1"
    assert rows_v1[1].document_version == 1

    assert len(rows_v2) == 2
    assert rows_v2[0].id == "chunk_v2_0"
    assert rows_v2[0].text == "Version 2 Chunk 0"
    assert rows_v2[0].document_version == 2
    assert rows_v2[1].id == "chunk_v2_1"
    assert rows_v2[1].text == "Version 2 Chunk 1"
    assert rows_v2[1].document_version == 2


def test_document_chunks_exact_data_round_trip(upgraded) -> None:
    now = datetime.now(UTC)
    with upgraded.begin() as connection:
        _insert_document(connection, "doc_1", "a.pdf")
        _insert_parse_run(connection, "prun_1", "doc_1", 1)
        connection.execute(
            text(
                "INSERT INTO document_chunks (id, document_id, parse_run_id, "
                "document_version, chunk_index, parent_chunk_id, section_path, "
                "page_numbers, source_block_ids, text, token_count, embedding, "
                "embedding_model, embedding_version, created_at) VALUES "
                "('chunk_unembedded', 'doc_1', 'prun_1', 1, 0, NULL, :section_path, "
                ":page_numbers, :source_block_ids, :text_val, :token_count, "
                "NULL, NULL, NULL, :now), "
                "('chunk_embedded', 'doc_1', 'prun_1', 1, 1, 'chunk_unembedded', "
                "'[\"Chương II\"]', '[2]', '[\"b3\"]', 'Embedded text', 15, :emb, "
                "'bge-m3', 'v1', :now)"
            ),
            {
                "section_path": json.dumps(["Chương I", "Điều 1"]),
                "page_numbers": json.dumps([1, 2]),
                "source_block_ids": json.dumps(["b1", "b2"]),
                "text_val": "Cộng hòa Xã hội Chủ nghĩa Việt Nam",
                "token_count": 42,
                "now": now,
                "emb": json.dumps(SAMPLE_EMBEDDING),
            },
        )

    with upgraded.connect() as connection:
        row_unembedded = (
            connection.execute(
                text(
                    "SELECT id, document_id, parse_run_id, document_version, chunk_index, "
                    "parent_chunk_id, section_path, page_numbers, source_block_ids, text, "
                    "token_count, embedding, embedding_model, embedding_version "
                    "FROM document_chunks WHERE id = 'chunk_unembedded'"
                )
            )
            .mappings()
            .one()
        )
        row_embedded = (
            connection.execute(
                text(
                    "SELECT id, document_id, parse_run_id, document_version, chunk_index, "
                    "parent_chunk_id, section_path, page_numbers, source_block_ids, text, "
                    "token_count, embedding, embedding_model, embedding_version "
                    "FROM document_chunks WHERE id = 'chunk_embedded'"
                )
            )
            .mappings()
            .one()
        )

    # Exact field assertions
    assert row_unembedded["document_id"] == "doc_1"
    assert row_unembedded["parse_run_id"] == "prun_1"
    assert row_unembedded["document_version"] == 1
    assert row_unembedded["chunk_index"] == 0
    assert row_unembedded["parent_chunk_id"] is None
    sec_path = (
        json.loads(row_unembedded["section_path"])
        if isinstance(row_unembedded["section_path"], str)
        else row_unembedded["section_path"]
    )
    assert sec_path == ["Chương I", "Điều 1"]
    pg_nums = (
        json.loads(row_unembedded["page_numbers"])
        if isinstance(row_unembedded["page_numbers"], str)
        else row_unembedded["page_numbers"]
    )
    assert pg_nums == [1, 2]
    blk_ids = (
        json.loads(row_unembedded["source_block_ids"])
        if isinstance(row_unembedded["source_block_ids"], str)
        else row_unembedded["source_block_ids"]
    )
    assert blk_ids == ["b1", "b2"]
    assert row_unembedded["text"] == "Cộng hòa Xã hội Chủ nghĩa Việt Nam"
    assert row_unembedded["token_count"] == 42
    assert row_unembedded["embedding"] is None
    assert row_unembedded["embedding_model"] is None
    assert row_unembedded["embedding_version"] is None

    assert row_embedded["parent_chunk_id"] == "chunk_unembedded"
    assert row_embedded["embedding"] is not None
    emb_data = (
        json.loads(row_embedded["embedding"])
        if isinstance(row_embedded["embedding"], str)
        else row_embedded["embedding"]
    )
    assert emb_data == pytest.approx(SAMPLE_EMBEDDING)
    assert row_embedded["embedding_model"] == "bge-m3"
    assert row_embedded["embedding_version"] == "v1"


def test_document_chunks_cascade_delete_on_document_delete(database_url: str) -> None:
    config = Config(ALEMBIC_INI)
    command.upgrade(config, "head")

    engine = create_engine(database_url, future=True)
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def set_sqlite_pragma(dbapi_connection: object, connection_record: object) -> None:
            cursor = dbapi_connection.cursor()  # type: ignore[union-attr]
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    now = datetime.now(UTC)
    try:
        with engine.begin() as connection:
            _insert_document(connection, "doc_1", "a.pdf")
            _insert_parse_run(connection, "prun_1", "doc_1", 1)
            connection.execute(
                text(
                    "INSERT INTO document_chunks (id, document_id, parse_run_id, "
                    "document_version, chunk_index, parent_chunk_id, section_path, "
                    "page_numbers, source_block_ids, text, token_count, embedding, "
                    "embedding_model, embedding_version, created_at) VALUES "
                    "('chunk_1', 'doc_1', 'prun_1', 1, 0, NULL, '[]', '[1]', '[\"b1\"]', "
                    "'To be deleted', 10, NULL, NULL, NULL, :now)"
                ),
                {"now": now},
            )

        with engine.connect() as connection:
            count_before = connection.execute(
                text("SELECT count(*) FROM document_chunks WHERE document_id = 'doc_1'")
            ).scalar()
            assert count_before == 1

        with engine.begin() as connection:
            connection.execute(text("DELETE FROM documents WHERE id = 'doc_1'"))

        with engine.connect() as connection:
            count_after = connection.execute(
                text("SELECT count(*) FROM document_chunks WHERE document_id = 'doc_1'")
            ).scalar()
            assert count_after == 0
    finally:
        engine.dispose()
        command.downgrade(config, "base")


def test_document_chunks_cascade_delete_on_parse_run_delete(database_url: str) -> None:
    config = Config(ALEMBIC_INI)
    command.upgrade(config, "head")

    engine = create_engine(database_url, future=True)
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def set_sqlite_pragma(dbapi_connection: object, connection_record: object) -> None:
            cursor = dbapi_connection.cursor()  # type: ignore[union-attr]
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    now = datetime.now(UTC)
    try:
        with engine.begin() as connection:
            _insert_document(connection, "doc_1", "a.pdf")
            _insert_parse_run(connection, "prun_1", "doc_1", 1)
            _insert_parse_run(connection, "prun_2", "doc_1", 2)
            connection.execute(
                text(
                    "INSERT INTO document_chunks (id, document_id, parse_run_id, "
                    "document_version, chunk_index, parent_chunk_id, section_path, "
                    "page_numbers, source_block_ids, text, token_count, embedding, "
                    "embedding_model, embedding_version, created_at) VALUES "
                    "('chunk_v1', 'doc_1', 'prun_1', 1, 0, NULL, '[]', '[1]', '[\"b1\"]', "
                    "'Run 1 chunk', 10, NULL, NULL, NULL, :now), "
                    "('chunk_v2', 'doc_1', 'prun_2', 2, 0, NULL, '[]', '[1]', '[\"b1\"]', "
                    "'Run 2 chunk', 12, NULL, NULL, NULL, :now)"
                ),
                {"now": now},
            )

        with engine.begin() as connection:
            connection.execute(text("DELETE FROM parse_runs WHERE id = 'prun_1'"))

        with engine.connect() as connection:
            rows = connection.execute(
                text("SELECT id FROM document_chunks WHERE document_id = 'doc_1'")
            ).fetchall()
            assert [r.id for r in rows] == ["chunk_v2"]
    finally:
        engine.dispose()
        command.downgrade(config, "base")


def test_document_chunks_orm_mapping_and_relationships(upgraded) -> None:
    now = datetime.now(UTC)
    with Session(upgraded) as session:
        doc = Document(
            id="doc_orm",
            filename="orm.pdf",
            content_type="application/pdf",
            byte_size=100,
            checksum_sha256="sha256_orm",
            storage_uri="local://orm",
            status="UPLOADED",
            created_at=now,
            updated_at=now,
        )
        prun = ParseRun(
            id="prun_orm",
            document_id="doc_orm",
            version=1,
            is_current=True,
            parser_name="pymupdf",
            parser_version="1.0",
            configuration_hash="hash",
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
            id="chunk_orm_1",
            document_id="doc_orm",
            parse_run_id="prun_orm",
            document_version=1,
            chunk_index=0,
            parent_chunk_id=None,
            section_path=["Mục 1"],
            page_numbers=[1],
            source_block_ids=["b1"],
            text="ORM text chunk",
            token_count=15,
            embedding=ORM_EMBEDDING,
            embedding_model="bge-m3",
            embedding_version="v1",
            created_at=now,
        )
        session.add_all([doc, prun, chunk])
        session.commit()

    with Session(upgraded) as session:
        doc_fetched = session.get(Document, "doc_orm")
        assert doc_fetched is not None
        assert len(doc_fetched.document_chunks) == 1
        assert doc_fetched.document_chunks[0].id == "chunk_orm_1"
        assert doc_fetched.document_chunks[0].text == "ORM text chunk"

        prun_fetched = session.get(ParseRun, "prun_orm")
        assert prun_fetched is not None
        assert len(prun_fetched.document_chunks) == 1
        assert prun_fetched.document_chunks[0].id == "chunk_orm_1"

        chunk_fetched = session.get(DocumentChunk, "chunk_orm_1")
        assert chunk_fetched is not None
        assert chunk_fetched.document.id == "doc_orm"
        assert chunk_fetched.parse_run.id == "prun_orm"
        assert chunk_fetched.parse_run.version == 1

        # Test ORM cascade delete
        session.delete(doc_fetched)
        session.commit()

        assert session.get(DocumentChunk, "chunk_orm_1") is None
        assert session.get(ParseRun, "prun_orm") is None


def test_downgrade_removes_phase4_chunk_index(database_url: str) -> None:
    config = Config(ALEMBIC_INI)
    command.upgrade(config, "head")

    engine = create_engine(database_url, future=True)
    try:
        tables_head = set(inspect(engine).get_table_names())
        assert "document_chunks" in tables_head

        command.downgrade(config, "0003_phase3_feedback")
        tables_p3 = set(inspect(engine).get_table_names())
        assert "document_chunks" not in tables_p3
        assert {
            "app_metadata",
            "documents",
            "jobs",
            "parse_runs",
            "feedback_events",
        } <= tables_p3

        command.downgrade(config, "0001_phase0_baseline")
        tables_p0 = set(inspect(engine).get_table_names())
        assert "app_metadata" in tables_p0
        assert (
            not {
                "documents",
                "jobs",
                "parse_runs",
                "feedback_events",
                "document_chunks",
            }
            & tables_p0
        )
    finally:
        engine.dispose()
        command.downgrade(config, "base")


def test_downgrade_removes_the_phase_two_tables(database_url: str) -> None:
    config = Config(ALEMBIC_INI)
    command.upgrade(config, "head")
    command.downgrade(config, "0001_phase0_baseline")

    engine = create_engine(database_url, future=True)
    try:
        tables = set(inspect(engine).get_table_names())
        assert "app_metadata" in tables
        assert (
            not {
                "documents",
                "jobs",
                "parse_runs",
                "feedback_events",
                "document_chunks",
            }
            & tables
        )
    finally:
        engine.dispose()
        command.downgrade(config, "base")
