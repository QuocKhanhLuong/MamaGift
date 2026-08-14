"""Pydantic DTOs shared by the API and the contract-only fake worker."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class WorkerCapabilities(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parse: bool = False
    embed: bool = False
    rerank: bool = False
    llm: bool = False


class WorkerHealth(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["online", "offline", "degraded"]
    worker_version: str = Field(min_length=1)
    capabilities: WorkerCapabilities
    models: dict[str, str] = Field(default_factory=dict)


class ParseJobInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object_uri: str = Field(min_length=1)
    checksum_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")


class ParserSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    configuration: dict[str, Any] = Field(default_factory=dict)


class ParseJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    input: ParseJobInput
    parser: ParserSpec


class ParseJobAccepted(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["accepted"] = "accepted"
    job_id: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    worker_version: str = Field(min_length=1)
    implementation: Literal["fake-contract-only"] = "fake-contract-only"
