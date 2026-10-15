"""Add missing user_id columns to all tables for multi-user isolation

Revision ID: add_missing_user_id
Revises: d9f4c2a7b1e6
Create Date: 2026-10-14
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "add_missing_user_id"
down_revision: Union[str, Sequence[str], None] = "d9f4c2a7b1e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    
    tables_needing_user_id = [
        "attendance_records",
        "exams", 
        "quizzes",
        "announcements",
        "change_events",
        "class_schedules",
        "timetable_entries",
        "agent_runs",
        "notifications",
        "google_credentials",
        "agent_events",
        "assignment_materials",
        "assignment_solutions",
        "submissions",
        "daily_reports",
    ]
    
    for table in tables_needing_user_id:
        if table not in inspector.get_table_names():
            continue
        columns = {column["name"] for column in inspector.get_columns(table)}
        if "user_id" not in columns:
            op.add_column(table, sa.Column("user_id", sa.String(length=255), nullable=True))
            op.execute(sa.text(f"UPDATE {table} SET user_id = 'legacy' WHERE user_id IS NULL"))
    
    for table in tables_needing_user_id:
        if table not in inspector.get_table_names():
            continue
        with op.batch_alter_table(table) as batch:
            batch.alter_column("user_id", existing_type=sa.String(length=255), nullable=False)
    
    if "google_credentials" in inspector.get_table_names():
        indexes = {index["name"] for index in inspector.get_indexes("google_credentials")}
        if "ix_google_credentials_user_id" not in indexes:
            op.create_index("ix_google_credentials_user_id", "google_credentials", ["user_id"], unique=True)
    
    if "attendance_records" in inspector.get_table_names():
        indexes = {index["name"] for index in inspector.get_indexes("attendance_records")}
        if "ix_attendance_records_user_id" not in indexes:
            op.create_index("ix_attendance_records_user_id", "attendance_records", ["user_id"])
    
    if "exams" in inspector.get_table_names():
        indexes = {index["name"] for index in inspector.get_indexes("exams")}
        if "ix_exams_user_id" not in indexes:
            op.create_index("ix_exams_user_id", "exams", ["user_id"])
    
    if "quizzes" in inspector.get_table_names():
        indexes = {index["name"] for index in inspector.get_indexes("quizzes")}
        if "ix_quizzes_user_id" not in indexes:
            op.create_index("ix_quizzes_user_id", "quizzes", ["user_id"])
    
    if "announcements" in inspector.get_table_names():
        indexes = {index["name"] for index in inspector.get_indexes("announcements")}
        if "ix_announcements_user_id" not in indexes:
            op.create_index("ix_announcements_user_id", "announcements", ["user_id"])
    
    if "change_events" in inspector.get_table_names():
        indexes = {index["name"] for index in inspector.get_indexes("change_events")}
        if "ix_change_events_user_id" not in indexes:
            op.create_index("ix_change_events_user_id", "change_events", ["user_id"])
    
    if "class_schedules" in inspector.get_table_names():
        indexes = {index["name"] for index in inspector.get_indexes("class_schedules")}
        if "ix_class_schedules_user_id" not in indexes:
            op.create_index("ix_class_schedules_user_id", "class_schedules", ["user_id"])
    
    if "timetable_entries" in inspector.get_table_names():
        indexes = {index["name"] for index in inspector.get_indexes("timetable_entries")}
        if "ix_timetable_entries_user_id" not in indexes:
            op.create_index("ix_timetable_entries_user_id", "timetable_entries", ["user_id"])
    
    if "agent_runs" in inspector.get_table_names():
        indexes = {index["name"] for index in inspector.get_indexes("agent_runs")}
        if "ix_agent_runs_user_id" not in indexes:
            op.create_index("ix_agent_runs_user_id", "agent_runs", ["user_id"])
    
    if "notifications" in inspector.get_table_names():
        indexes = {index["name"] for index in inspector.get_indexes("notifications")}
        if "ix_notifications_user_id" not in indexes:
            op.create_index("ix_notifications_user_id", "notifications", ["user_id"])
    
    if "agent_events" in inspector.get_table_names():
        indexes = {index["name"] for index in inspector.get_indexes("agent_events")}
        if "ix_agent_events_user_id" not in indexes:
            op.create_index("ix_agent_events_user_id", "agent_events", ["user_id"])
    
    if "assignment_materials" in inspector.get_table_names():
        indexes = {index["name"] for index in inspector.get_indexes("assignment_materials")}
        if "ix_assignment_materials_user_id" not in indexes:
            op.create_index("ix_assignment_materials_user_id", "assignment_materials", ["user_id"])
    
    if "assignment_solutions" in inspector.get_table_names():
        indexes = {index["name"] for index in inspector.get_indexes("assignment_solutions")}
        if "ix_assignment_solutions_user_id" not in indexes:
            op.create_index("ix_assignment_solutions_user_id", "assignment_solutions", ["user_id"])
    
    if "submissions" in inspector.get_table_names():
        indexes = {index["name"] for index in inspector.get_indexes("submissions")}
        if "ix_submissions_user_id" not in indexes:
            op.create_index("ix_submissions_user_id", "submissions", ["user_id"])
    
    if "daily_reports" in inspector.get_table_names():
        indexes = {index["name"] for index in inspector.get_indexes("daily_reports")}
        if "ix_daily_reports_user_id" not in indexes:
            op.create_index("ix_daily_reports_user_id", "daily_reports", ["user_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    
    tables_with_user_id = [
        "attendance_records",
        "exams", 
        "quizzes",
        "announcements",
        "change_events",
        "class_schedules",
        "timetable_entries",
        "agent_runs",
        "notifications",
        "google_credentials",
        "agent_events",
        "assignment_materials",
        "assignment_solutions",
        "submissions",
        "daily_reports",
    ]
    
    for table in tables_with_user_id:
        if table not in inspector.get_table_names():
            continue
        indexes = {index["name"] for index in inspector.get_indexes(table)}
        user_index = f"ix_{table}_user_id"
        if user_index in indexes:
            op.drop_index(user_index, table_name=table)
    
    if "google_credentials" in inspector.get_table_names():
        indexes = {index["name"] for index in inspector.get_indexes("google_credentials")}
        if "ix_google_credentials_user_id" in indexes:
            op.drop_index("ix_google_credentials_user_id", table_name="google_credentials")
    
    for table in tables_with_user_id:
        if table not in inspector.get_table_names():
            continue
        columns = {column["name"] for column in inspector.get_columns(table)}
        if "user_id" in columns:
            with op.batch_alter_table(table) as batch:
                batch.drop_column("user_id")