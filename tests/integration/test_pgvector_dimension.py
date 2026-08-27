"""The production dimension guarantee, proved against a live PostgreSQL + pgvector database.

`EmbeddingVector.process_bind_param` only raises on the PostgreSQL dialect, and on SQLite it
imposes no dimension at all. That is safe precisely because the PostgreSQL column type is the
real constraint: `vector(1024)` rejects a wrong-dimension value no matter what the application
does. These tests exist so that claim is verified rather than asserted.
"""

from __future__ import annotations

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from app.vector_type import EMBEDDING_DIM

TABLE = "test_infra_vector_dimension"


@pytest.fixture
def dimension_table(pg_engine: Engine, pgvector_available: str) -> object:
    with pg_engine.begin() as conn:
        conn.execute(text(f"DROP TABLE IF EXISTS {TABLE}"))
        conn.execute(
            text(f"CREATE TABLE {TABLE} (id INT PRIMARY KEY, embedding vector({EMBEDDING_DIM}))")
        )
    yield None
    with pg_engine.begin() as conn:
        conn.execute(text(f"DROP TABLE IF EXISTS {TABLE}"))


def _insert(conn: object, row_id: int, vector: list[float]) -> None:
    conn.execute(  # type: ignore[attr-defined]
        text(f"INSERT INTO {TABLE} (id, embedding) VALUES (:id, CAST(:v AS vector))"),
        {"id": row_id, "v": str(vector)},
    )


def test_column_accepts_the_declared_dimension(pg_engine: Engine, dimension_table: object) -> None:
    with pg_engine.begin() as conn:
        _insert(conn, 1, [0.5] * EMBEDDING_DIM)
    with pg_engine.connect() as conn:
        stored = conn.execute(text(f"SELECT embedding FROM {TABLE} WHERE id = 1")).scalar_one()
    assert stored is not None


@pytest.mark.parametrize("wrong_length", [1, 512, EMBEDDING_DIM - 1, EMBEDDING_DIM + 1])
def test_database_rejects_a_wrong_dimension_vector(
    pg_engine: Engine, dimension_table: object, wrong_length: int
) -> None:
    """The column itself refuses the write, independent of any Python-side check.

    If someone deletes `EmbeddingVector`'s dimension guard entirely, this test still passes --
    and that is the point. It proves the guarantee lives in the schema, which is what makes
    the SQLite pass-through acceptable.
    """
    with pytest.raises(DBAPIError) as exc_info:
        with pg_engine.begin() as conn:
            _insert(conn, 2, [0.5] * wrong_length)

    message = str(exc_info.value)
    assert "dimension" in message.lower() or "expected" in message.lower()


def test_declared_column_dimension_matches_the_application_constant(
    pg_engine: Engine, dimension_table: object
) -> None:
    """`vector(N)` in the database must agree with EMBEDDING_DIM, or the guard is fiction."""
    with pg_engine.connect() as conn:
        declared = conn.execute(
            text(
                "SELECT format_type(a.atttypid, a.atttypmod) "
                "FROM pg_attribute a "
                "JOIN pg_class c ON c.oid = a.attrelid "
                "WHERE c.relname = :table AND a.attname = 'embedding'"
            ),
            {"table": TABLE},
        ).scalar_one()
    assert declared == f"vector({EMBEDDING_DIM})"
