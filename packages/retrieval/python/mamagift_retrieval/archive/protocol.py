"""Archive-scoped retrieval contract: many CURRENT documents, never one pinned document.

This is the deliberate counterpart to `mamagift_retrieval.index.DocumentIndex`, not a
generalisation of it. The two have mutually exclusive scope guards:

- `DocumentIndex` requires `document_id` and refuses `archive_scope=True`;
- `ArchiveIndex` requires `archive_scope=True` and refuses a pinned `document_id`,
  `parse_run_id` or `document_version`.

Selected-document QA therefore cannot reach archive retrieval, and archive QA cannot quietly
collapse into "one global DocumentIndex". Both directions are tested.

Current-version isolation is an invariant of every implementation, not a filter: an
implementation MUST build its candidate set from chunks whose parse run satisfies BOTH
`parse_runs.is_current` AND `documents.current_parse_run_id = parse_runs.id`. Two independent
facts must agree; a row satisfying only one is excluded. No parameter relaxes this.
"""

from __future__ import annotations

from datetime import date
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from mamagift_retrieval.index.entries import ScoredChunk
from mamagift_retrieval.index.protocol import AUTHORITATIVE_FAMILY_ID
from mamagift_retrieval.scope import EvidenceScope

from .filters import ArchiveFilter


class ArchiveDocumentRef(BaseModel):
    """One current document in the archive, with the relational metadata retrieval filters on."""

    model_config = ConfigDict(extra="forbid")

    document_id: str = Field(min_length=1)
    parse_run_id: str = Field(min_length=1)
    document_version: int = Field(ge=1)
    document_type: str | None = None
    document_number: str | None = None
    title: str | None = None
    issuer: str | None = None
    issued_date: date | None = None
    requires_user_review: bool = False


class ArchiveIndexStats(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_documents: int = 0
    total_chunks: int = 0
    embedded_chunks: int = 0
    embedding_model: str | None = None
    embedding_version: str | None = None


def validate_archive_scope(scope: EvidenceScope) -> None:
    """Reject any scope that is not a genuine archive wildcard.

    Refusing a pinned `document_id` is what keeps `ArchiveIndex` from being used as a
    back-door single-document index with different (weaker) provenance checks.
    """
    if not scope.family_id:
        raise ValueError("scope must specify family_id")
    if scope.family_id != AUTHORITATIVE_FAMILY_ID:
        raise ValueError(
            f"scope family_id {scope.family_id!r} is not authoritative; "
            f"expected {AUTHORITATIVE_FAMILY_ID!r}"
        )
    if not scope.archive_scope:
        raise ValueError("archive index requires an archive scope (archive_scope=True)")
    if scope.document_id is not None:
        raise ValueError(
            "archive scope must not pin document_id; use DocumentIndex for one document"
        )
    if scope.parse_run_id is not None:
        raise ValueError("archive scope must not pin parse_run_id")
    if scope.document_version is not None:
        raise ValueError("archive scope must not pin document_version")


@runtime_checkable
class ArchiveIndex(Protocol):
    """Retrieval across the current version of every document in one family.

    Every method takes an `EvidenceScope` and MUST validate it with `validate_archive_scope`
    internally. Scope and current-version filtering are never the caller's job.
    """

    def current_documents(
        self, scope: EvidenceScope, filters: ArchiveFilter | None = None
    ) -> list[ArchiveDocumentRef]:
        """Every current document matching `filters`, ordered by document_id ascending."""
        ...

    def search_dense(
        self,
        scope: EvidenceScope,
        query_vector: list[float],
        top_k: int,
        filters: ArchiveFilter | None = None,
    ) -> list[ScoredChunk]:
        """Exact vector search over current-version chunks, ranked 1-based, descending score."""
        ...

    def search_lexical(
        self,
        scope: EvidenceScope,
        query: str,
        top_k: int,
        filters: ArchiveFilter | None = None,
    ) -> list[ScoredChunk]:
        """BM25 search over current-version chunks, ranked 1-based, descending score."""
        ...

    def stats(
        self, scope: EvidenceScope, filters: ArchiveFilter | None = None
    ) -> ArchiveIndexStats:
        """Counts for the current-version corpus matching `filters`."""
        ...


__all__ = [
    "AUTHORITATIVE_FAMILY_ID",
    "ArchiveDocumentRef",
    "ArchiveIndex",
    "ArchiveIndexStats",
    "validate_archive_scope",
]
