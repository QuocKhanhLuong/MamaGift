"""Deterministic chunk builders over `CanonicalDocument` (Phase 3.5)."""

from .builder import build_chunks
from .fallback import build_fallback_chunks
from .legal import build_legal_chunks
from .plan import build_plan_chunks

__all__ = [
    "build_chunks",
    "build_fallback_chunks",
    "build_legal_chunks",
    "build_plan_chunks",
]
