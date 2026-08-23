"""Single-document version-keyed DocumentIndex interface and SQL implementation."""

from __future__ import annotations

from .entries import IndexEntry, IndexStats, ScoredChunk
from .protocol import DocumentIndex
from .sql_index import SqlDocumentIndex

__all__ = [
    "DocumentIndex",
    "IndexEntry",
    "IndexStats",
    "ScoredChunk",
    "SqlDocumentIndex",
]
