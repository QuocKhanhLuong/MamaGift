"""Search types for Phase 4 retrieval."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from mamagift_retrieval.chunk import Chunk


class ScoredChunk(BaseModel):
    """A retrieved chunk paired with its score, 1-based rank, and retriever origin.

    Contract frozen in Phase 4 Plan §3.3.
    """

    model_config = ConfigDict(extra="forbid")

    chunk: Chunk
    score: float
    rank: int = Field(ge=1, description="1-based rank within retriever results.")
    retriever: Literal["lexical", "dense", "fused", "reranked"]
