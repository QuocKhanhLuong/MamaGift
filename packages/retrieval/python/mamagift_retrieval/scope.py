"""Provider-neutral retrieval/evidence scope and authority contract (Phase 3.5).

Phase 3.5 introduces the scope concepts a later retrieval/memory layer must respect,
without implementing that layer. Nothing here talks to Zep, a vector store, or any
memory backend (docs/09_CODEX_EXECUTION.md non-goals for this phase).

Authority order, most to least authoritative, is fixed and load-bearing:

    verified current DocumentVersion
    > archive/document evidence
    > user/episodic memory

A verified document fact must never be silently overridden by memory.
`resolve_conflict` is the single place that encodes this rule so a later memory
integration cannot accidentally invert it.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class EvidenceSource(StrEnum):
    """Where a candidate fact/answer came from, ordered by authority below."""

    VERIFIED_DOCUMENT_VERSION = "verified_document_version"
    ARCHIVE_EVIDENCE = "archive_evidence"
    USER_MEMORY = "user_memory"
    EPISODIC_MEMORY = "episodic_memory"


# Lower number = higher authority. A verified current DocumentVersion always wins;
# episodic memory always loses when it conflicts with any document evidence.
_AUTHORITY_RANK: dict[EvidenceSource, int] = {
    EvidenceSource.VERIFIED_DOCUMENT_VERSION: 0,
    EvidenceSource.ARCHIVE_EVIDENCE: 1,
    EvidenceSource.USER_MEMORY: 2,
    EvidenceSource.EPISODIC_MEMORY: 3,
}


def authority_rank(source: EvidenceSource) -> int:
    return _AUTHORITY_RANK[source]


def resolve_conflict(a: EvidenceSource, b: EvidenceSource) -> EvidenceSource:
    """Return whichever source outranks the other.

    Ties are impossible: every `EvidenceSource` has a distinct rank.
    """
    return a if authority_rank(a) < authority_rank(b) else b


class EvidenceScope(BaseModel):
    """The provider-neutral addressing scope for a piece of retrievable evidence.

    Every field is optional except `family_id`: document-scoped evidence should also
    carry `document_id`; archive-scoped evidence may span many documents within one
    `family_id` and therefore leaves it unset.
    """

    model_config = ConfigDict(extra="forbid")

    family_id: str = Field(min_length=1)
    user_id: str | None = None
    thread_id: str | None = None
    document_id: str | None = None
    document_version: int | None = Field(default=None, ge=1)
    parse_run_id: str | None = None
    archive_scope: bool = False


def scope_matches(candidate: EvidenceScope, allowed: EvidenceScope) -> bool:
    """Whether `candidate` evidence may be used to answer a request scoped to `allowed`.

    A leak is any candidate whose family/document/version does not match the allowed
    scope. `archive_scope=True` on `allowed` permits any document within the family;
    otherwise the candidate must name the same `document_id` (and, when the caller
    pinned a version, the same `document_version`).
    """
    if candidate.family_id != allowed.family_id:
        return False
    if allowed.user_id is not None and candidate.user_id not in (None, allowed.user_id):
        return False
    if allowed.archive_scope:
        return True
    if allowed.document_id is None:
        return True
    if candidate.document_id != allowed.document_id:
        return False
    if allowed.document_version is not None and candidate.document_version not in (
        None,
        allowed.document_version,
    ):
        return False
    return True
