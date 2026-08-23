"""Search package for Phase 4 single-document RAG."""

from __future__ import annotations

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
    "LexicalRetriever",
    "ScoredChunk",
    "normalize_vi_text",
    "tokenize_vi",
]
