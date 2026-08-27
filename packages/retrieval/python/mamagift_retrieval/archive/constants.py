"""Frozen tuning constants for archive-scoped retrieval.

`RRF_K` is deliberately absent: archive fusion imports the single definition from
`mamagift_retrieval.search.fusion` so document-scoped and archive-scoped fusion can never
drift apart. The same applies to the BM25 hyperparameters, which come from
`mamagift_retrieval.search.lexical`.
"""

from __future__ import annotations

EMBEDDING_DIM = 1024
"""Verified against BgeM3EmbeddingProvider and FakeEmbeddingProvider."""

ARCHIVE_LEXICAL_TOP_K = 50
ARCHIVE_DENSE_TOP_K = 50
ARCHIVE_RERANK_TOP_K = 12

ARCHIVE_MAX_DOCUMENTS = 8
"""Distinct documents allowed into one evidence set.

A cap exists so a broad question cannot assemble evidence from the whole archive; the
per-document cap below then stops any single document consuming the shared budget.
"""

ARCHIVE_PER_DOCUMENT_CHAR_CAP = 3_000
ARCHIVE_EVIDENCE_BUDGET_CHARS = 16_000

__all__ = [
    "ARCHIVE_DENSE_TOP_K",
    "ARCHIVE_EVIDENCE_BUDGET_CHARS",
    "ARCHIVE_LEXICAL_TOP_K",
    "ARCHIVE_MAX_DOCUMENTS",
    "ARCHIVE_PER_DOCUMENT_CHAR_CAP",
    "ARCHIVE_RERANK_TOP_K",
    "EMBEDDING_DIM",
]
