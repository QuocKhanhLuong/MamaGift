"""Phase 5 pgvector migration for document_chunks.

Replaces the JSON embedding column on PostgreSQL with a native pgvector
vector(1024) column and clears embedding metadata so the indexing worker
re-embeds. SQLite is a no-op as EmbeddingVector resolves to JSON there.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

from alembic import op

revision: str = "0005_phase5_pgvector"
down_revision: str | None = "0004_phase4_chunk_index"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        # 1. Ensure pgvector extension exists
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
        # 2. Drop the old JSON embedding column
        op.drop_column("document_chunks", "embedding")
        # 3. Add the native pgvector column with dimension 1024
        op.add_column("document_chunks", sa.Column("embedding", Vector(1024), nullable=True))
        # 4. Step 4 safety mechanism: clearing embedding_version makes the existing
        # needs_reindex() in services/api/app/indexing.py return True for every document,
        # so the worker re-embeds safely.
        op.execute("UPDATE document_chunks SET embedding_version = NULL, embedding_model = NULL")
    else:
        # SQLite / other dialects: NO-OP. EmbeddingVector already resolves to JSON
        # there, so the shipped schema already matches the model.
        pass


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        # Drop the vector column and restore sa.JSON() column
        op.drop_column("document_chunks", "embedding")
        op.add_column("document_chunks", sa.Column("embedding", sa.JSON(), nullable=True))
        # Clear embedding metadata again so downstream indexing stays consistent
        op.execute("UPDATE document_chunks SET embedding_version = NULL, embedding_model = NULL")
        # NOTE: DO NOT drop the vector extension; it may be shared with unrelated objects.
    else:
        # SQLite / other dialects: no-op
        pass
