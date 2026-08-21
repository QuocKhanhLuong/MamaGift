"""Phase 3.5 deterministic evaluation data contracts.

These are data shapes only: no LLM evaluator, RAGAS, or generation-quality scoring
is implemented here. A "case" is authored ground truth an eval runner can score
deterministic parser/chunking output against.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ExpectedTaskRelation(BaseModel):
    """One `task -> owner -> deadline` relation a plan case expects to survive
    parsing and chunking, keyed by the task's ordinal label (e.g. `"1"`, `"2.1"`)."""

    model_config = ConfigDict(extra="forbid")

    task_ordinal: str = Field(min_length=1)
    task_title: str
    owner: str | None = None
    coordinating_unit: str | None = None
    deadline: str | None = None


class ParserSemanticCase(BaseModel):
    """A deterministic parser/chunking correctness case for one document."""

    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    document_type: str = Field(min_length=1)
    expected_critical_fields: dict[str, str | None] = Field(default_factory=dict)
    expected_hierarchy_labels: list[str] = Field(default_factory=list)
    expected_task_relations: list[ExpectedTaskRelation] = Field(default_factory=list)
    expected_source_block_ids: list[str] = Field(default_factory=list)
    expected_source_page_numbers: list[int] = Field(default_factory=list)


class RetrievalQACase(BaseModel):
    """A future retrieval-QA case. Scoring an actual answer against this is Phase
    4+ work; only the data shape is defined here."""

    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1)
    question: str = Field(min_length=1)
    expected_document_ids: list[str] = Field(min_length=1)
    expected_block_ids: list[str] = Field(default_factory=list)
    expected_chunk_ids: list[str] = Field(default_factory=list)
    forbidden_document_ids: list[str] = Field(default_factory=list)
    required_metadata_scope: dict[str, str] = Field(default_factory=dict)
