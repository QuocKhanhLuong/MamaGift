"""Sanitized multi-document archive evaluation corpus and fixtures."""

from __future__ import annotations

from .corpus import (
    ARCHIVE_CORPUS,
    ArchiveFixtureDocument,
    build_canonical,
    seed_archive,
)

__all__ = [
    "ARCHIVE_CORPUS",
    "ArchiveFixtureDocument",
    "build_canonical",
    "seed_archive",
]
