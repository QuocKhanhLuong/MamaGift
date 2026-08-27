"""Persist structure-aware chunk metadata so task/owner/deadline survives the database.

The `Kế hoạch` chunker binds each task's owner, coordinating unit and deadline to that task
as `Chunk.metadata` rather than leaving them loose in text, which is what stops Task B's
deadline attaching to Task A. Until this revision `document_chunks` had nowhere to put that
mapping, so it was silently dropped on write and every retrieved plan task came back with an
empty metadata dict. The association existed in the chunker and nowhere else.

The column is `chunk_metadata`, not `metadata`: `metadata` is reserved on SQLAlchemy
declarative models.
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0007_phase5_chunk_metadata"
down_revision: Union[str, None] = "0006_phase5_document_relations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "document_chunks",
        sa.Column("chunk_metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )
    # Existing rows predate the column and carry no structured metadata. They are derived data
    # and will be rebuilt on the next reindex, so an empty object is the correct value rather
    # than a guess.
    op.execute("UPDATE document_chunks SET chunk_metadata = '{}' WHERE chunk_metadata IS NULL")


def downgrade() -> None:
    op.drop_column("document_chunks", "chunk_metadata")
