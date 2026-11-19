"""Create personal planner tables.

Revision ID: m9_personal_planner
Revises: m8_exported_chats_google_drive
"""

from alembic import op
import sqlalchemy as sa

revision = "m9_personal_planner"
down_revision = "m8_exported_chats_google_drive"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "planner_goals" not in tables:
        op.create_table(
            "planner_goals",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.String(255), nullable=False, index=True),
            sa.Column("title", sa.String(500), nullable=False),
            sa.Column("description", sa.Text()),
            sa.Column("category", sa.String(80), nullable=False),
            sa.Column("priority", sa.String(20), nullable=False),
            sa.Column("status", sa.String(20), nullable=False),
            sa.Column("target_value", sa.Float()),
            sa.Column("current_value", sa.Float(), nullable=False, server_default="0"),
            sa.Column("unit", sa.String(80)),
            sa.Column("start_at", sa.DateTime(timezone=True)),
            sa.Column("target_at", sa.DateTime(timezone=True), index=True),
            sa.Column("check_in_frequency", sa.String(30), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True)),
        )

    if "planner_tasks" not in tables:
        op.create_table(
            "planner_tasks",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.String(255), nullable=False, index=True),
            sa.Column("title", sa.String(500), nullable=False),
            sa.Column("description", sa.Text()),
            sa.Column("category", sa.String(80), nullable=False),
            sa.Column("priority", sa.String(20), nullable=False),
            sa.Column("status", sa.String(20), nullable=False),
            sa.Column("due_at", sa.DateTime(timezone=True), index=True),
            sa.Column("estimated_minutes", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("goal_id", sa.Integer(), sa.ForeignKey("planner_goals.id"), index=True),
            sa.Column("recurrence", sa.String(30), nullable=False),
            sa.Column("reminder_offsets", sa.Text()),
            sa.Column("completed_at", sa.DateTime(timezone=True)),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True)),
        )

    if "planner_expenses" not in tables:
        op.create_table(
            "planner_expenses",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.String(255), nullable=False, index=True),
            sa.Column("title", sa.String(500), nullable=False),
            sa.Column("category", sa.String(80), nullable=False),
            sa.Column("amount", sa.Float(), nullable=False),
            sa.Column("spent_at", sa.DateTime(timezone=True), nullable=False, index=True),
            sa.Column("payment_method", sa.String(80)),
            sa.Column("notes", sa.Text()),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        )

    if "planner_bills" not in tables:
        op.create_table(
            "planner_bills",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.String(255), nullable=False, index=True),
            sa.Column("title", sa.String(500), nullable=False),
            sa.Column("category", sa.String(80), nullable=False),
            sa.Column("amount", sa.Float(), nullable=False),
            sa.Column("amount_paid", sa.Float(), nullable=False, server_default="0"),
            sa.Column("due_at", sa.DateTime(timezone=True), index=True),
            sa.Column("status", sa.String(20), nullable=False),
            sa.Column("recurrence", sa.String(30), nullable=False),
            sa.Column("reminder_offsets", sa.Text()),
            sa.Column("notes", sa.Text()),
            sa.Column("paid_at", sa.DateTime(timezone=True)),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True)),
        )

    if "planner_profiles" not in tables:
        op.create_table(
            "planner_profiles",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.String(255), nullable=False),
            sa.Column("monthly_budget", sa.Float(), nullable=False, server_default="0"),
            sa.Column("currency", sa.String(8), nullable=False, server_default="PKR"),
            sa.Column("timezone", sa.String(64)),
            sa.Column("daily_digest_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("weekly_review_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("quiet_hours_start", sa.String(5)),
            sa.Column("quiet_hours_end", sa.String(5)),
            sa.Column("updated_at", sa.DateTime(timezone=True)),
            sa.UniqueConstraint("user_id", name="uq_planner_profiles_user"),
        )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    for tbl in ["planner_profiles", "planner_bills", "planner_expenses", "planner_tasks", "planner_goals"]:
        if tbl in tables:
            op.drop_table(tbl)
