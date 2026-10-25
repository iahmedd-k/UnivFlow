"""add pgvector HNSW index and full-text search indexes for retrieval

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-08

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # pgvector HNSW index for fast approximate cosine similarity search.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_document_chunks_embedding_hnsw "
        "ON document_chunks "
        "USING hnsw (embedding vector_cosine_ops)"
    )

    # Generated tsvector column over chunk content for full-text search.
    op.execute(
        "ALTER TABLE document_chunks "
        "ADD COLUMN IF NOT EXISTS search_vector tsvector "
        "GENERATED ALWAYS AS ("
        "to_tsvector('english', coalesce(content, ''))"
        ") STORED"
    )

    # GIN index on the generated tsvector column for efficient ranking.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_document_chunks_search_vector_gin "
        "ON document_chunks "
        "USING gin (search_vector)"
    )


def downgrade() -> None:
    op.execute(
        "DROP INDEX IF EXISTS ix_document_chunks_search_vector_gin"
    )
    op.execute(
        "ALTER TABLE document_chunks "
        "DROP COLUMN IF EXISTS search_vector"
    )
    op.execute(
        "DROP INDEX IF EXISTS ix_document_chunks_embedding_hnsw"
    )
