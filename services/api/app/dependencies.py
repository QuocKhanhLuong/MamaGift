"""Shared FastAPI dependencies."""

from __future__ import annotations

from functools import lru_cache

from .settings import Settings, get_settings
from .storage import LocalObjectStorage, ObjectStorage


@lru_cache(maxsize=1)
def get_storage() -> ObjectStorage:
    settings: Settings = get_settings()
    return LocalObjectStorage(settings.storage_root)
