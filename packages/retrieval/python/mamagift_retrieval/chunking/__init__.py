"""Deterministic chunk builders over `CanonicalDocument` (Phase 3.5)."""

from .fallback import build_fallback_chunks
from .legal import build_legal_chunks

__all__ = [
    "build_fallback_chunks",
    "build_legal_chunks",
]
