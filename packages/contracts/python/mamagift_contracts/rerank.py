"""Typed contracts for candidate reranking."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class RerankItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index: int = Field(..., ge=0, description="0-based index of the candidate in the input list.")
    score: float = Field(..., description="Relevance score computed by the reranker.")
    text: str | None = Field(default=None, description="Optional text content of the candidate.")


class RerankRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(..., min_length=1, description="Query string to score candidates against.")
    documents: list[str] = Field(..., description="List of document text candidates.")
    top_k: int | None = Field(
        default=None, ge=1, description="Optional limit on returned candidates."
    )
    model: str | None = Field(default=None, description="Optional reranker model identifier.")


class RerankResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    results: list[RerankItem] = Field(default_factory=list, description="Reranked candidate items.")
    model: str = Field(..., description="Identifier of the reranker model used.")
    reranker_version: str | None = Field(
        default=None, description="Version string of the reranker."
    )
