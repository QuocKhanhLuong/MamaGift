"""Frozen schemas for grounded single-document question answering."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class RetrievalRef(BaseModel):
    """Identity of the bounded retrieval request used for an answer."""

    model_config = ConfigDict(extra="forbid")

    query_id: str


class ModelRef(BaseModel):
    """Provider/model provenance for a generated answer."""

    model_config = ConfigDict(extra="forbid")

    provider: str
    model: str
    version: str


class Citation(BaseModel):
    """A citation whose id must resolve to one item in the request evidence."""

    model_config = ConfigDict(extra="forbid")

    citation_id: str
    document_id: str
    page_number: int
    block_ids: list[str]
    quote: str | None = None


class QaAnswer(BaseModel):
    """Validated, provenance-preserving answer returned by the QA service."""

    model_config = ConfigDict(extra="forbid")

    answer: str
    status: Literal["answered", "insufficient_evidence", "ai_worker_unavailable", "failed"]
    citations: list[Citation]
    retrieval: RetrievalRef
    model: ModelRef


__all__ = ["Citation", "ModelRef", "QaAnswer", "RetrievalRef"]
