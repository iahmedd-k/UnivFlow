import json
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
    AssignmentSolution,
    Submission,
    Setting,
    TimetableEntry,
)
from app.auth.clerk_auth import require_current_user
from app.core.redis import (
    attendance_summary_cache_key,
    get_attendance_cache_generation,
    get_json as redis_get_json,
    set_json as redis_set_json,
)
from app.services.alert_service import (
    normalize_subject_name,
    calculate_attendance_recovery,
    calculate_safe_bunks,
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


def _is_on_or_after(val, since_dt: Optional[datetime]) -> bool:
    if not since_dt or not val:
        return True
    try:
        if isinstance(val, datetime):
            target = val if val.tzinfo else val.replace(tzinfo=timezone.utc)
            return target >= since_dt
        if hasattr(val, 'year'): # date object
            return val >= since_dt.date()
        return True
    except Exception:
        return True


@router.get("/overview", response_model=dict)
def get_dashboard_overview(
    since: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    user: dict = Depends(require_current_user),
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
        courses = [c for c in courses if (c.created_at and _is_on_or_after(c.created_at, since_dt)) or (c.updated_at and _is_on_or_after(c.updated_at, since_dt)) or c.created_at is None]
    
    all_assignments = assignment_repo.get_all()
    if since_dt:
        all_assignments = [a for a in all_assignments if 
            (a.due_at and _is_on_or_after(a.due_at, since_dt)) or 
            (a.due_date and _is_on_or_after(a.due_date, since_dt)) or 
            (a.due_at is None and (a.created_at and _is_on_or_after(a.created_at, since_dt) or a.updated_at and _is_on_or_after(a.updated_at, since_dt)))
        ]
    
    upcoming_schedules = schedule_repo.get_upcoming(7)
    if since_dt:
        upcoming_schedules = [s for s in upcoming_schedules if s.date and _is_on_or_after(s.date, since_dt)]
    
    attendance_records = attendance_repo.get_all()
    if since_dt:
        attendance_records = [
            r for r in attendance_records
            if (r.last_updated and _is_on_or_after(r.last_updated, since_dt))
            or (r.created_at and _is_on_or_after(r.created_at, since_dt))
            or (r.last_updated is None and r.created_at is None)
        ]
    
    upcoming_exams = exam_repo.get_upcoming(30)
    if since_dt:
        upcoming_exams = [e for e in upcoming_exams if e.date and _is_on_or_after(e.date, since_dt)]
    
    upcoming_quizzes = quiz_repo.get_upcoming(30)
    if since_dt:
        upcoming_quizzes = [q for q in upcoming_quizzes if q.date and _is_on_or_after(q.date, since_dt)]
    
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

    user_id = str((user or {}).get("id") or "dev_student_user")
    academic_key = f"portal:{user_id}:portal_academic_summary"
    academic_setting = db.query(Setting).filter(Setting.key == academic_key).first()
    academic_summary = None
    if academic_setting and academic_setting.value:
        try:
            academic_summary = json.loads(academic_setting.value)
        except Exception:
            pass

    # AI Agent Solver & 4-Agent Crew Activity
    course_map = {c.id: c.name for c in courses}
    all_solutions = db.query(AssignmentSolution).all()
    solution_by_assign = {s.assignment_id: s for s in all_solutions}

    active_crew_runs = []
    ready_for_review_solutions = []

    for a in all_assignments:
        sol = solution_by_assign.get(a.id)
        if a.status == AssignmentStatus.GENERATING or (sol and not sol.validated_content and sol.ai_provider and not sol.validation_errors):
            progress_key = f"assignment_crew_progress_{a.id}"
            progress_row = db.query(Setting).filter(Setting.key == progress_key).first()
            crew_progress = None
            if progress_row and progress_row.value:
                try:
                    crew_progress = json.loads(progress_row.value)
                except Exception:
                    crew_progress = None
            active_crew_runs.append({
                "assignment_id": a.id,
                "title": a.title,
                "course_name": course_map.get(a.course_id, "Coursework"),
                "due_at": a.due_at,
                "status": "generating",
                "crew_progress": crew_progress,
                "generated_at": sol.generated_at if sol else None,
            })
        elif a.status == AssignmentStatus.READY_FOR_REVIEW or (sol and sol.validated_content):
            sub = db.query(Submission).filter(Submission.assignment_id == a.id).first()
            ready_for_review_solutions.append({
                "assignment_id": a.id,
                "title": a.title,
                "course_name": course_map.get(a.course_id, "Coursework"),
                "due_at": a.due_at,
                "status": "ready_for_review",
                "validated_at": sol.validated_at if sol else None,
                "google_doc_id": sub.google_doc_id if sub else None,
                "google_doc_url": f"https://docs.google.com/document/d/{sub.google_doc_id}/edit" if sub and sub.google_doc_id else None,
            })

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
        "academic_summary": academic_summary,
        "ai_agent_hub": {
            "active_crew_runs": active_crew_runs,
            "ready_for_review": ready_for_review_solutions[:5],
            "total_solved": len(ready_for_review_solutions),
            "active_count": len(active_crew_runs),
        },
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
    db: Session = Depends(get_db),
    user: dict = Depends(require_current_user),
):
    schedule_repo = ClassScheduleRepository(db)
    assignment_repo = AssignmentRepository(db)
    exam_repo = ExamRepository(db)
    quiz_repo = QuizRepository(db)

    since_dt = _get_semester_start_dt(db, since)
    
    schedules = schedule_repo.get_upcoming(days)
    if since_dt:
        schedules = [s for s in schedules if s.date and _is_on_or_after(s.date, since_dt)]
    
    all_assignments = assignment_repo.get_all()
    if since_dt:
        all_assignments = [a for a in all_assignments if 
            (a.due_at and _is_on_or_after(a.due_at, since_dt)) or 
            (a.due_date and _is_on_or_after(a.due_date, since_dt)) or 
            (a.due_at is None and (a.created_at and _is_on_or_after(a.created_at, since_dt) or a.updated_at and _is_on_or_after(a.updated_at, since_dt)))
        ]
    
    upcoming_assignments = [
        a for a in all_assignments
        if a.due_at and a.due_at <= datetime.now(timezone.utc) + timedelta(days=days)
        and a.status not in [AssignmentStatus.SUBMITTED, AssignmentStatus.APPROVED]
    ]
    exams = exam_repo.get_upcoming(days)
    if since_dt:
        exams = [e for e in exams if e.date and _is_on_or_after(e.date, since_dt)]
    
    quizzes = quiz_repo.get_upcoming(days)
    if since_dt:
        quizzes = [q for q in quizzes if q.date and _is_on_or_after(q.date, since_dt)]

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
    db: Session = Depends(get_db),
    user: dict = Depends(require_current_user),
):
    cache_enabled = db.get_bind().dialect.name != "sqlite"
    user_id = str((user or {}).get("id") or "dev_student_user")
    cache_generation = get_attendance_cache_generation() if cache_enabled else None
    cache_key = (
        attendance_summary_cache_key(user_id, cache_generation)
        if cache_generation is not None
        else None
    )
    if cache_key:
        cached = redis_get_json(cache_key)
        if cached is not None:
            return cached

    attendance_repo = AttendanceRecordRepository(db)
    course_repo = CourseRepository(db)

    # This endpoint serves the portal's current cumulative snapshot. Filtering
    # it by record sync timestamps would incorrectly drop courses registered earlier.
    records = attendance_repo.get_all()
    courses = course_repo.get_all()
    course_by_id = {course.id: course for course in courses}
    weekly_classes = {}
    for entry in db.query(TimetableEntry).all():
        subject_key = normalize_subject_name(entry.subject)
        if subject_key:
            weekly_classes.setdefault(subject_key, set()).add(
                (entry.weekday, entry.start_time, entry.end_time)
            )

    summary = []
    total_attended = 0
    total_held = 0
    for record in records:
        course = course_by_id.get(record.course_id)
        c_name = course.name if course else record.subject
        held = record.total
        attended = record.attended
        is_legacy_portal_placeholder = (
            str(record.external_id or "").startswith("portal-attendance:")
            and held == 100
        )
        has_valid_counts = (
            not is_legacy_portal_placeholder
            and held is not None
            and held > 0
            and attended is not None
            and 0 <= attended <= held
        )
        if not has_valid_counts:
            held = None
            attended = None

        pct = (
            round(attended * 100 / held, 2)
            if has_valid_counts
            else float(record.percentage) if record.percentage is not None else None
        )
        subject_key = normalize_subject_name(record.subject or c_name or "")
        scheduled_classes = weekly_classes.get(subject_key, set())
        absent = held - attended if has_valid_counts else None

        if has_valid_counts:
            total_attended += attended
            total_held += held

        recovery_needed = calculate_attendance_recovery(attended, held) if (has_valid_counts and pct is not None and pct < 75.0) else 0
        safe_bunks = calculate_safe_bunks(attended, held) if (has_valid_counts and pct is not None and pct >= 75.0) else 0

        summary.append({
            "course_id": record.course_id,
            "course_name": c_name,
            "subject": record.subject,
            "attended": attended,
            "total": held,
            "held": held,
            "absent": absent,
            "percentage": pct,
            "recovery_needed": recovery_needed,
            "safe_bunks": safe_bunks,
            "registration_date": None,
            "classes_per_week": len(scheduled_classes),
            "weekly_schedule_available": bool(scheduled_classes),
            "planned_since_registration": None,
        })

    overall = round(total_attended * 100 / total_held, 2) if total_held else None

    result = {
        "overall_attendance": overall,
        "counted_attended": total_attended,
        "counted_held": total_held,
        "per_course": summary,
    }
    if cache_key:
        redis_set_json(cache_key, result, ttl_seconds=20)
    return result


@router.get("/assignments-by-status", response_model=dict)
def get_assignments_by_status(
    since: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    user: dict = Depends(require_current_user),
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
