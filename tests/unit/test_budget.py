"""Tests for the Phase 3.5 context/evidence budget contract.

Borrows the *principle* from Lab 17 — bound every context category instead of
concatenating unlimited evidence — without its exact percentages, and without any
production memory implementation.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from mamagift_retrieval.budget import EvidenceBudget, assemble_bounded_context

pytestmark = pytest.mark.unit


def _budget() -> EvidenceBudget:
    return EvidenceBudget(
        selected_document_chars=20,
        conversation_short_term_chars=10,
        user_long_term_memory_chars=5,
        episodic_memory_chars=5,
        archive_semantic_chars=15,
    )


def test_budget_rejects_negative_values() -> None:
    with pytest.raises(ValidationError):
        EvidenceBudget(
            selected_document_chars=-1,
            conversation_short_term_chars=0,
            user_long_term_memory_chars=0,
            episodic_memory_chars=0,
            archive_semantic_chars=0,
        )


def test_total_chars_sums_every_category() -> None:
    assert _budget().total_chars() == 55


def test_assemble_bounded_context_truncates_over_budget_categories() -> None:
    offered = {"selected_document": "x" * 30, "conversation_short_term": "y" * 3}
    bounded, breakdown = assemble_bounded_context(_budget(), offered)
    assert bounded["selected_document"] == "x" * 20
    assert bounded["conversation_short_term"] == "y" * 3

    by_category = {item.category: item for item in breakdown.categories}
    assert by_category["selected_document"].truncated is True
    assert by_category["selected_document"].used_chars == 20
    assert by_category["conversation_short_term"].truncated is False


def test_assemble_bounded_context_never_concatenates_categories_together() -> None:
    offered = {"selected_document": "A" * 5, "archive_semantic": "B" * 5}
    bounded, _ = assemble_bounded_context(_budget(), offered)
    assert "B" not in bounded["selected_document"]
    assert "A" not in bounded["archive_semantic"]


def test_unset_category_defaults_to_empty_and_is_reported() -> None:
    bounded, breakdown = assemble_bounded_context(_budget(), {})
    assert bounded["user_long_term_memory"] == ""
    by_category = {item.category: item for item in breakdown.categories}
    assert by_category["episodic_memory"].offered_chars == 0
    assert by_category["episodic_memory"].used_chars == 0


def test_unknown_category_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown budget category"):
        assemble_bounded_context(_budget(), {"not_a_real_category": "x"})


def test_breakdown_total_used_chars_matches_bounded_output() -> None:
    offered = {"selected_document": "x" * 30}
    bounded, breakdown = assemble_bounded_context(_budget(), offered)
    assert breakdown.total_used_chars() == sum(len(text) for text in bounded.values())
