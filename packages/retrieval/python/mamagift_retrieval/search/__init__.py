"""Search and retrieval over a single indexed document version (Phase 4)."""

from __future__ import annotations

from .dense import DenseRetriever, EmbeddingVersionMismatchError
from .lexical import (
    DEFAULT_BM25_B,
    DEFAULT_BM25_K1,
    BM25Index,
    BM25LexicalRetriever,
    BM25Params,
    LexicalRetriever,
)
from .types import ScoredChunk
from .vi_tokenize import normalize_vi_text, tokenize_vi

__all__ = [
    "BM25Index",
    "BM25LexicalRetriever",
    "BM25Params",
    "DEFAULT_BM25_B",
    "DEFAULT_BM25_K1",
    "DenseRetriever",
    "EmbeddingVersionMismatchError",
    "LexicalRetriever",
    "ScoredChunk",
    "normalize_vi_text",
    "tokenize_vi",
]
