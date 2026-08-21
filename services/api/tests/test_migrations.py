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

from alembic import command

ALEMBIC_INI = "services/api/alembic.ini"

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
    try:
        yield engine
    finally:
        engine.dispose()
        command.downgrade(config, "base")


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
        connection.execute(
            text(
                "INSERT INTO documents (id, filename, content_type, byte_size, "
                "checksum_sha256, storage_uri, status, requires_user_review, "
                "created_at, updated_at) VALUES "
                "('doc_1', 'a.pdf', 'application/pdf', 10, 'abc', 'local://a', "
                "'UPLOADED', :flag, :now, :now)"
            ),
            {"now": datetime.now(UTC), "flag": False},
        )

    with pytest.raises(IntegrityError):
        with upgraded.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO documents (id, filename, content_type, byte_size, "
                    "checksum_sha256, storage_uri, status, requires_user_review, "
                    "created_at, updated_at) VALUES "
                    "('doc_2', 'b.pdf', 'application/pdf', 10, 'abc', 'local://b', "
                    "'UPLOADED', :flag, :now, :now)"
                ),
                {"now": datetime.now(UTC), "flag": False},
            )


def test_job_idempotency_key_is_unique(upgraded) -> None:
    now = datetime.now(UTC)
    with upgraded.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO documents (id, filename, content_type, byte_size, "
                "checksum_sha256, storage_uri, status, requires_user_review, "
                "created_at, updated_at) VALUES "
                "('doc_1', 'a.pdf', 'application/pdf', 10, 'abc', 'local://a', "
                "'UPLOADED', :flag, :now, :now)"
            ),
            {"now": now, "flag": False},
        )
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
    now = datetime.now(UTC)
    insert_run = (
        "INSERT INTO parse_runs (id, document_id, version, is_current, parser_name, "
        "parser_version, configuration_hash, strategy_decided, degraded, route, "
        "schema_version, canonical, inspection, quality_report, started_at, finished_at, "
        "created_at) VALUES (:id, 'doc_1', 1, :flag, 'pymupdf', '1.0', 'hash', :flag, "
        ":flag, 'born_digital', '1.0', '{}', '{}', '{}', :now, :now, :now)"
    )
    with upgraded.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO documents (id, filename, content_type, byte_size, "
                "checksum_sha256, storage_uri, status, requires_user_review, "
                "created_at, updated_at) VALUES "
                "('doc_1', 'a.pdf', 'application/pdf', 10, 'abc', 'local://a', "
                "'UPLOADED', :flag, :now, :now)"
            ),
            {"now": now, "flag": False},
        )
        connection.execute(text(insert_run), {"id": "prun_1", "now": now, "flag": False})

    with pytest.raises(IntegrityError):
        with upgraded.begin() as connection:
            connection.execute(text(insert_run), {"id": "prun_2", "now": now, "flag": False})


def test_feedback_event_round_trip(upgraded) -> None:
    now = datetime.now(UTC)
    with upgraded.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO documents (id, filename, content_type, byte_size, "
                "checksum_sha256, storage_uri, status, requires_user_review, "
                "created_at, updated_at) VALUES "
                "('doc_1', 'a.pdf', 'application/pdf', 10, 'abc', 'local://a', "
                "'UPLOADED', :flag, :now, :now)"
            ),
            {"now": now, "flag": False},
        )
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
    columns = {column["name"] for column in inspect(upgraded).get_columns("document_chunks")}
    assert {
        "id",
        "document_id",
        "parse_run_id",
        "document_version",
        "chunk_index",
        "parent_chunk_id",
        "section_path",
        "page_numbers",
        "source_block_ids",
        "text",
        "token_count",
        "embedding",
        "embedding_model",
        "embedding_version",
        "created_at",
    } <= columns


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


def test_document_chunks_unique_constraint_enforced(upgraded) -> None:
    now = datetime.now(UTC)
    with upgraded.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO documents (id, filename, content_type, byte_size, "
                "checksum_sha256, storage_uri, status, requires_user_review, "
                "created_at, updated_at) VALUES "
                "('doc_1', 'a.pdf', 'application/pdf', 10, 'abc', 'local://a', "
                "'UPLOADED', :flag, :now, :now)"
            ),
            {"now": now, "flag": False},
        )
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


def test_document_chunks_two_parse_runs_coexist_without_collision(upgraded) -> None:
    now = datetime.now(UTC)
    with upgraded.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO documents (id, filename, content_type, byte_size, "
                "checksum_sha256, storage_uri, status, requires_user_review, "
                "created_at, updated_at) VALUES "
                "('doc_1', 'a.pdf', 'application/pdf', 10, 'abc', 'local://a', "
                "'UPLOADED', :flag, :now, :now)"
            ),
            {"now": now, "flag": False},
        )
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


def test_document_chunks_embedding_metadata_round_trip(upgraded) -> None:
    now = datetime.now(UTC)
    with upgraded.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO documents (id, filename, content_type, byte_size, "
                "checksum_sha256, storage_uri, status, requires_user_review, "
                "created_at, updated_at) VALUES "
                "('doc_1', 'a.pdf', 'application/pdf', 10, 'abc', 'local://a', "
                "'UPLOADED', :flag, :now, :now)"
            ),
            {"now": now, "flag": False},
        )
        connection.execute(
            text(
                "INSERT INTO document_chunks (id, document_id, parse_run_id, "
                "document_version, chunk_index, parent_chunk_id, section_path, "
                "page_numbers, source_block_ids, text, token_count, embedding, "
                "embedding_model, embedding_version, created_at) VALUES "
                "('chunk_unembedded', 'doc_1', 'prun_1', 1, 0, NULL, '[]', '[1]', '[\"b1\"]', "
                "'Not yet embedded', 10, NULL, NULL, NULL, :now), "
                "('chunk_embedded', 'doc_1', 'prun_1', 1, 1, NULL, '[]', '[1]', '[\"b2\"]', "
                "'Embedded text', 15, :emb, 'bge-m3', 'v1', :now)"
            ),
            {"now": now, "emb": json.dumps([0.12, -0.34, 0.56])},
        )

    with upgraded.connect() as connection:
        row_unembedded = connection.execute(
            text(
                "SELECT embedding, embedding_model, embedding_version "
                "FROM document_chunks WHERE id = 'chunk_unembedded'"
            )
        ).one()
        row_embedded = connection.execute(
            text(
                "SELECT embedding, embedding_model, embedding_version "
                "FROM document_chunks WHERE id = 'chunk_embedded'"
            )
        ).one()

    assert row_unembedded.embedding is None
    assert row_unembedded.embedding_model is None
    assert row_unembedded.embedding_version is None

    assert row_embedded.embedding is not None
    assert row_embedded.embedding_model == "bge-m3"
    assert row_embedded.embedding_version == "v1"


def test_document_chunks_cascade_delete(database_url: str) -> None:
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
            connection.execute(
                text(
                    "INSERT INTO documents (id, filename, content_type, byte_size, "
                    "checksum_sha256, storage_uri, status, requires_user_review, "
                    "created_at, updated_at) VALUES "
                    "('doc_1', 'a.pdf', 'application/pdf', 10, 'abc', 'local://a', "
                    "'UPLOADED', :flag, :now, :now)"
                ),
                {"now": now, "flag": False},
            )
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
