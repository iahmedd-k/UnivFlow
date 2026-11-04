"""Store the Google Drive file created for each exported chat PDF.

Revision ID: m8_exported_chats_google_drive
Revises: m7_user_read_indexes
Create Date: 2026-11-04 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "m8_exported_chats_google_drive"
down_revision: Union[str, Sequence[str], None] = "m7_user_read_indexes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "exported_chats" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("exported_chats")}
    if "google_drive_file_id" not in columns:
        with op.batch_alter_table("exported_chats") as batch:
            batch.add_column(sa.Column("google_drive_file_id", sa.String(length=255), nullable=True))


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "exported_chats" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("exported_chats")}
    if "google_drive_file_id" in columns:
        with op.batch_alter_table("exported_chats") as batch:
            batch.drop_column("google_drive_file_id")
