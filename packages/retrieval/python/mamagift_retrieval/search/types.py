"""Ranking contract re-exports for the search package.

`ScoredChunk` is frozen in the Phase 4 plan section 3.3 and has exactly ONE
definition, in `mamagift_retrieval.index.entries`. Tasks C1 and C2 each declared
a local copy on their own branches; two structurally identical Pydantic models
are still different runtime types, so isinstance checks and `extra="forbid"`
validation would disagree across the fusion boundary. This module re-exports the
single definition so both retrievers and Task C3's fusion share one type.
"""

from __future__ import annotations

from mamagift_retrieval.index.entries import ScoredChunk

__all__ = ["ScoredChunk"]
