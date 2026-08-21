"""Typed contracts for document and query embeddings."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class EmbeddingResult(BaseModel):
    """Result of embedding one or more text inputs.

    `embedding_version` is persisted with every chunk. A change to `embedding_version`
    must force a reindex.
    """

    model_config = ConfigDict(extra="forbid")

    vectors: list[list[float]] = Field(
        ...,
        description="List of embedding vectors, each vector being a list of floats.",
    )
    model: str = Field(..., description="Identifier of the embedding model used.")
    dimension: int = Field(..., description="Dimension of each embedding vector.")
    embedding_version: str = Field(
        ...,
        description=(
            "Version string of the embedding model and configuration. "
            "Persisted with each chunk; a change forces a reindex."
        ),
    )
