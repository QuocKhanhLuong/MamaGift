"""Unit tests for the SQLAlchemy pgvector type adapter `EmbeddingVector`."""

from __future__ import annotations

from typing import Any

import pgvector.sqlalchemy
import pytest
from sqlalchemy import JSON
from sqlalchemy.dialects import postgresql, sqlite

from app.vector_type import EMBEDDING_DIM, EmbeddingVector

pytestmark = pytest.mark.unit


class _ArrayLike:
    """Mock object simulating a numpy array with a .tolist() method."""

    def __init__(self, data: list[float]) -> None:
        self._data = data

    def tolist(self) -> list[float]:
        return list(self._data)


def test_postgresql_dialect_impl() -> None:
    """postgresql dialect impl is a pgvector Vector with dim 1024."""
    pg_dialect = postgresql.dialect()
    vec_type = EmbeddingVector(EMBEDDING_DIM)
    impl = vec_type.load_dialect_impl(pg_dialect)
    assert isinstance(impl, pgvector.sqlalchemy.Vector)
    assert impl.dim == 1024


def test_sqlite_dialect_impl() -> None:
    """sqlite dialect impl is JSON."""
    sq_dialect = sqlite.dialect()
    vec_type = EmbeddingVector(EMBEDDING_DIM)
    impl = vec_type.load_dialect_impl(sq_dialect)
    assert isinstance(impl, JSON)


def test_round_trip_vector_both_dialects() -> None:
    """Round-trip of 1024-float vector through bind/result on BOTH dialects yields equal list."""
    vec_type = EmbeddingVector(EMBEDDING_DIM)
    sample_vector = [float(i) * 0.001 for i in range(EMBEDDING_DIM)]

    for dialect in (postgresql.dialect(), sqlite.dialect()):
        bound = vec_type.process_bind_param(sample_vector, dialect)
        assert bound == sample_vector
        assert isinstance(bound, list)
        assert all(isinstance(x, float) for x in bound)

        result = vec_type.process_result_value(bound, dialect)
        assert result == sample_vector
        assert isinstance(result, list)
        assert all(isinstance(x, float) for x in result)


def test_bind_param_rejects_wrong_dimension_on_postgresql() -> None:
    """A wrong-dimension vector is refused on PostgreSQL, naming both dimensions.

    PostgreSQL is where the column is a real `vector(1024)`. Raising here converts what
    would otherwise be an opaque driver error into an actionable message.
    """
    vec_type = EmbeddingVector(1024)

    for wrong_length in (512, 1025, 1):
        with pytest.raises(ValueError) as exc_info:
            vec_type.process_bind_param([0.1] * wrong_length, postgresql.dialect())
        msg = str(exc_info.value)
        assert str(wrong_length) in msg
        assert "1024" in msg


def test_bind_param_allows_other_dimensions_on_sqlite() -> None:
    """SQLite stores JSON and imposes no dimension, so neither does this type.

    This is deliberate, not an oversight: the production guarantee comes from the
    PostgreSQL column type (proved in tests/integration/test_pgvector_dimension.py against a
    live database), and the Phase 4 single-document suite relies on short, readable vectors
    such as [1.0, 0.0] to keep cosine ordering legible. Simulating the constraint here would
    invalidate that suite while proving nothing about production.
    """
    vec_type = EmbeddingVector(1024)

    assert vec_type.process_bind_param([1.0, 0.0], sqlite.dialect()) == [1.0, 0.0]
    assert vec_type.process_bind_param([0.1] * 1025, sqlite.dialect()) == [0.1] * 1025


def test_bind_param_type_errors_apply_on_every_dialect() -> None:
    """Element-type validation is dialect independent -- only the dimension check is not."""
    vec_type = EmbeddingVector(1024)

    for dialect in (postgresql.dialect(), sqlite.dialect()):
        with pytest.raises(TypeError):
            vec_type.process_bind_param(["a", "b"], dialect)
        with pytest.raises(TypeError):
            vec_type.process_bind_param([True, False], dialect)


def test_bind_and_result_none_returns_none_both_dialects() -> None:
    """binding None returns None on both dialects."""
    vec_type = EmbeddingVector(1024)

    for dialect in (postgresql.dialect(), sqlite.dialect()):
        assert vec_type.process_bind_param(None, dialect) is None
        assert vec_type.process_result_value(None, dialect) is None


def test_bind_param_rejects_strings() -> None:
    """binding ['a']*1024 raises TypeError."""
    vec_type = EmbeddingVector(1024)
    str_vector: Any = ["a"] * 1024

    for dialect in (postgresql.dialect(), sqlite.dialect()):
        with pytest.raises(TypeError):
            vec_type.process_bind_param(str_vector, dialect)


def test_bind_param_rejects_booleans() -> None:
    """binding [True]*1024 raises TypeError (bool must not pass as a float)."""
    vec_type = EmbeddingVector(1024)
    bool_vector: Any = [True] * 1024

    for dialect in (postgresql.dialect(), sqlite.dialect()):
        with pytest.raises(TypeError):
            vec_type.process_bind_param(bool_vector, dialect)


def test_init_rejects_zero_and_negative_dim() -> None:
    """EmbeddingVector(0) and EmbeddingVector(-1) raise ValueError."""
    with pytest.raises(ValueError):
        EmbeddingVector(0)

    with pytest.raises(ValueError):
        EmbeddingVector(-1)


def test_process_result_value_converts_object_with_tolist() -> None:
    """process_result_value converts an object exposing .tolist() into a plain list."""
    vec_type = EmbeddingVector(1024)
    raw_data = [0.25] * 1024
    array_obj = _ArrayLike(raw_data)

    for dialect in (postgresql.dialect(), sqlite.dialect()):
        result = vec_type.process_result_value(array_obj, dialect)
        assert result == raw_data
        assert isinstance(result, list)
        assert all(isinstance(x, float) for x in result)


def test_bind_param_accepts_tuple() -> None:
    """process_bind_param accepts tuple and returns list of floats."""
    vec_type = EmbeddingVector(1024)
    tuple_data = tuple([0.5] * 1024)

    for dialect in (postgresql.dialect(), sqlite.dialect()):
        bound = vec_type.process_bind_param(tuple_data, dialect)
        assert bound == list(tuple_data)
        assert isinstance(bound, list)


def test_bind_param_rejects_non_sequence() -> None:
    """process_bind_param rejects non-sequence values with TypeError."""
    vec_type = EmbeddingVector(1024)

    for dialect in (postgresql.dialect(), sqlite.dialect()):
        for invalid_val in (42, 3.14, "not_a_vector", {"key": "val"}):
            with pytest.raises(TypeError):
                vec_type.process_bind_param(invalid_val, dialect)  # type: ignore[arg-type]


def test_process_result_value_rejects_invalid_type() -> None:
    """process_result_value rejects objects that are not None, sequence, or array-like."""
    vec_type = EmbeddingVector(1024)

    for dialect in (postgresql.dialect(), sqlite.dialect()):
        for invalid_val in (42, 3.14, object()):
            with pytest.raises(TypeError):
                vec_type.process_result_value(invalid_val, dialect)


def test_embedding_vector_repr_and_cache_ok() -> None:
    """EmbeddingVector has cache_ok=True and descriptive __repr__."""
    vec_type = EmbeddingVector(1024)
    assert vec_type.cache_ok is True
    assert repr(vec_type) == "EmbeddingVector(dim=1024)"
    assert EmbeddingVector(1024) == EmbeddingVector(1024)
    assert hash(EmbeddingVector(1024)) == hash(EmbeddingVector(1024))
    assert EmbeddingVector(1024) != EmbeddingVector(512)
