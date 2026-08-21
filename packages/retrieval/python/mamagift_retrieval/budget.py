"""Context/evidence budget contract (Phase 3.5).

Borrows the *principle* from Lab 17 — bound every context category instead of
concatenating unlimited evidence — without its exact percentages, and without any
production memory implementation. Every category is measured in characters (not
tokens/model-specific units) so the contract stays provider-neutral; a later
integration may swap the unit without changing this shape.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

_CATEGORIES = (
    "selected_document",
    "conversation_short_term",
    "user_long_term_memory",
    "episodic_memory",
    "archive_semantic",
)


class EvidenceBudget(BaseModel):
    """Configurable per-category character budgets for a future assembled context.

    Categories mirror the sources named in the Phase 3.5 goal: the currently
    selected document's own evidence, short-term conversation turns, user
    long-term memory, episodic memory and archive-wide semantic evidence. No
    category has a hard-coded default ratio; callers must set values deliberately.
    """

    model_config = ConfigDict(extra="forbid")

    selected_document_chars: int = Field(ge=0)
    conversation_short_term_chars: int = Field(ge=0)
    user_long_term_memory_chars: int = Field(ge=0)
    episodic_memory_chars: int = Field(ge=0)
    archive_semantic_chars: int = Field(ge=0)

    def total_chars(self) -> int:
        return (
            self.selected_document_chars
            + self.conversation_short_term_chars
            + self.user_long_term_memory_chars
            + self.episodic_memory_chars
            + self.archive_semantic_chars
        )


class BudgetCategoryUsage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: str
    budget_chars: int = Field(ge=0)
    offered_chars: int = Field(ge=0)
    used_chars: int = Field(ge=0)
    truncated: bool


class BudgetBreakdown(BaseModel):
    """Debug-visible record of what was offered vs. what actually fit each category."""

    model_config = ConfigDict(extra="forbid")

    categories: list[BudgetCategoryUsage]

    def total_used_chars(self) -> int:
        return sum(item.used_chars for item in self.categories)


def assemble_bounded_context(
    budget: EvidenceBudget, offered: dict[str, str]
) -> tuple[dict[str, str], BudgetBreakdown]:
    """Truncate each named category to its configured budget deterministically.

    `offered` keys must be a subset of the five budget category names (the field
    name without its `_chars` suffix, e.g. `"selected_document"`). Truncation is a
    plain left-to-right character cut — no summarization, no random sampling — so
    results are reproducible and debuggable via the returned `BudgetBreakdown`.
    Categories are never concatenated together: each stays keyed and bounded on its
    own.
    """
    limits = {
        "selected_document": budget.selected_document_chars,
        "conversation_short_term": budget.conversation_short_term_chars,
        "user_long_term_memory": budget.user_long_term_memory_chars,
        "episodic_memory": budget.episodic_memory_chars,
        "archive_semantic": budget.archive_semantic_chars,
    }
    unknown = set(offered) - set(limits)
    if unknown:
        raise ValueError(f"unknown budget category/categories: {sorted(unknown)}")

    bounded: dict[str, str] = {}
    usage: list[BudgetCategoryUsage] = []
    for category in _CATEGORIES:
        limit = limits[category]
        text = offered.get(category, "")
        used_text = text[:limit]
        bounded[category] = used_text
        usage.append(
            BudgetCategoryUsage(
                category=category,
                budget_chars=limit,
                offered_chars=len(text),
                used_chars=len(used_text),
                truncated=len(used_text) < len(text),
            )
        )
    return bounded, BudgetBreakdown(categories=usage)
