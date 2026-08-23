"""Evidence expansion and assembly helpers."""

from __future__ import annotations

from .expansion import (
    DEFAULT_MAX_ANCESTOR_DEPTH,
    MAX_ANCESTOR_DEPTH,
    expand_evidence,
)

__all__ = [
    "DEFAULT_MAX_ANCESTOR_DEPTH",
    "MAX_ANCESTOR_DEPTH",
    "expand_evidence",
]
