"""extend document processing status lifecycle

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-08

The documents.status column is stored as a plain VARCHAR(20) without a
DB-level CHECK constraint (the enum is defined at the application layer),
so introducing the "completed" lifecycle status requires no DDL changes.

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass