"""Merge recurring timetable and browser job migrations.

Revision ID: d9f4c2a7b1e6
Revises: b71d1a0c8f44, c8d1a92e4f10
Create Date: 2026-10-13
"""

from typing import Sequence, Union

revision: str = "d9f4c2a7b1e6"
down_revision: Union[str, Sequence[str], None] = ("b71d1a0c8f44", "c8d1a92e4f10")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
