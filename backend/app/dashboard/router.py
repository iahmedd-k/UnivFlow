from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime, timedelta, timezone

from app.db.database import get_db
from app.db.repositories import (
    CourseRepository,
    AssignmentRepository,
    ClassScheduleRepository,
    AttendanceRecordRepository,
    ExamRepository,
    QuizRepository,
    AgentRunRepository,
)
from app.db.models import (
    Course,
    Assignment,
    ClassSchedule,
    AttendanceRecord,
    Exam,
    Quiz,
    AssignmentStatus,
    Setting,
)

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


def _get_semester_start_dt(db: Session, override: Optional[str] = None) -> Optional[datetime]:
    """Get semester start date from database settings if configured"""
    val = override
    if not val:
        setting = db.query(Setting).filter(Setting.key == "semester_start_date").first()
        if setting and setting.value:
            val = setting.value.strip().replace('"', '')
    if val:
        try:
            if len(val) == 10:
                dt = datetime.fromisoformat(f"{val}T00:00:00+00:00")
            else:
                dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            pass
    return None


@router.get("/overview", response_model=dict)
def get_dashboard_overview(
    since: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    course_repo = CourseRepository(db)
    assignment_repo = AssignmentRepository(db)
    schedule_repo = ClassScheduleRepository(db)
    attendance_repo = AttendanceRecordRepository(db)
    exam_repo = ExamRepository(db)
    quiz_repo = QuizRepository(db)
    agent_repo = AgentRunRepository(db)

    since_dt = _get_semester_start_dt(db, since)
    
    courses = course_repo.get_all()
    if since_dt:
        courses = [c for c in courses if (c.created_at and c.created_at >= since_dt) or (c.updated_at and c.updated_at >= since_dt) or c.created_at is None]
    
    all_assignments = assignment_repo.get_all()
    if since_dt:
        all_assignments = [a for a in all_assignments if 
            (a.due_at and a.due_at >= since_dt) or 
            (a.due_date and a.due_date >= since_dt) or 
            (a.due_at is None and (a.created_at and a.created_at >= since_dt or a.updated_at and a.updated_at >= since_dt))
        ]
    
    upcoming_schedules = schedule_repo.get_upcoming(7)
    if since_dt:
        upcoming_schedules = [s for s in upcoming_schedules if s.date and s.date >= since_dt.date()]
    
    attendance_records = attendance_repo.get_all()
    if since_dt:
        attendance_records = [
            r for r in attendance_records
            if (r.last_updated and r.last_updated >= since_dt)
            or (r.created_at and r.created_at >= since_dt)
            or (r.last_updated is None and r.created_at is None)
        ]
    
    upcoming_exams = exam_repo.get_upcoming(30)
    if since_dt:
        upcoming_exams = [e for e in upcoming_exams if e.date and e.date >= since_dt.date()]
    
    upcoming_quizzes = quiz_repo.get_upcoming(30)
    if since_dt:
        upcoming_quizzes = [q for q in upcoming_quizzes if q.date and q.date >= since_dt.date()]
    
    recent_agent_runs = agent_repo.get_recent(5)

    submitted_states = {"TURNED_IN", "RETURNED"}
    is_submitted = lambda assignment: assignment.status in [AssignmentStatus.SUBMITTED, AssignmentStatus.APPROVED] or (assignment.submission_state and assignment.submission_state.value in submitted_states)
    pending_assignments = [a for a in all_assignments if not is_submitted(a) and a.status in [AssignmentStatus.PENDING, AssignmentStatus.DRAFT, AssignmentStatus.READY_FOR_REVIEW]]
    def is_past_due(assignment):
        due_at = assignment.due_at or assignment.due_date
        if due_at is None:
            return False
        if due_at.tzinfo is None:
            due_at = due_at.replace(tzinfo=timezone.utc)
        return due_at < datetime.now(timezone.utc)

    overdue_assignments = [a for a in all_assignments if is_past_due(a) and not is_submitted(a)]
    completed_assignments = [a for a in all_assignments if is_submitted(a)]

    active_courses = [c for c in courses if not c.course_state or c.course_state.upper() == "ACTIVE"]
    avg_attendance = sum(r.percentage for r in attendance_records) / len(attendance_records) if attendance_records else 0

    return {
        "courses_count": len(active_courses),
        "assignments": {
            "total": len(all_assignments),
            "pending": len(pending_assignments),
            "overdue": len(overdue_assignments),
            "completed": len(completed_assignments),
        },
        "upcoming_classes": len(upcoming_schedules),
        "upcoming_exams": len(upcoming_exams),
        "upcoming_quizzes": len(upcoming_quizzes),
        "average_attendance": round(avg_attendance, 2),
        "recent_agent_runs": [
            {
                "id": r.id,
                "trigger": r.trigger.value,
                "status": r.status.value,
                "started_at": r.started_at,
                "finished_at": r.finished_at,
                "assignments_found": r.assignments_found,
                "changes_found": r.changes_found,
                "notifications_sent": r.notifications_sent,
            }
            for r in recent_agent_runs
        ],
    }


@router.get("/upcoming", response_model=dict)
def get_upcoming_items(
    days: int = 7,
    since: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    schedule_repo = ClassScheduleRepository(db)
    assignment_repo = AssignmentRepository(db)
    exam_repo = ExamRepository(db)
    quiz_repo = QuizRepository(db)

    since_dt = _get_semester_start_dt(db, since)
    
    schedules = schedule_repo.get_upcoming(days)
    if since_dt:
        schedules = [s for s in schedules if s.date and s.date >= since_dt.date()]
    
    all_assignments = assignment_repo.get_all()
    if since_dt:
        all_assignments = [a for a in all_assignments if 
            (a.due_at and a.due_at >= since_dt) or 
            (a.due_date and a.due_date >= since_dt) or 
            (a.due_at is None and (a.created_at and a.created_at >= since_dt or a.updated_at and a.updated_at >= since_dt))
        ]
    
    upcoming_assignments = [
        a for a in all_assignments
        if a.due_at and a.due_at <= datetime.now(timezone.utc) + timedelta(days=days)
        and a.status not in [AssignmentStatus.SUBMITTED, AssignmentStatus.APPROVED]
    ]
    exams = exam_repo.get_upcoming(days)
    if since_dt:
        exams = [e for e in exams if e.date and e.date >= since_dt.date()]
    
    quizzes = quiz_repo.get_upcoming(days)
    if since_dt:
        quizzes = [q for q in quizzes if q.date and q.date >= since_dt.date()]

    return {
        "classes": [
            {
                "id": s.id,
                "subject": s.subject,
                "date": s.date,
                "start_time": s.start_time,
                "end_time": s.end_time,
                "teacher": s.teacher,
                "room": s.room,
            }
            for s in schedules
        ],
        "assignments": [
            {
                "id": a.id,
                "title": a.title,
                "due_at": a.due_at,
                "course_id": a.course_id,
                "status": a.status.value if a.status else None,
            }
            for a in upcoming_assignments
        ],
        "exams": [
            {
                "id": e.id,
                "title": e.title,
                "date": e.date,
                "time": e.time,
                "room": e.room,
            }
            for e in exams
        ],
        "quizzes": [
            {
                "id": q.id,
                "title": q.title,
                "date": q.date,
                "time": q.time,
                "room": q.room,
            }
            for q in quizzes
        ],
    }


@router.get("/attendance-summary", response_model=dict)
def get_attendance_summary(
    since: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    attendance_repo = AttendanceRecordRepository(db)
    course_repo = CourseRepository(db)

    since_dt = _get_semester_start_dt(db, since)
    
    records = attendance_repo.get_all()
    if since_dt:
        records = [
            r for r in records
            if (r.last_updated and r.last_updated >= since_dt)
            or (r.created_at and r.created_at >= since_dt)
            or (r.last_updated is None and r.created_at is None)
        ]
    
    courses = course_repo.get_all()
    if since_dt:
        courses = [c for c in courses if (c.created_at and c.created_at >= since_dt) or (c.updated_at and c.updated_at >= since_dt) or c.created_at is None]

    summary = []
    for record in records:
        course = next((c for c in courses if c.id == record.course_id), None)
        summary.append({
            "course_id": record.course_id,
            "course_name": course.name if course else "Unknown",
            "subject": record.subject,
            "attended": record.attended,
            "total": record.total,
            "percentage": record.percentage,
        })

    overall = sum(r.percentage for r in records) / len(records) if records else 0

    return {
        "overall_attendance": round(overall, 2),
        "per_course": summary,
    }


@router.get("/assignments-by-status", response_model=dict)
def get_assignments_by_status(
    since: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    assignment_repo = AssignmentRepository(db)
    all_assignments = assignment_repo.get_all()
    
    since_dt = _get_semester_start_dt(db, since)
    if since_dt:
        all_assignments = [a for a in all_assignments if (a.due_at and a.due_at >= since_dt) or (a.created_at and a.created_at >= since_dt) or (a.updated_at and a.updated_at >= since_dt) or a.due_at is None]

    by_status = {}
    for status in AssignmentStatus:
        by_status[status.value] = len([a for a in all_assignments if a.status == status])

    return {
        "by_status": by_status,
        "total": len(all_assignments),
    }
