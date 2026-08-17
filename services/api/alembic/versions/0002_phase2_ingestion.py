"""Create the Phase 2 ingestion tables: documents, jobs and parse runs."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0002_phase2_ingestion"
down_revision: Union[str, None] = "0001_phase0_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("filename", sa.String(length=512), nullable=False),
        sa.Column("content_type", sa.String(length=128), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=False),
        sa.Column("storage_uri", sa.String(length=1024), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("document_type", sa.String(length=64), nullable=True),
        sa.Column("document_number", sa.String(length=128), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("issuer", sa.Text(), nullable=True),
        sa.Column("issued_date", sa.Date(), nullable=True),
        sa.Column("signer", sa.String(length=256), nullable=True),
        sa.Column("deadline", sa.Date(), nullable=True),
        sa.Column("current_parse_run_id", sa.String(length=64), nullable=True),
        sa.Column(
            "requires_user_review",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0" if op.get_bind().dialect.name == "sqlite" else "false"),
        ),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint("checksum_sha256", name="uq_documents_checksum"),
    )
    op.create_index("ix_documents_status", "documents", ["status"])

    op.create_table(
        "jobs",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "document_id",
            sa.String(length=64),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default=sa.text("3")),
        sa.Column("idempotency_key", sa.String(length=256), nullable=False),
        sa.Column("leased_by", sa.String(length=128), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint("idempotency_key", name="uq_jobs_idempotency_key"),
    )
    op.create_index("ix_jobs_document_id", "jobs", ["document_id"])
    op.create_index("ix_jobs_status", "jobs", ["status"])

    op.create_table(
        "parse_runs",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "document_id",
            sa.String(length=64),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("job_id", sa.String(length=64), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "is_current",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0" if op.get_bind().dialect.name == "sqlite" else "false"),
        ),
        sa.Column("parser_name", sa.String(length=64), nullable=False),
        sa.Column("parser_version", sa.String(length=128), nullable=False),
        sa.Column("configuration_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "strategy_decided",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0" if op.get_bind().dialect.name == "sqlite" else "false"),
        ),
        sa.Column(
            "degraded",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0" if op.get_bind().dialect.name == "sqlite" else "false"),
        ),
        sa.Column("route", sa.String(length=32), nullable=False),
        sa.Column("schema_version", sa.String(length=16), nullable=False),
        sa.Column("canonical", sa.JSON(), nullable=False),
        sa.Column("inspection", sa.JSON(), nullable=False),
        sa.Column("quality_report", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint("document_id", "version", name="uq_parse_runs_version"),
    )
    op.create_index("ix_parse_runs_document_id", "parse_runs", ["document_id"])


def downgrade() -> None:
    op.drop_index("ix_parse_runs_document_id", table_name="parse_runs")
    op.drop_table("parse_runs")
    op.drop_index("ix_jobs_status", table_name="jobs")
    op.drop_index("ix_jobs_document_id", table_name="jobs")
    op.drop_table("jobs")
    op.drop_index("ix_documents_status", table_name="documents")
    op.drop_table("documents")
