"""Shared typed contracts for the Phase 0 fake AI-worker boundary."""

from .worker import (
    ParseJobAccepted,
    ParseJobInput,
    ParseJobRequest,
    ParserSpec,
    WorkerCapabilities,
    WorkerHealth,
)

__all__ = [
    "ParseJobAccepted",
    "ParseJobInput",
    "ParseJobRequest",
    "ParserSpec",
    "WorkerCapabilities",
    "WorkerHealth",
]
