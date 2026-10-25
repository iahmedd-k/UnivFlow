"""add document_chunks table and pgvector extension

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-08

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EMBEDDING_DIMENSION = 768


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "document_chunks",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "document_id",
            sa.Integer,
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "user_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("page_number", sa.Integer, nullable=False),
        sa.Column(
            "page_numbers",
            sa.JSON().with_variant(JSONB(), "postgresql"),
            nullable=False,
            server_default="[]",
        ),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("content_type", sa.String(20), nullable=False),
        sa.Column(
            "metadata",
            sa.JSON().with_variant(JSONB(), "postgresql"),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "embedding",
            Vector(EMBEDDING_DIMENSION),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("document_chunks")
    op.execute("DROP EXTENSION IF EXISTS vector")
