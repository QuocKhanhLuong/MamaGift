"""Deterministic in-process fake for the future AI-worker boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from mamagift_contracts import (
    ParseJobAccepted,
    ParseJobRequest,
    WorkerHealth,
)
from mamagift_contracts.worker import WorkerCapabilities


class AIWorkerPort(Protocol):
    async def health(self) -> WorkerHealth:
        """Return the worker protocol health payload."""

    async def submit_parse_job(self, request: ParseJobRequest) -> ParseJobAccepted:
        """Accept a typed job without performing document intelligence."""


@dataclass(frozen=True)
class FakeAIWorker:
    """A contract-only implementation; it never parses or calls a model."""

    worker_version: str = "fake-contract-only-0.1.0"

    async def health(self) -> WorkerHealth:
        return WorkerHealth(
            status="degraded",
            worker_version=self.worker_version,
            capabilities=WorkerCapabilities(),
            models={},
        )

    async def submit_parse_job(self, request: ParseJobRequest) -> ParseJobAccepted:
        return ParseJobAccepted(
            job_id=request.job_id,
            document_id=request.document_id,
            idempotency_key=request.idempotency_key,
            worker_version=self.worker_version,
        )
