"""Deterministic chunk builders over `CanonicalDocument` (Phase 3.5)."""

from .legal import build_legal_chunks
from .plan import build_plan_chunks

__all__ = [
    "build_legal_chunks",
    "build_plan_chunks",
]
