"""API DTOs.

The frontend consumes these, never database row shapes
(`docs/08_API_AND_DATA_CONTRACTS.md` section 20). Nullable extracted fields stay
nullable: a missing value is never replaced by a plausible placeholder.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .models import Document, FeedbackEvent, Job, ParseRun


class DocumentSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    filename: str
    checksum_sha256: str
    byte_size: int
    status: str
    document_type: str | None = None
    document_number: str | None = None
    title: str | None = None
    issuer: str | None = None
    issued_date: date | None = None
    signer: str | None = None
    deadline: date | None = None
    requires_user_review: bool = False
    current_parse_run_id: str | None = None
    error_code: str | None = None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, document: Document) -> DocumentSummary:
        return cls(
            id=document.id,
            filename=document.filename,
            checksum_sha256=document.checksum_sha256,
            byte_size=document.byte_size,
            status=document.status,
            document_type=document.document_type,
            document_number=document.document_number,
            title=document.title,
            issuer=document.issuer,
            issued_date=document.issued_date,
            signer=document.signer,
            deadline=document.deadline,
            requires_user_review=document.requires_user_review,
            current_parse_run_id=document.current_parse_run_id,
            error_code=document.error_code,
            created_at=document.created_at,
            updated_at=document.updated_at,
        )


class JobSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    document_id: str
    kind: str
    status: str
    attempt: int
    idempotency_key: str
    leased_by: str | None = None
    lease_expires_at: datetime | None = None
    error: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, job: Job) -> JobSummary:
        return cls(
            id=job.id,
            document_id=job.document_id,
            kind=job.kind,
            status=job.status,
            attempt=job.attempt,
            idempotency_key=job.idempotency_key,
            leased_by=job.leased_by,
            lease_expires_at=job.lease_expires_at,
            error=job.error,
            created_at=job.created_at,
            updated_at=job.updated_at,
        )


class ParseRunSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    document_id: str
    version: int
    is_current: bool
    parser_name: str
    parser_version: str
    configuration_hash: str
    strategy_decided: bool
    degraded: bool
    route: str
    schema_version: str
    quality_report: dict[str, Any]
    started_at: datetime
    finished_at: datetime

    @classmethod
    def from_model(cls, run: ParseRun) -> ParseRunSummary:
        return cls(
            id=run.id,
            document_id=run.document_id,
            version=run.version,
            is_current=run.is_current,
            parser_name=run.parser_name,
            parser_version=run.parser_version,
            configuration_hash=run.configuration_hash,
            strategy_decided=run.strategy_decided,
            degraded=run.degraded,
            route=run.route,
            schema_version=run.schema_version,
            quality_report=run.quality_report,
            started_at=run.started_at,
            finished_at=run.finished_at,
        )


class UploadResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document: DocumentSummary
    job: JobSummary
    duplicate_of_existing: bool = False


class DocumentListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[DocumentSummary] = Field(default_factory=list)
    total: int
    limit: int
    offset: int


class DocumentStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document: DocumentSummary
    latest_job: JobSummary | None = None
    current_parse_run: ParseRunSummary | None = None


class DocumentDetailResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document: DocumentSummary
    parse_runs: list[ParseRunSummary] = Field(default_factory=list)


class CanonicalResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parse_run: ParseRunSummary
    canonical: dict[str, Any]


class ReprocessResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document: DocumentSummary
    job: JobSummary


class FeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feedback_type: str = Field(min_length=1)
    field_id: str | None = None
    corrected_value: str | None = None
    comment: str | None = None


class FeedbackResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    document_id: str
    feedback_type: str
    field_id: str | None = None
    corrected_value: str | None = None
    comment: str | None = None
    created_at: datetime

    @classmethod
    def from_model(cls, event: FeedbackEvent) -> FeedbackResponse:
        return cls(
            id=event.id,
            document_id=event.document_id,
            feedback_type=event.feedback_type,
            field_id=event.field_id,
            corrected_value=event.corrected_value,
            comment=event.comment,
            created_at=event.created_at,
        )
