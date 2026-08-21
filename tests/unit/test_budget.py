"""Tests for the Phase 3.5 context/evidence budget contract.

Borrows the *principle* from Lab 17 — bound every context category instead of
concatenating unlimited evidence — without its exact percentages, and without any
production memory implementation.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from mamagift_retrieval.budget import (
    BudgetBreakdown,
    BudgetCategoryUsage,
    EvidenceBudget,
    assemble_bounded_context,
)

pytestmark = pytest.mark.unit


def _budget() -> EvidenceBudget:
    return EvidenceBudget(
        selected_document_chars=20,
        conversation_short_term_chars=10,
        user_long_term_memory_chars=5,
        episodic_memory_chars=5,
        archive_semantic_chars=15,
    )


@pytest.mark.parametrize(
    "field",
    [
        "selected_document_chars",
        "conversation_short_term_chars",
        "user_long_term_memory_chars",
        "episodic_memory_chars",
        "archive_semantic_chars",
    ],
)
def test_budget_rejects_negative_values(field: str) -> None:
    kwargs = {
        "selected_document_chars": 0,
        "conversation_short_term_chars": 0,
        "user_long_term_memory_chars": 0,
        "episodic_memory_chars": 0,
        "archive_semantic_chars": 0,
    }
    kwargs[field] = -1
    with pytest.raises(ValidationError):
        EvidenceBudget(**kwargs)


@pytest.mark.parametrize(
    "field",
    [
        "budget_chars",
        "offered_chars",
        "used_chars",
    ],
)
def test_budget_category_usage_rejects_negative_values(field: str) -> None:
    kwargs = {
        "category": "selected_document",
        "budget_chars": 10,
        "offered_chars": 10,
        "used_chars": 10,
        "truncated": False,
    }
    kwargs[field] = -1
    with pytest.raises(ValidationError):
        BudgetCategoryUsage(**kwargs)


def test_evidence_budget_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError):
        EvidenceBudget(
            selected_document_chars=10,
            conversation_short_term_chars=10,
            user_long_term_memory_chars=10,
            episodic_memory_chars=10,
            archive_semantic_chars=10,
            unknown_field="unexpected",  # type: ignore[call-arg]
        )


def test_budget_category_usage_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError):
        BudgetCategoryUsage(
            category="selected_document",
            budget_chars=10,
            offered_chars=10,
            used_chars=10,
            truncated=False,
            unknown_field="unexpected",  # type: ignore[call-arg]
        )


def test_budget_breakdown_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError):
        BudgetBreakdown(
            categories=[],
            unknown_field="unexpected",  # type: ignore[call-arg]
        )


def test_total_chars_sums_every_category() -> None:
    assert _budget().total_chars() == 55


def test_assemble_bounded_context_truncates_over_budget_categories() -> None:
    offered = {"selected_document": "x" * 30, "conversation_short_term": "y" * 3}
    bounded, breakdown = assemble_bounded_context(_budget(), offered)
    assert bounded["selected_document"] == "x" * 20
    assert bounded["conversation_short_term"] == "y" * 3

    by_category = {item.category: item for item in breakdown.categories}
    assert by_category["selected_document"].offered_chars == 30
    assert by_category["selected_document"].used_chars == 20
    assert by_category["selected_document"].truncated is True
    assert by_category["conversation_short_term"].offered_chars == 3
    assert by_category["conversation_short_term"].used_chars == 3
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
    assert by_category["episodic_memory"].truncated is False


def test_offered_none_value_treated_as_empty() -> None:
    bounded, breakdown = assemble_bounded_context(
        _budget(),
        {"selected_document": None, "archive_semantic": "B" * 5},  # type: ignore[dict-item]
    )
    assert bounded["selected_document"] == ""
    assert bounded["archive_semantic"] == "B" * 5
    by_category = {item.category: item for item in breakdown.categories}
    assert by_category["selected_document"].offered_chars == 0
    assert by_category["selected_document"].used_chars == 0
    assert by_category["selected_document"].truncated is False
    assert by_category["archive_semantic"].offered_chars == 5
    assert by_category["archive_semantic"].used_chars == 5
    assert by_category["archive_semantic"].truncated is False


def test_offered_non_string_non_none_rejected() -> None:
    with pytest.raises(TypeError, match="must be str or None"):
        assemble_bounded_context(_budget(), {"selected_document": 123})  # type: ignore[dict-item]


def test_unknown_category_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown budget category"):
        assemble_bounded_context(_budget(), {"not_a_real_category": "x"})


def test_breakdown_total_used_chars_matches_bounded_output() -> None:
    offered = {"selected_document": "x" * 30}
    bounded, breakdown = assemble_bounded_context(_budget(), offered)
    assert breakdown.total_used_chars() == sum(len(text) for text in bounded.values())
    by_category = {item.category: item for item in breakdown.categories}
    assert by_category["selected_document"].offered_chars == 30
    assert by_category["selected_document"].used_chars == 20
