"""add document_ids to conversations

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-14

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column(
            "document_ids",
            JSONB,
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("conversations", "document_ids")
