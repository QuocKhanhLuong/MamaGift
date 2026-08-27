"""Phase 5 migration creating the document_relations table.

Revision ID: 0006_phase5_document_relations
Revises: 0005_phase5_pgvector
Create Date: 2026-08-27
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0006_phase5_document_relations"
down_revision: str | None = "0005_phase5_pgvector"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "document_relations",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "source_document_id",
            sa.String(length=64),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_parse_run_id", sa.String(length=64), nullable=False),
        sa.Column("source_document_version", sa.Integer(), nullable=False),
        sa.Column("source_block_ids", sa.JSON(), nullable=False),
        sa.Column("page_numbers", sa.JSON(), nullable=False),
        sa.Column("relation_type", sa.String(length=32), nullable=False),
        sa.Column(
            "target_document_id",
            sa.String(length=64),
            sa.ForeignKey("documents.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("target_document_number", sa.String(length=128), nullable=True),
        sa.Column("target_raw_text", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column(
            "review_state",
            sa.String(length=32),
            nullable=False,
            server_default="unverified",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["source_parse_run_id", "source_document_id", "source_document_version"],
            ["parse_runs.id", "parse_runs.document_id", "parse_runs.version"],
            ondelete="CASCADE",
            name="fk_document_relations_source_provenance",
        ),
        sa.CheckConstraint(
            "target_document_id IS NOT NULL OR target_document_number IS NOT NULL",
            name="ck_document_relations_target_present",
        ),
        sa.CheckConstraint(
            "confidence >= 0.0 AND confidence <= 1.0",
            name="ck_document_relations_confidence_range",
        ),
        sa.UniqueConstraint(
            "source_parse_run_id",
            "relation_type",
            "target_document_number",
            "target_document_id",
            name="uq_document_relations_identity",
        ),
    )
    op.create_index(
        "ix_document_relations_source_document_id",
        "document_relations",
        ["source_document_id"],
    )
    op.create_index(
        "ix_document_relations_target_document_id",
        "document_relations",
        ["target_document_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_document_relations_target_document_id", table_name="document_relations")
    op.drop_index("ix_document_relations_source_document_id", table_name="document_relations")
    op.drop_table("document_relations")
