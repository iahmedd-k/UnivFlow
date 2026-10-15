"""Add notification columns and missing tables

Revision ID: add_notification_tables
Revises: add_fk_and_soft_deletes
Create Date: 2026-10-15
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = "add_notification_tables"
down_revision: Union[str, Sequence[str], None] = "add_fk_and_soft_deletes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())

    # 1. Update notifications table columns
    if "notifications" in table_names:
        cols = {c["name"] for c in inspector.get_columns("notifications")}
        if "channel" not in cols:
            op.add_column("notifications", sa.Column("channel", sa.String(length=32), nullable=False, server_default="email"))
        if "delivered_at" not in cols:
            op.add_column("notifications", sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True))
        if "retry_count" not in cols:
            op.add_column("notifications", sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"))
        if "max_retries" not in cols:
            op.add_column("notifications", sa.Column("max_retries", sa.Integer(), nullable=False, server_default="3"))
        if "scheduled_for" not in cols:
            op.add_column("notifications", sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=True))
        if "template_id" not in cols:
            op.add_column("notifications", sa.Column("template_id", sa.String(length=100), nullable=True))
        if "template_data" not in cols:
            op.add_column("notifications", sa.Column("template_data", sa.Text(), nullable=True))
        if "provider" not in cols:
            op.add_column("notifications", sa.Column("provider", sa.String(length=50), nullable=True))
        if "provider_message_id" not in cols:
            op.add_column("notifications", sa.Column("provider_message_id", sa.String(length=255), nullable=True))
        if "updated_at" not in cols:
            op.add_column("notifications", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))

    # 2. In PostgreSQL, ensure enum values exist for both casing
    if bind.dialect.name == "postgresql":
        op.execute("""
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM pg_type WHERE typname = 'notificationstatus') THEN
                    BEGIN
                        ALTER TYPE notificationstatus ADD VALUE IF NOT EXISTS 'pending';
                        ALTER TYPE notificationstatus ADD VALUE IF NOT EXISTS 'sent';
                        ALTER TYPE notificationstatus ADD VALUE IF NOT EXISTS 'failed';
                        ALTER TYPE notificationstatus ADD VALUE IF NOT EXISTS 'PENDING';
                        ALTER TYPE notificationstatus ADD VALUE IF NOT EXISTS 'SENT';
                        ALTER TYPE notificationstatus ADD VALUE IF NOT EXISTS 'FAILED';
                    EXCEPTION WHEN duplicate_object THEN
                        NULL;
                    END;
                END IF;
            END$$;
        """)

    # 3. Create notification_preferences table if not exists
    if "notification_preferences" not in table_names:
        op.create_table(
            "notification_preferences",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.String(length=255), nullable=False),
            sa.Column("notification_type", sa.String(length=100), nullable=False),
            sa.Column("channel", sa.String(length=32), nullable=False),
            sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=True),
            sa.Column("quiet_hours_start", sa.String(length=5), nullable=True),
            sa.Column("quiet_hours_end", sa.String(length=5), nullable=True),
            sa.Column("timezone", sa.String(length=50), server_default="UTC", nullable=True),
            sa.Column("frequency", sa.String(length=32), server_default="immediate", nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("user_id", "notification_type", "channel", name="uq_notif_pref_user_type_channel")
        )
        op.create_index(op.f("ix_notification_preferences_id"), "notification_preferences", ["id"], unique=False)
        op.create_index(op.f("ix_notification_preferences_user_id"), "notification_preferences", ["user_id"], unique=False)

    # 4. Create notification_templates table if not exists
    if "notification_templates" not in table_names:
        op.create_table(
            "notification_templates",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=100), nullable=False),
            sa.Column("channel", sa.String(length=32), nullable=False),
            sa.Column("subject_template", sa.String(length=500), nullable=True),
            sa.Column("body_template", sa.Text(), nullable=False),
            sa.Column("variables", sa.Text(), nullable=True),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("name", "channel", name="uq_template_name_channel")
        )
        op.create_index(op.f("ix_notification_templates_id"), "notification_templates", ["id"], unique=False)
        op.create_index(op.f("ix_notification_templates_name"), "notification_templates", ["name"], unique=False)

    # 5. Create portal_sync_jobs table if not exists
    if "portal_sync_jobs" not in table_names:
        op.create_table(
            "portal_sync_jobs",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.String(length=255), nullable=False),
            sa.Column("job_id", sa.String(length=64), nullable=False),
            sa.Column("status", sa.String(length=32), server_default="queued", nullable=False),
            sa.Column("sync_type", sa.String(length=32), server_default="full", nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("result", sa.Text(), nullable=True),
            sa.Column("retry_count", sa.Integer(), server_default="0", nullable=True),
            sa.Column("max_retries", sa.Integer(), server_default="3", nullable=True),
            sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
            sa.PrimaryKeyConstraint("id")
        )
        op.create_index(op.f("ix_portal_sync_jobs_id"), "portal_sync_jobs", ["id"], unique=False)
        op.create_index(op.f("ix_portal_sync_jobs_job_id"), "portal_sync_jobs", ["job_id"], unique=True)
        op.create_index(op.f("ix_portal_sync_jobs_user_id"), "portal_sync_jobs", ["user_id"], unique=False)

    # 6. Create assignment_templates table if not exists
    if "assignment_templates" not in table_names:
        op.create_table(
            "assignment_templates",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.String(length=255), server_default="legacy", nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("google_doc_id", sa.String(length=255), nullable=False),
            sa.Column("google_drive_file_id", sa.String(length=255), nullable=True),
            sa.Column("mime_type", sa.String(length=100), nullable=True),
            sa.Column("is_default", sa.Boolean(), server_default=sa.text("false"), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.PrimaryKeyConstraint("id")
        )
        op.create_index(op.f("ix_assignment_templates_id"), "assignment_templates", ["id"], unique=False)
        op.create_index(op.f("ix_assignment_templates_user_id"), "assignment_templates", ["user_id"], unique=False)


def downgrade() -> None:
    pass
