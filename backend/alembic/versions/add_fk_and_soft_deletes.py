"""Add FK constraints, soft deletes, and materialized views

Revision ID: add_fk_and_soft_deletes
Revises: add_missing_user_id
Create Date: 2026-10-14
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = "add_fk_and_soft_deletes"
down_revision: Union[str, Sequence[str], None] = "add_missing_user_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    
    # Add soft delete columns to main tables
    tables_with_soft_delete = [
        "courses",
        "assignments",
        "class_schedules",
        "attendance_records",
        "exams",
        "quizzes",
        "announcements",
        "agent_runs",
        "notifications",
        "google_credentials",
    ]
    
    for table in tables_with_soft_delete:
        if table not in inspector.get_table_names():
            continue
        columns = {column["name"] for column in inspector.get_columns(table)}
        if "deleted_at" not in columns:
            op.add_column(table, sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
        if "deleted_by" not in columns:
            op.add_column(table, sa.Column("deleted_by", sa.String(length=255), nullable=True))
    
    # Add FK constraints where missing
    # assignments -> courses
    if "assignments" in inspector.get_table_names() and "courses" in inspector.get_table_names():
        fks = inspector.get_foreign_keys("assignments")
        fk_names = {fk["name"] for fk in fks}
        if "fk_assignments_course_id" not in fk_names:
            op.create_foreign_key(
                "fk_assignments_course_id",
                "assignments", "courses",
                ["course_id"], ["id"],
                ondelete="CASCADE"
            )
    
    # attendance_records -> courses
    if "attendance_records" in inspector.get_table_names() and "courses" in inspector.get_table_names():
        fks = inspector.get_foreign_keys("attendance_records")
        fk_names = {fk["name"] for fk in fks}
        if "fk_attendance_records_course_id" not in fk_names:
            op.create_foreign_key(
                "fk_attendance_records_course_id",
                "attendance_records", "courses",
                ["course_id"], ["id"],
                ondelete="CASCADE"
            )
    
    # class_schedules -> courses
    if "class_schedules" in inspector.get_table_names() and "courses" in inspector.get_table_names():
        fks = inspector.get_foreign_keys("class_schedules")
        fk_names = {fk["name"] for fk in fks}
        if "fk_class_schedules_course_id" not in fk_names:
            op.create_foreign_key(
                "fk_class_schedules_course_id",
                "class_schedules", "courses",
                ["course_id"], ["id"],
                ondelete="CASCADE"
            )
    
    # exams -> courses
    if "exams" in inspector.get_table_names() and "courses" in inspector.get_table_names():
        fks = inspector.get_foreign_keys("exams")
        fk_names = {fk["name"] for fk in fks}
        if "fk_exams_course_id" not in fk_names:
            op.create_foreign_key(
                "fk_exams_course_id",
                "exams", "courses",
                ["course_id"], ["id"],
                ondelete="SET NULL"
            )
    
    # quizzes -> courses
    if "quizzes" in inspector.get_table_names() and "courses" in inspector.get_table_names():
        fks = inspector.get_foreign_keys("quizzes")
        fk_names = {fk["name"] for fk in fks}
        if "fk_quizzes_course_id" not in fk_names:
            op.create_foreign_key(
                "fk_quizzes_course_id",
                "quizzes", "courses",
                ["course_id"], ["id"],
                ondelete="SET NULL"
            )
    
    # assignment_materials -> assignments
    if "assignment_materials" in inspector.get_table_names() and "assignments" in inspector.get_table_names():
        fks = inspector.get_foreign_keys("assignment_materials")
        fk_names = {fk["name"] for fk in fks}
        if "fk_assignment_materials_assignment_id" not in fk_names:
            op.create_foreign_key(
                "fk_assignment_materials_assignment_id",
                "assignment_materials", "assignments",
                ["assignment_id"], ["id"],
                ondelete="CASCADE"
            )
    
    # assignment_solutions -> assignments
    if "assignment_solutions" in inspector.get_table_names() and "assignments" in inspector.get_table_names():
        fks = inspector.get_foreign_keys("assignment_solutions")
        fk_names = {fk["name"] for fk in fks}
        if "fk_assignment_solutions_assignment_id" not in fk_names:
            op.create_foreign_key(
                "fk_assignment_solutions_assignment_id",
                "assignment_solutions", "assignments",
                ["assignment_id"], ["id"],
                ondelete="CASCADE"
            )
    
    # submissions -> assignments
    if "submissions" in inspector.get_table_names() and "assignments" in inspector.get_table_names():
        fks = inspector.get_foreign_keys("submissions")
        fk_names = {fk["name"] for fk in fks}
        if "fk_submissions_assignment_id" not in fk_names:
            op.create_foreign_key(
                "fk_submissions_assignment_id",
                "submissions", "assignments",
                ["assignment_id"], ["id"],
                ondelete="CASCADE"
            )
    
    # browser_automation_jobs -> assignments
    if "browser_automation_jobs" in inspector.get_table_names() and "assignments" in inspector.get_table_names():
        fks = inspector.get_foreign_keys("browser_automation_jobs")
        fk_names = {fk["name"] for fk in fks}
        if "fk_browser_automation_jobs_assignment_id" not in fk_names:
            op.create_foreign_key(
                "fk_browser_automation_jobs_assignment_id",
                "browser_automation_jobs", "assignments",
                ["assignment_id"], ["id"],
                ondelete="CASCADE"
            )
    
    # agent_events -> agent_runs
    if "agent_events" in inspector.get_table_names() and "agent_runs" in inspector.get_table_names():
        fks = inspector.get_foreign_keys("agent_events")
        fk_names = {fk["name"] for fk in fks}
        if "fk_agent_events_run_id" not in fk_names:
            op.create_foreign_key(
                "fk_agent_events_run_id",
                "agent_events", "agent_runs",
                ["run_id"], ["id"],
                ondelete="CASCADE"
            )
    
    # notification_preferences -> notification_templates (if tables exist)
    if "notification_preferences" in inspector.get_table_names() and "notification_templates" in inspector.get_table_names():
        pass  # No direct FK needed
    
    # Create materialized views for dashboard performance (PostgreSQL only)
    if bind.dialect.name == "postgresql":
        op.execute("""
            CREATE MATERIALIZED VIEW IF NOT EXISTS mv_dashboard_overview AS
            SELECT 
                u.user_id,
                COUNT(DISTINCT c.id) as courses_count,
                COUNT(DISTINCT a.id) as total_assignments,
                COUNT(DISTINCT CASE 
                    WHEN a.status::text IN ('PENDING', 'DRAFT', 'READY_FOR_REVIEW', 'pending', 'draft', 'ready_for_review') 
                    AND a.due_at > NOW() THEN a.id 
                END) as pending_assignments,
                COUNT(DISTINCT CASE 
                    WHEN a.status::text IN ('PENDING', 'DRAFT', 'READY_FOR_REVIEW', 'pending', 'draft', 'ready_for_review') 
                    AND a.due_at < NOW() THEN a.id 
                END) as overdue_assignments,
                COUNT(DISTINCT CASE 
                    WHEN a.status::text IN ('SUBMITTED', 'APPROVED', 'submitted', 'approved') THEN a.id 
                END) as completed_assignments,
                AVG(ar.percentage) as average_attendance,
                COUNT(DISTINCT cs.id) as upcoming_classes,
                COUNT(DISTINCT e.id) as upcoming_exams,
                COUNT(DISTINCT q.id) as upcoming_quizzes
            FROM 
                (SELECT DISTINCT user_id FROM courses) u
                LEFT JOIN courses c ON c.user_id = u.user_id AND c.deleted_at IS NULL
                LEFT JOIN assignments a ON a.user_id = u.user_id AND a.deleted_at IS NULL
                LEFT JOIN attendance_records ar ON ar.user_id = u.user_id AND ar.deleted_at IS NULL
                LEFT JOIN class_schedules cs ON cs.user_id = u.user_id AND cs.deleted_at IS NULL AND cs.date > NOW()
                LEFT JOIN exams e ON e.user_id = u.user_id AND e.deleted_at IS NULL AND e.date > NOW()
                LEFT JOIN quizzes q ON q.user_id = u.user_id AND q.deleted_at IS NULL AND q.date > NOW()
            GROUP BY u.user_id
            WITH DATA;
        """)
        
        # Create index for materialized view
        op.execute("CREATE UNIQUE INDEX IF NOT EXISTS mv_dashboard_overview_user_id_idx ON mv_dashboard_overview (user_id);")
        
        # Create materialized view for attendance summary
        op.execute("""
            CREATE MATERIALIZED VIEW IF NOT EXISTS mv_attendance_summary AS
            SELECT 
                ar.user_id,
                ar.course_id,
                c.name as course_name,
                ar.subject,
                ar.attended,
                ar.total,
                ar.percentage,
                ar.last_updated
            FROM attendance_records ar
            JOIN courses c ON c.id = ar.course_id
            WHERE ar.deleted_at IS NULL AND c.deleted_at IS NULL
            WITH DATA;
        """)
        
        op.execute("CREATE INDEX IF NOT EXISTS mv_attendance_summary_user_id_idx ON mv_attendance_summary (user_id);")
        
        # Create materialized view for assignment summary
        op.execute("""
            CREATE MATERIALIZED VIEW IF NOT EXISTS mv_assignment_summary AS
            SELECT 
                a.user_id,
                a.id as assignment_id,
                a.title,
                a.course_id,
                c.name as course_name,
                a.due_at,
                a.status,
                a.submission_state,
                CASE 
                    WHEN a.due_at < NOW() AND a.status::text NOT IN ('SUBMITTED', 'APPROVED', 'submitted', 'approved') THEN true 
                    ELSE false 
                END as is_overdue
            FROM assignments a
            JOIN courses c ON c.id = a.course_id
            WHERE a.deleted_at IS NULL AND c.deleted_at IS NULL
            WITH DATA;
        """)
        
        op.execute("CREATE INDEX IF NOT EXISTS mv_assignment_summary_user_id_idx ON mv_assignment_summary (user_id);")
        op.execute("CREATE INDEX IF NOT EXISTS mv_assignment_summary_due_at_idx ON mv_assignment_summary (due_at);")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    
    # Drop materialized views (PostgreSQL only)
    if bind.dialect.name == "postgresql":
        op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_dashboard_overview;")
        op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_attendance_summary;")
        op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_assignment_summary;")
    
    # Drop FK constraints
    fk_constraints = [
        ("fk_assignments_course_id", "assignments"),
        ("fk_attendance_records_course_id", "attendance_records"),
        ("fk_class_schedules_course_id", "class_schedules"),
        ("fk_exams_course_id", "exams"),
        ("fk_quizzes_course_id", "quizzes"),
        ("fk_assignment_materials_assignment_id", "assignment_materials"),
        ("fk_assignment_solutions_assignment_id", "assignment_solutions"),
        ("fk_submissions_assignment_id", "submissions"),
        ("fk_browser_automation_jobs_assignment_id", "browser_automation_jobs"),
        ("fk_agent_events_run_id", "agent_events"),
    ]
    
    for fk_name, table in fk_constraints:
        if table in inspector.get_table_names():
            fks = inspector.get_foreign_keys(table)
            if any(fk["name"] == fk_name for fk in fks):
                op.drop_constraint(fk_name, table, type_="foreignkey")
    
    # Remove soft delete columns
    tables_with_soft_delete = [
        "courses",
        "assignments",
        "class_schedules",
        "attendance_records",
        "exams",
        "quizzes",
        "announcements",
        "agent_runs",
        "notifications",
        "google_credentials",
    ]
    
    for table in tables_with_soft_delete:
        if table not in inspector.get_table_names():
            continue
        columns = {column["name"] for column in inspector.get_columns(table)}
        if "deleted_at" in columns:
            op.drop_column(table, "deleted_at")
        if "deleted_by" in columns:
            op.drop_column(table, "deleted_by")


from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa