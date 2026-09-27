"""add recurring timetable entries

Revision ID: b71d1a0c8f44
Revises: a42b98f1e7c3
Create Date: 2026-09-26
"""

from alembic import op
import sqlalchemy as sa

revision = "b71d1a0c8f44"
down_revision = "a42b98f1e7c3"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if "timetable_entries" not in inspector.get_table_names():
        op.create_table(
            "timetable_entries",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("external_id", sa.String(length=64), nullable=False),
            sa.Column("subject", sa.String(length=255), nullable=False),
            sa.Column("weekday", sa.Integer(), nullable=False),
            sa.Column("start_time", sa.String(length=10), nullable=False),
            sa.Column("end_time", sa.String(length=10), nullable=False),
            sa.Column("teacher", sa.String(length=255), nullable=True),
            sa.Column("room", sa.String(length=100), nullable=True),
            sa.Column("semester_name", sa.String(length=120), nullable=True),
            sa.Column("semester_start", sa.DateTime(timezone=True), nullable=True),
            sa.Column("semester_end", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("external_id"),
        )
    indexes = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes("timetable_entries")}
    if "ix_timetable_entries_id" not in indexes:
        op.create_index("ix_timetable_entries_id", "timetable_entries", ["id"])
    if "ix_timetable_entries_external_id" not in indexes:
        op.create_index("ix_timetable_entries_external_id", "timetable_entries", ["external_id"], unique=True)


def downgrade():
    op.drop_index("ix_timetable_entries_external_id", table_name="timetable_entries")
    op.drop_index("ix_timetable_entries_id", table_name="timetable_entries")
    op.drop_table("timetable_entries")
