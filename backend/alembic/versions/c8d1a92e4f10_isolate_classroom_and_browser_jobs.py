"""isolate Classroom data and persist automatic browser jobs

Revision ID: c8d1a92e4f10
Revises: a42b98f1e7c3
Create Date: 2026-10-12
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "c8d1a92e4f10"
down_revision: Union[str, None] = "a42b98f1e7c3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    for table in ("google_credentials", "courses", "assignments", "assignment_templates"):
        if table not in inspector.get_table_names():
            continue
        columns = {column["name"] for column in inspector.get_columns(table)}
        if "user_id" not in columns:
            op.add_column(table, sa.Column("user_id", sa.String(length=255), nullable=True))
            op.execute(sa.text(f"UPDATE {table} SET user_id = 'legacy' WHERE user_id IS NULL"))

    for table, index_name, replacement in (
        ("courses", "ix_courses_external_id", "uq_courses_user_external_id"),
        ("assignments", "ix_assignments_external_id", "uq_assignments_user_external_id"),
    ):
        indexes = {index["name"] for index in sa.inspect(bind).get_indexes(table)}
        if index_name in indexes:
            op.drop_index(index_name, table_name=table)
        if replacement not in {index["name"] for index in sa.inspect(bind).get_indexes(table)}:
            op.create_index(replacement, table, ["user_id", "external_id"], unique=True)
        if index_name not in {index["name"] for index in sa.inspect(bind).get_indexes(table)}:
            op.create_index(index_name, table, ["external_id"], unique=False)

    if "ix_google_credentials_user_id" not in {
        index["name"] for index in sa.inspect(bind).get_indexes("google_credentials")
    }:
        op.create_index("ix_google_credentials_user_id", "google_credentials", ["user_id"], unique=True)

    with op.batch_alter_table("google_credentials") as batch:
        batch.alter_column("user_id", existing_type=sa.String(length=255), nullable=False)
    with op.batch_alter_table("courses") as batch:
        batch.alter_column("user_id", existing_type=sa.String(length=255), nullable=False)
    with op.batch_alter_table("assignments") as batch:
        batch.alter_column("user_id", existing_type=sa.String(length=255), nullable=False)
    if "assignment_templates" in sa.inspect(bind).get_table_names():
        with op.batch_alter_table("assignment_templates") as batch:
            batch.alter_column("user_id", existing_type=sa.String(length=255), nullable=False)
        if "ix_assignment_templates_user_id" not in {
            index["name"] for index in sa.inspect(bind).get_indexes("assignment_templates")
        }:
            op.create_index("ix_assignment_templates_user_id", "assignment_templates", ["user_id"])

    if "browser_automation_jobs" not in sa.inspect(bind).get_table_names():
        op.create_table(
            "browser_automation_jobs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.String(length=255), nullable=False),
            sa.Column("assignment_id", sa.Integer(), sa.ForeignKey("assignments.id"), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("queued_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("error", sa.Text(), nullable=True),
            sa.UniqueConstraint("user_id", "assignment_id", name="uq_browser_jobs_user_assignment"),
        )
        op.create_index("ix_browser_automation_jobs_user_id", "browser_automation_jobs", ["user_id"])
        op.create_index("ix_browser_automation_jobs_assignment_id", "browser_automation_jobs", ["assignment_id"])
        op.create_index(
            "ix_browser_jobs_status_queued_at",
            "browser_automation_jobs",
            ["status", "queued_at"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "browser_automation_jobs" in inspector.get_table_names():
        op.drop_table("browser_automation_jobs")

    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("google_credentials")}
    if "ix_google_credentials_user_id" in indexes:
        op.drop_index("ix_google_credentials_user_id", table_name="google_credentials")

    for table, index_name in (
        ("assignments", "ix_assignments_external_id"),
        ("courses", "ix_courses_external_id"),
    ):
        indexes = {index["name"] for index in sa.inspect(bind).get_indexes(table)}
        if "uq_assignments_user_external_id" in indexes and table == "assignments":
            op.drop_index("uq_assignments_user_external_id", table_name=table)
        if "uq_courses_user_external_id" in indexes and table == "courses":
            op.drop_index("uq_courses_user_external_id", table_name=table)
        indexes = {index["name"] for index in sa.inspect(bind).get_indexes(table)}
        if index_name in indexes:
            op.drop_index(index_name, table_name=table)
        op.create_index(index_name, table, ["external_id"], unique=True)
    for table in ("assignments", "courses", "google_credentials"):
        with op.batch_alter_table(table) as batch:
            batch.drop_column("user_id")
    if "assignment_templates" in sa.inspect(bind).get_table_names():
        indexes = {index["name"] for index in sa.inspect(bind).get_indexes("assignment_templates")}
        if "ix_assignment_templates_user_id" in indexes:
            op.drop_index("ix_assignment_templates_user_id", table_name="assignment_templates")
        with op.batch_alter_table("assignment_templates") as batch:
            batch.drop_column("user_id")
