"""SQLAlchemy pgvector type adapter.

Provides `EmbeddingVector`, which uses pgvector's `VECTOR` type on PostgreSQL
and falls back to `JSON` on other dialects (such as SQLite for unit testing).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pgvector.sqlalchemy
from sqlalchemy import JSON, TypeDecorator
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeEngine

EMBEDDING_DIM = 1024


class EmbeddingVector(TypeDecorator[list[float] | None]):
    """`vector(N)` on PostgreSQL, JSON on every other dialect.

    The Python-side value is `list[float] | None` on both, so no caller changes.
    """

    cache_ok = True
    impl = JSON

    def __init__(self, dim: int = EMBEDDING_DIM, **kwargs: Any) -> None:
        if dim <= 0:
            raise ValueError(f"Vector dimension must be positive, got {dim}")
        super().__init__(**kwargs)
        self.dim = dim

    def __repr__(self) -> str:
        return f"EmbeddingVector(dim={self.dim})"

    def __eq__(self, other: object) -> bool:
        if isinstance(other, EmbeddingVector):
            return self.dim == other.dim
        return NotImplemented

    def __hash__(self) -> int:
        return hash((self.__class__, self.dim))

    def load_dialect_impl(self, dialect: Dialect) -> TypeEngine[Any]:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(pgvector.sqlalchemy.Vector(self.dim))
        return dialect.type_descriptor(JSON())

    def process_bind_param(
        self, value: Sequence[float] | None, dialect: Dialect
    ) -> list[float] | None:
        """Validate and normalise a vector on its way into the database.

        The dimension check is deliberately applied only on PostgreSQL, where the column is
        a real `vector(N)` and a mismatch would otherwise surface as an opaque driver error.
        Raising here turns that into a message naming both dimensions.

        On other dialects the column is JSON and imposes no dimension, so this type imposes
        none either. That is not a gap in the production guarantee: on PostgreSQL the column
        type rejects a wrong-dimension vector regardless of what Python does, which
        `tests/integration/test_pgvector_dimension.py` proves against a live database. It is
        a deliberate choice not to simulate that constraint on SQLite, where the existing
        single-document retrieval suite uses short, hand-readable vectors (`[1.0, 0.0]`) to
        make cosine ordering legible.
        """
        if value is None:
            return None
        if not isinstance(value, (list, tuple)):
            raise TypeError(
                f"Embedding vector must be a list or tuple of numbers, got {type(value).__name__}"
            )
        for elem in value:
            if isinstance(elem, bool) or not isinstance(elem, (int, float)):
                raise TypeError(
                    f"Embedding vector elements must be real numbers, got {type(elem).__name__}"
                )
        if dialect.name == "postgresql" and len(value) != self.dim:
            raise ValueError(
                f"Embedding vector dimension mismatch: expected {self.dim}, got {len(value)}"
            )
        return [float(x) for x in value]

    def process_result_value(self, value: Any, dialect: Dialect) -> list[float] | None:
        if value is None:
            return None
        if hasattr(value, "tolist") and callable(value.tolist):
            value = value.tolist()
        if isinstance(value, (list, tuple)):
            return [float(x) for x in value]
        raise TypeError(
            f"Cannot convert result value of type {type(value).__name__} to list[float]"
        )
