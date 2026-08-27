"""Pytest fixtures for PostgreSQL 16 + pgvector integration tests.

Provides session-scoped database connection/engine management and pgvector extension verification,
plus function-scoped migration lifecycle management via Alembic.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from alembic import command

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = str(REPO_ROOT / "services" / "api" / "alembic.ini")


@pytest.fixture(scope="session")
def pg_database_url() -> str:
    """Read MAMAGIFT_TEST_DATABASE_URL and verify PostgreSQL connectivity.

    Skips cleanly if unset, invalid scheme, or if the database is unreachable.
    """
    raw_url = os.environ.get("MAMAGIFT_TEST_DATABASE_URL")
    if not raw_url or not raw_url.strip():
        pytest.skip(
            "MAMAGIFT_TEST_DATABASE_URL is not set; "
            "PostgreSQL+pgvector integration tests are skipped",
            allow_module_level=False,
        )

    url = raw_url.strip()
    if not url.startswith("postgresql+psycopg://"):
        pytest.skip(
            f"MAMAGIFT_TEST_DATABASE_URL must start with 'postgresql+psycopg://', got: {url}",
            allow_module_level=False,
        )

    temp_engine = create_engine(url, future=True)
    try:
        with temp_engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:
        pytest.skip(
            f"MAMAGIFT_TEST_DATABASE_URL is set but PostgreSQL is unreachable ({exc})",
            allow_module_level=False,
        )
    finally:
        temp_engine.dispose()

    return url


@pytest.fixture(scope="session")
def pg_engine(pg_database_url: str) -> Iterator[Engine]:
    """Provide a session-scoped SQLAlchemy Engine bound to the test database."""
    engine = create_engine(pg_database_url, future=True)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture(scope="session")
def pgvector_available(pg_engine: Engine) -> str:
    """Ensure pgvector extension is available, returning the extension version string."""
    try:
        with pg_engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            version_row = conn.execute(
                text("SELECT extversion FROM pg_extension WHERE extname='vector'")
            ).scalar()
    except Exception as exc:
        pytest.skip(
            f"pgvector extension could not be initialized: {exc}",
            allow_module_level=False,
        )

    if not version_row:
        pytest.skip(
            "pgvector extension is not available in pg_extension",
            allow_module_level=False,
        )

    return str(version_row)


@pytest.fixture
def migrated_pg(
    pg_database_url: str,
    pg_engine: Engine,
    pgvector_available: str,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[Engine]:
    """Run migrations up to head, yield the engine, and downgrade to base on teardown."""
    monkeypatch.setenv("DATABASE_URL", pg_database_url)
    config = Config(ALEMBIC_INI)
    # Start from base rather than trusting the previous test's teardown. If an earlier test
    # crashed before downgrading, `upgrade head` would be a no-op and this test would run
    # against a stale schema while still reporting green.
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    try:
        yield pg_engine
    finally:
        # `pg_engine` is session-scoped and outlives this fixture, so it is NOT disposed here;
        # only the schema this fixture created is rolled back.
        command.downgrade(config, "base")


@pytest.fixture
def pg_session_factory(migrated_pg: Engine) -> sessionmaker[Session]:
    """Provide a session factory bound to the migrated test database."""
    return sessionmaker(bind=migrated_pg, expire_on_commit=False, future=True)
