"""Data transfer objects for DocumentIndex."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from mamagift_retrieval.chunk import Chunk


class IndexEntry(BaseModel):
    """One chunk prepared for indexing, with its positional index and optional embedding."""

    model_config = ConfigDict(extra="forbid")

    chunk: Chunk
    chunk_index: int = Field(
        default=0, ge=0, description="0-based sequence index within the parse run."
    )
    token_count: int = Field(default=0, ge=0, description="Token or approximate word count.")
    embedding: list[float] | None = Field(
        default=None, description="Dense embedding vector if computed."
    )
    embedding_model: str | None = Field(default=None, description="Embedding model identifier.")
    embedding_version: str | None = Field(
        default=None, description="Version string of the embedding model."
    )


class IndexStats(BaseModel):
    """Statistics for an indexed document version / parse run."""

    model_config = ConfigDict(extra="forbid")

    document_id: str
    parse_run_id: str
    document_version: int | None = None
    total_chunks: int = 0
    embedded_chunks: int = 0
    embedding_model: str | None = None
    embedding_version: str | None = None


class ScoredChunk(BaseModel):
    """A retrieved chunk paired with its score, 1-based rank, and retriever origin."""

    model_config = ConfigDict(extra="forbid")

    chunk: Chunk
    score: float
    rank: int = Field(ge=1, description="1-based rank within retriever results.")
    retriever: Literal["lexical", "dense", "fused", "reranked"]
