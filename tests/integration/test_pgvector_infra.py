"""Integration tests proving PostgreSQL 16 + pgvector infrastructure.

Covers:
1. pgvector extension availability and version reporting.
2. Round-trip storage and retrieval of 1024-dimensional float vectors.
3. Correct distance calculation and ordering with the `<=>` cosine distance operator.
4. Schema migration application up to head (document_chunks, documents, parse_runs, etc.).
5. Session factory binding and clean database state.

Note on skipping without database:
When MAMAGIFT_TEST_DATABASE_URL is absent or empty, the `pg_database_url` session fixture
calls `pytest.skip(...)`, cleanly skipping all tests in this module with zero errors.
"""

from __future__ import annotations

import pytest
from sqlalchemy import Engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker


def test_pgvector_available_version(pgvector_available: str) -> None:
    """Verify that pgvector_available fixture returns a non-empty extension version string."""
    assert isinstance(pgvector_available, str)
    assert len(pgvector_available) > 0
    parts = pgvector_available.split(".")
    assert len(parts) >= 2
    assert parts[0].isdigit()


def test_vector_roundtrip_1024(pg_engine: Engine, pgvector_available: str) -> None:
    """Round-trip a 1024-dimensional float vector through PostgreSQL + pgvector.

    Creates a table with a vector(1024) column, inserts a 1024-float vector,
    retrieves it, and asserts length, first element, and last element match.
    """
    table_name = "test_infra_vector_roundtrip_1024"
    with pg_engine.begin() as conn:
        conn.execute(text(f"DROP TABLE IF EXISTS {table_name}"))
        conn.execute(
            text(f"CREATE TABLE {table_name} (id INT PRIMARY KEY, embedding vector(1024))")
        )
        vec = [float(i) / 1024.0 for i in range(1024)]
        conn.execute(
            text(f"INSERT INTO {table_name} (id, embedding) VALUES (:id, CAST(:vec AS vector))"),
            {"id": 1, "vec": str(vec)},
        )

    try:
        with pg_engine.connect() as conn:
            row = conn.execute(text(f"SELECT embedding FROM {table_name} WHERE id = 1")).one()
            raw_val = row[0]
            if isinstance(raw_val, str):
                parsed = [float(x) for x in raw_val.strip("[]").split(",")]
            elif isinstance(raw_val, (list, tuple)):
                parsed = [float(x) for x in raw_val]
            elif hasattr(raw_val, "tolist"):
                parsed = [float(x) for x in raw_val.tolist()]
            else:
                raise TypeError(f"Unexpected vector return type: {type(raw_val)}")

            assert len(parsed) == 1024
            assert pytest.approx(parsed[0], abs=1e-5) == vec[0]
            assert pytest.approx(parsed[-1], abs=1e-5) == vec[-1]
            assert pytest.approx(parsed[512], abs=1e-5) == vec[512]
    finally:
        with pg_engine.begin() as conn:
            conn.execute(text(f"DROP TABLE IF EXISTS {table_name}"))


def test_cosine_distance_ordering(pg_engine: Engine, pgvector_available: str) -> None:
    """Verify that pgvector's <=> cosine distance operator calculates distances and orders properly.

    Inserts three known 1024-dimensional vectors with known angular separations from
    a query vector q, queries with ORDER BY embedding <=> :q, and asserts the expected id order.
    """
    table_name = "test_infra_vector_cosine_order"
    with pg_engine.begin() as conn:
        conn.execute(text(f"DROP TABLE IF EXISTS {table_name}"))
        conn.execute(
            text(f"CREATE TABLE {table_name} (id INT PRIMARY KEY, embedding vector(1024))")
        )

        # q = [1.0, 0.0, 0.0, ...]
        # v1: identical to q -> angle 0, cosine distance = 0.0
        v1 = [1.0] + [0.0] * 1023
        # v2: angle 45 degrees to q -> cosine similarity ~0.7071, cosine distance ~0.2929
        v2 = [0.70710678, 0.70710678] + [0.0] * 1022
        # v3: orthogonal to q -> angle 90 degrees, cosine similarity 0.0, cosine distance = 1.0
        v3 = [0.0, 1.0] + [0.0] * 1022

        # Insert in non-sorted order (3, 1, 2)
        conn.execute(
            text(
                f"INSERT INTO {table_name} (id, embedding) VALUES "
                f"(3, CAST(:v3 AS vector)), (1, CAST(:v1 AS vector)), (2, CAST(:v2 AS vector))"
            ),
            {"v1": str(v1), "v2": str(v2), "v3": str(v3)},
        )

    try:
        with pg_engine.connect() as conn:
            query_vector = [1.0] + [0.0] * 1023
            results = conn.execute(
                text(
                    f"SELECT id, embedding <=> CAST(:q AS vector) AS distance "
                    f"FROM {table_name} "
                    f"ORDER BY embedding <=> CAST(:q AS vector) ASC"
                ),
                {"q": str(query_vector)},
            ).fetchall()

            ordered_ids = [row[0] for row in results]
            distances = [float(row[1]) for row in results]

            assert ordered_ids == [1, 2, 3]
            assert pytest.approx(distances[0], abs=1e-5) == 0.0
            assert 0.28 < distances[1] < 0.31
            assert pytest.approx(distances[2], abs=1e-5) == 1.0
    finally:
        with pg_engine.begin() as conn:
            conn.execute(text(f"DROP TABLE IF EXISTS {table_name}"))


def test_migrated_pg_schema(migrated_pg: Engine) -> None:
    """Verify that migrated_pg fixture applies all Alembic migrations to head.

    Asserts that document_chunks, documents, parse_runs, feedback_events, and jobs all exist.
    """
    inspector = inspect(migrated_pg)
    tables = set(inspector.get_table_names())
    expected_tables = {
        "document_chunks",
        "documents",
        "parse_runs",
        "feedback_events",
        "jobs",
    }
    assert expected_tables <= tables


def test_pg_session_factory_and_clean_state(
    pg_session_factory: sessionmaker[Session],
) -> None:
    """Verify that pg_session_factory creates sessions against the migrated database.

    Also proves that each test starts with empty tables.
    """
    with pg_session_factory() as session:
        count = session.execute(text("SELECT COUNT(*) FROM documents")).scalar()
        assert count == 0


def test_pg_database_url_fixture(pg_database_url: str) -> None:
    """Verify that pg_database_url fixture returns a valid PostgreSQL+psycopg URL."""
    assert pg_database_url.startswith("postgresql+psycopg://")
