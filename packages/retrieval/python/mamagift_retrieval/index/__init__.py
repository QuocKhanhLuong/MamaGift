"""Single-document version-keyed DocumentIndex interface and SQL implementation."""

from __future__ import annotations

from .entries import IndexEntry, IndexStats, ScoredChunk
from .protocol import AUTHORITATIVE_FAMILY_ID, DocumentIndex
from .sql_index import SqlDocumentIndex

__all__ = [
    "AUTHORITATIVE_FAMILY_ID",
    "DocumentIndex",
    "IndexEntry",
    "IndexStats",
    "ScoredChunk",
    "SqlDocumentIndex",
]
