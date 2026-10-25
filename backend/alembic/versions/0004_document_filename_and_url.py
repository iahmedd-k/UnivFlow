"""rename document filename and add storage url

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-08

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("storage_url", sa.String(length=512), nullable=False, server_default=""),
    )
    op.alter_column(
        "documents",
        "filename",
        new_column_name="original_filename",
    )


def downgrade() -> None:
    op.alter_column(
        "documents",
        "original_filename",
        new_column_name="filename",
    )
    op.drop_column("documents", "storage_url")