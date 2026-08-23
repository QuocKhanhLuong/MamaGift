"""Search and retrieval modules for single-document RAG."""

from __future__ import annotations

from .dense import DenseRetriever, EmbeddingVersionMismatchError
from .types import ScoredChunk

__all__ = [
    "DenseRetriever",
    "EmbeddingVersionMismatchError",
    "ScoredChunk",
]
