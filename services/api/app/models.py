"""SQLAlchemy models for Phase 2 ingestion.

Database rows are storage, not API truth: DTOs in `schemas.py` are what the API
returns. Extracted fields are mirrored onto `documents` for listing and filtering,
while the authoritative versioned artifact stays in `parse_runs.canonical`.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base
from .state_machine import DocumentStatus, JobStatus


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    storage_uri: Mapped[str] = mapped_column(String(1024), nullable=False)

    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=DocumentStatus.UPLOADED.value
    )

    document_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    document_number: Mapped[str | None] = mapped_column(String(128), nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    issuer: Mapped[str | None] = mapped_column(Text, nullable=True)
    issued_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    signer: Mapped[str | None] = mapped_column(String(256), nullable=True)
    deadline: Mapped[date | None] = mapped_column(Date, nullable=True)

    current_parse_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    requires_user_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    jobs: Mapped[list[Job]] = relationship(back_populates="document", cascade="all, delete-orphan")
    parse_runs: Mapped[list[ParseRun]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    document_chunks: Mapped[list[DocumentChunk]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_jobs_idempotency_key"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    document_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False, default="parse")
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=JobStatus.QUEUED.value, index=True
    )
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    idempotency_key: Mapped[str] = mapped_column(String(256), nullable=False)

    leased_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    available_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    error: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    document: Mapped[Document] = relationship(back_populates="jobs")


class ParseRun(Base):
    """One immutable attempt at turning the original bytes into a canonical document."""

    __tablename__ = "parse_runs"
    __table_args__ = (UniqueConstraint("document_id", "version", name="uq_parse_runs_version"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    document_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    job_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    parser_name: Mapped[str] = mapped_column(String(64), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(128), nullable=False)
    configuration_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    strategy_decided: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    degraded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    route: Mapped[str] = mapped_column(String(32), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(16), nullable=False)

    canonical: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    inspection: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    quality_report: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    document: Mapped[Document] = relationship(back_populates="parse_runs")


class FeedbackEvent(Base):
    """An append-only correction event (`docs/08_API_AND_DATA_CONTRACTS.md` section 13).

    Feedback never rewrites `parse_runs.canonical`; the raw prediction stays exactly
    as parsed, and a corrected value is layered on top when the canonical document is
    served (`docs/09_CODEX_EXECUTION.md` section 8).
    """

    __tablename__ = "feedback_events"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    document_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    feedback_type: Mapped[str] = mapped_column(String(64), nullable=False)
    field_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    corrected_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class DocumentChunk(Base):
    """A persisted chunk of a parsed document version (`docs/superpowers/plans/...` section 3.6).

    Chunks are derived data, never authoritative: reparsing writes a new
    `parse_run_id` and its own rows; old rows remain until explicitly dropped
    and must never be returned for a current-version query.
    """

    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint(
            "parse_run_id", "chunk_index", name="uq_document_chunks_parse_run_chunk_index"
        ),
        Index("ix_document_chunks_document_id_parse_run_id", "document_id", "parse_run_id"),
    )

    id: Mapped[str] = mapped_column(String(256), primary_key=True)
    document_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    parse_run_id: Mapped[str] = mapped_column(String(64), nullable=False)
    document_version: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_chunk_id: Mapped[str | None] = mapped_column(String(256), nullable=True)

    section_path: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    page_numbers: Mapped[list[int]] = mapped_column(JSON, nullable=False)
    source_block_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)

    embedding: Mapped[list[float] | None] = mapped_column(JSON, nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    embedding_version: Mapped[str | None] = mapped_column(String(64), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    document: Mapped[Document] = relationship(back_populates="document_chunks")
