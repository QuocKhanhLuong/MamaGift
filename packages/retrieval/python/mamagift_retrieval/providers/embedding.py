"""Embedding provider protocol and contract definitions."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from mamagift_contracts.embedding import EmbeddingResult


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Protocol for text embedding providers (dense retrieval and document indexing).

    `embedding_version` is load-bearing: it is persisted with every chunk row in the
    database (see Phase 4 plan §3.6) and a change to it must force a reindex. It must
    change whenever the underlying embedding model, weights, dimension, truncation,
    or embedding semantics change.
    """

    @property
    def model_id(self) -> str:
        """Identifier of the embedding model (e.g. 'bge-m3', 'fake-bge-m3')."""
        ...

    @property
    def dimension(self) -> int:
        """Dimensionality of the generated embedding vectors (e.g. 1024)."""
        ...

    @property
    def embedding_version(self) -> str:
        """Version string of the embedding configuration. Persisted with each chunk."""
        ...

    async def embed_documents(self, texts: list[str]) -> EmbeddingResult:
        """Embed a sequence of document texts/chunks into dense vectors.

        Batch behavior requirement:
        Embedding N texts must return exactly N vectors in the SAME order.
        """
        ...

    async def embed_query(self, text: str) -> EmbeddingResult:
        """Embed a single search query text into a dense vector."""
        ...
