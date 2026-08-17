"""Migration tests.

Migrations are applied from an empty database, their constraints are exercised, and
they are rolled back again, so the suite is repeatable against the CI PostgreSQL
service as well as SQLite (`docs/09_CODEX_EXECUTION.md` section 10).
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from alembic import command

ALEMBIC_INI = "services/api/alembic.ini"

EXPECTED_TABLES = {"app_metadata", "documents", "jobs", "parse_runs"}


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


def test_downgrade_removes_the_phase_two_tables(database_url: str) -> None:
    config = Config(ALEMBIC_INI)
    command.upgrade(config, "head")
    command.downgrade(config, "0001_phase0_baseline")

    engine = create_engine(database_url, future=True)
    try:
        tables = set(inspect(engine).get_table_names())
        assert "app_metadata" in tables
        assert not {"documents", "jobs", "parse_runs"} & tables
    finally:
        engine.dispose()
        command.downgrade(config, "base")
