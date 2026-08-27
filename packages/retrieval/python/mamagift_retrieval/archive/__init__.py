"""Archive-scoped retrieval: many current documents, as opposed to one pinned document."""

from __future__ import annotations

from .constants import (
    ARCHIVE_DENSE_TOP_K,
    ARCHIVE_EVIDENCE_BUDGET_CHARS,
    ARCHIVE_LEXICAL_TOP_K,
    ARCHIVE_MAX_DOCUMENTS,
    ARCHIVE_PER_DOCUMENT_CHAR_CAP,
    ARCHIVE_RERANK_TOP_K,
    EMBEDDING_DIM,
)
from .filters import ArchiveFilter, normalize_identifier
from .protocol import (
    ArchiveDocumentRef,
    ArchiveIndex,
    ArchiveIndexStats,
    validate_archive_scope,
)

__all__ = [
    "ARCHIVE_DENSE_TOP_K",
    "ARCHIVE_EVIDENCE_BUDGET_CHARS",
    "ARCHIVE_LEXICAL_TOP_K",
    "ARCHIVE_MAX_DOCUMENTS",
    "ARCHIVE_PER_DOCUMENT_CHAR_CAP",
    "ARCHIVE_RERANK_TOP_K",
    "EMBEDDING_DIM",
    "ArchiveDocumentRef",
    "ArchiveFilter",
    "ArchiveIndex",
    "ArchiveIndexStats",
    "normalize_identifier",
    "validate_archive_scope",
]
