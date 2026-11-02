"""Add composite indexes for user-scoped dashboard and coursework reads."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "m7_user_read_indexes"
down_revision: Union[str, Sequence[str], None] = "m6_schedule_user_unique"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


INDEXES = (
    ("ix_assignments_user_due_id", "assignments", ["user_id", "due_at", "id"]),
    ("ix_assignment_materials_user_assignment", "assignment_materials", ["user_id", "assignment_id"]),
    ("ix_class_schedules_user_date", "class_schedules", ["user_id", "date"]),
    ("ix_timetable_entries_user_weekday_start", "timetable_entries", ["user_id", "weekday", "start_time"]),
    ("ix_attendance_records_user_course", "attendance_records", ["user_id", "course_id"]),
    ("ix_courses_user_name_id", "courses", ["user_id", "name", "id"]),
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for name, table, columns in INDEXES:
        if table not in inspector.get_table_names():
            continue
        existing_names = {index["name"] for index in inspector.get_indexes(table)}
        if name not in existing_names:
            op.create_index(name, table, columns, unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for name, table, _columns in reversed(INDEXES):
        if table in inspector.get_table_names():
            existing_names = {index["name"] for index in inspector.get_indexes(table)}
            if name in existing_names:
                op.drop_index(name, table_name=table)
