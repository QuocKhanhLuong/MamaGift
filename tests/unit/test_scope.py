"""Tests for the Phase 3.5 provider-neutral evidence/retrieval scope contract."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from mamagift_retrieval.scope import (
    EvidenceScope,
    EvidenceSource,
    authority_rank,
    resolve_conflict,
    scope_matches,
)

pytestmark = pytest.mark.unit


def test_authority_order_is_document_over_archive_over_user_over_episodic() -> None:
    assert authority_rank(EvidenceSource.VERIFIED_DOCUMENT_VERSION) < authority_rank(
        EvidenceSource.ARCHIVE_EVIDENCE
    )
    assert authority_rank(EvidenceSource.ARCHIVE_EVIDENCE) < authority_rank(
        EvidenceSource.USER_MEMORY
    )
    assert authority_rank(EvidenceSource.USER_MEMORY) < authority_rank(
        EvidenceSource.EPISODIC_MEMORY
    )


def test_resolve_conflict_never_lets_memory_beat_a_verified_document() -> None:
    winner = resolve_conflict(
        EvidenceSource.EPISODIC_MEMORY, EvidenceSource.VERIFIED_DOCUMENT_VERSION
    )
    assert winner == EvidenceSource.VERIFIED_DOCUMENT_VERSION

    winner = resolve_conflict(EvidenceSource.USER_MEMORY, EvidenceSource.ARCHIVE_EVIDENCE)
    assert winner == EvidenceSource.ARCHIVE_EVIDENCE


def test_scope_requires_family_id() -> None:
    with pytest.raises(ValidationError):
        EvidenceScope(family_id="")


def test_scope_matches_same_document_and_version() -> None:
    allowed = EvidenceScope(family_id="fam_1", document_id="doc_1", document_version=2)
    candidate = EvidenceScope(family_id="fam_1", document_id="doc_1", document_version=2)
    assert scope_matches(candidate, allowed) is True


def test_scope_rejects_different_document_even_in_same_family() -> None:
    allowed = EvidenceScope(family_id="fam_1", document_id="doc_1")
    candidate = EvidenceScope(family_id="fam_1", document_id="doc_2")
    assert scope_matches(candidate, allowed) is False


def test_scope_rejects_different_family_even_with_same_document_id() -> None:
    allowed = EvidenceScope(family_id="fam_1", document_id="doc_1")
    candidate = EvidenceScope(family_id="fam_2", document_id="doc_1")
    assert scope_matches(candidate, allowed) is False


def test_scope_rejects_stale_version_when_caller_pinned_one() -> None:
    allowed = EvidenceScope(family_id="fam_1", document_id="doc_1", document_version=3)
    candidate = EvidenceScope(family_id="fam_1", document_id="doc_1", document_version=2)
    assert scope_matches(candidate, allowed) is False


def test_archive_scope_permits_any_document_within_the_family() -> None:
    allowed = EvidenceScope(family_id="fam_1", archive_scope=True)
    candidate = EvidenceScope(family_id="fam_1", document_id="doc_99")
    assert scope_matches(candidate, allowed) is True


def test_archive_scope_still_rejects_a_different_family() -> None:
    allowed = EvidenceScope(family_id="fam_1", archive_scope=True)
    candidate = EvidenceScope(family_id="fam_2", document_id="doc_99")
    assert scope_matches(candidate, allowed) is False


def test_scope_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError):
        EvidenceScope(family_id="fam_1", not_a_real_field="x")  # type: ignore[call-arg]
