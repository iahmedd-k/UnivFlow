"""merge uniflow and rag heads

Revision ID: 343253623f7c
Revises: m5_encrypt_google_oauth_tokens, 0008
Create Date: 2026-10-25 15:58:18.242920

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '343253623f7c'
down_revision: Union[str, None] = ('m5_encrypt_google_oauth_tokens', '0008')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass