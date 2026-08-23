"""Bound retrieved chunks into provenance-preserving evidence for a request."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from mamagift_retrieval.budget import (
    BudgetBreakdown,
    EvidenceBudget,
    assemble_bounded_context,
)
from mamagift_retrieval.scope import EvidenceScope, scope_matches
from mamagift_retrieval.search.types import ScoredChunk


class Evidence(BaseModel):
    """One bounded, citeable chunk and its source provenance."""

    model_config = ConfigDict(extra="forbid")

    citation_id: str = Field(min_length=1)
    chunk_id: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    parse_run_id: str = Field(min_length=1)
    document_version: int = Field(ge=1)
    page_numbers: list[int]
    source_block_ids: list[str]
    section_path: list[str]
    text: str


class EvidenceSet(BaseModel):
    """The bounded evidence allow-list consumed by grounded generation."""

    model_config = ConfigDict(extra="forbid")

    scope: EvidenceScope
    evidence: list[Evidence]
    budget: BudgetBreakdown
    query_id: str


def assemble_evidence(
    candidates: list[ScoredChunk],
    *,
    scope: EvidenceScope,
    budget: EvidenceBudget,
    query_id: str,
) -> EvidenceSet:
    """Create a bounded, ordered evidence set from scoped retrieval candidates.

    Candidate order is the final evidence order, so citation identifiers are
    deterministic for a request.  The Phase 3.5 assembler is deliberately used
    for the character cap and its complete category breakdown; the selected
    document text is then split back across candidates in the same order.
    """
    candidate_texts: list[str] = []
    validated_candidates: list[tuple[ScoredChunk, int]] = []
    seen_chunk_ids: set[str] = set()
    for candidate in candidates:
        chunk = candidate.chunk
        if chunk.chunk_id in seen_chunk_ids:
            raise ValueError(f"duplicate evidence chunk_id {chunk.chunk_id!r}")
        seen_chunk_ids.add(chunk.chunk_id)

        candidate_scope = EvidenceScope(
            family_id=scope.family_id,
            document_id=chunk.document_id,
            document_version=chunk.document_version,
            parse_run_id=chunk.parse_run_id,
            user_id=scope.user_id,
            thread_id=scope.thread_id,
        )
        if not scope_matches(candidate_scope, scope):
            raise ValueError(f"candidate chunk {chunk.chunk_id!r} violates requested EvidenceScope")
        if chunk.document_version is None:
            raise ValueError(
                f"candidate chunk {chunk.chunk_id!r} has no document_version provenance"
            )
        candidate_texts.append(chunk.text)
        validated_candidates.append((candidate, chunk.document_version))

    offered_text = "".join(candidate_texts)
    bounded, breakdown = assemble_bounded_context(
        budget,
        {"selected_document": offered_text},
    )
    bounded_text = bounded["selected_document"]

    evidence: list[Evidence] = []
    offset = 0
    for index, (candidate, document_version) in enumerate(validated_candidates, start=1):
        chunk = candidate.chunk
        end = min(offset + len(chunk.text), len(bounded_text))
        evidence.append(
            Evidence(
                citation_id=f"c{index}",
                chunk_id=chunk.chunk_id,
                document_id=chunk.document_id,
                parse_run_id=chunk.parse_run_id,
                document_version=document_version,
                page_numbers=list(chunk.source_page_numbers),
                source_block_ids=list(chunk.source_block_ids),
                section_path=list(chunk.section_path),
                text=bounded_text[offset:end],
            )
        )
        offset += len(chunk.text)

    return EvidenceSet(
        scope=scope,
        evidence=evidence,
        budget=breakdown,
        query_id=query_id,
    )


__all__ = ["Evidence", "EvidenceSet", "assemble_evidence"]
