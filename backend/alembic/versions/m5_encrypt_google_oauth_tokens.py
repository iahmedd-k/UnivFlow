"""Encrypt existing Google OAuth tokens at rest."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.core.security import encrypt_token_if_needed


revision: str = "m5_encrypt_google_oauth_tokens"
down_revision: Union[str, Sequence[str], None] = "m4_course_file_cache"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "google_credentials" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("google_credentials")}
    if not {"id", "access_token", "refresh_token"}.issubset(columns):
        return

    table = sa.table(
        "google_credentials",
        sa.column("id", sa.Integer()),
        sa.column("access_token", sa.Text()),
        sa.column("refresh_token", sa.Text()),
    )
    rows = bind.execute(sa.select(table.c.id, table.c.access_token, table.c.refresh_token)).all()
    for row in rows:
        access_token = encrypt_token_if_needed(row.access_token)
        refresh_token = encrypt_token_if_needed(row.refresh_token)
        if access_token != row.access_token or refresh_token != row.refresh_token:
            bind.execute(
                table.update().where(table.c.id == row.id).values(
                    access_token=access_token,
                    refresh_token=refresh_token,
                )
            )


def downgrade() -> None:
    # Keep credentials encrypted when rolling back application code.
    pass
