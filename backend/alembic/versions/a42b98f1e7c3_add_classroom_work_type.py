"""add Google Classroom work type

Revision ID: a42b98f1e7c3
Revises: f9eb2b17779e
Create Date: 2026-09-26
"""

from alembic import op
import sqlalchemy as sa

revision = "a42b98f1e7c3"
down_revision = "f9eb2b17779e"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    existing_tables = set(inspector.get_table_names())
    additions = {
        "assignments": {
            "work_type": sa.Column("work_type", sa.String(length=50), nullable=True),
            "is_quiz": sa.Column("is_quiz", sa.Boolean(), nullable=False, server_default=sa.false()),
        },
        "announcements": {
            "course_id": sa.Column("course_id", sa.Integer(), nullable=True),
            "url": sa.Column("url", sa.String(length=1000), nullable=True),
        },
    }
    for table, columns in additions.items():
        if table not in existing_tables:
            continue
        existing_columns = {column["name"] for column in inspector.get_columns(table)}
        for name, column in columns.items():
            if name not in existing_columns:
                op.add_column(table, column)


def downgrade():
    op.drop_column("announcements", "url")
    op.drop_column("announcements", "course_id")
    op.drop_column("assignments", "work_type")
    op.drop_column("assignments", "is_quiz")
