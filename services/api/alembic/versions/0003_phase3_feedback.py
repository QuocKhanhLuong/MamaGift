"""Create the Phase 3 feedback_events table."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0003_phase3_feedback"
down_revision: Union[str, None] = "0002_phase2_ingestion"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "feedback_events",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "document_id",
            sa.String(length=64),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("feedback_type", sa.String(length=64), nullable=False),
        sa.Column("field_id", sa.String(length=128), nullable=True),
        sa.Column("corrected_value", sa.Text(), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index("ix_feedback_events_document_id", "feedback_events", ["document_id"])
    op.create_index("ix_feedback_events_field_id", "feedback_events", ["field_id"])


def downgrade() -> None:
    op.drop_index("ix_feedback_events_field_id", table_name="feedback_events")
    op.drop_index("ix_feedback_events_document_id", table_name="feedback_events")
    op.drop_table("feedback_events")
