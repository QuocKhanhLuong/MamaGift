"""Create the Phase 4 document_chunks table and index."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0004_phase4_chunk_index"
down_revision: Union[str, None] = "0003_phase3_feedback"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "document_chunks",
        sa.Column("id", sa.String(length=256), primary_key=True),
        sa.Column(
            "document_id",
            sa.String(length=64),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("parse_run_id", sa.String(length=64), nullable=False),
        sa.Column("document_version", sa.Integer(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("parent_chunk_id", sa.String(length=256), nullable=True),
        sa.Column("section_path", sa.JSON(), nullable=False),
        sa.Column("page_numbers", sa.JSON(), nullable=False),
        sa.Column("source_block_ids", sa.JSON(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("embedding", sa.JSON(), nullable=True),
        sa.Column("embedding_model", sa.String(length=128), nullable=True),
        sa.Column("embedding_version", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint(
            "parse_run_id", "chunk_index", name="uq_document_chunks_parse_run_chunk_index"
        ),
    )
    op.create_index(
        "ix_document_chunks_document_id_parse_run_id",
        "document_chunks",
        ["document_id", "parse_run_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_document_chunks_document_id_parse_run_id", table_name="document_chunks")
    op.drop_table("document_chunks")
