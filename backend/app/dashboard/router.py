import json
import logging
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import or_
from typing import List, Optional
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

from app.db.database import get_db
from app.db.repositories import (
    CourseRepository,
    AssignmentRepository,
    ClassScheduleRepository,
    AttendanceRecordRepository,
    ExamRepository,
)
from app.db.models import (
    Course,
    Assignment,
    ClassSchedule,
    AttendanceRecord,
    Exam,
    AssignmentStatus,
    SubmissionState,
    AssignmentSolution,
    Submission,
    BrowserAutomationJob,
    Setting,
    TimetableEntry,
)
from app.auth.clerk_auth import require_current_user
from app.auth.ownership import user_owner_ids
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


@router.get("/automation-history", response_model=List[dict])
def get_automation_history(
    limit: int = Query(40, ge=1, le=100),
    db: Session = Depends(get_db),
    user: dict = Depends(require_current_user),
):
    """Return this account's Claude solve and Classroom turn-in history."""
    user_id = str((user or {}).get("id") or "dev_student_user")
    owners = user_owner_ids(user_id)
    history = []

    jobs = (
        db.query(BrowserAutomationJob)
        .join(Assignment, BrowserAutomationJob.assignment_id == Assignment.id)
        .filter(BrowserAutomationJob.user_id.in_(owners), Assignment.user_id.in_(owners))
        .order_by(BrowserAutomationJob.queued_at.desc())
        .limit(limit)
        .all()
    )
    for job in jobs:
        assignment = job.assignment
        course = assignment.course if assignment and assignment.course and assignment.course.user_id in owners else None
        history.append({
            "id": f"claude-{job.id}",
            "kind": "claude_assignment",
            "assignment_id": job.assignment_id,
            "assignment_title": assignment.title if assignment else "Assignment",
            "course_name": course.name if course else "Course",
            "status": job.status,
            "started_at": job.started_at,
            "finished_at": job.finished_at,
            "created_at": job.queued_at,
            "error": job.error,
            "retryable": job.status in {"failed", "needs_login", "cancelled"},
        })

    submissions = (
        db.query(Submission)
        .join(Assignment, Submission.assignment_id == Assignment.id)
        .filter(Submission.user_id.in_(owners), Assignment.user_id.in_(owners))
        .order_by(Submission.submitted_at.desc().nullslast(), Submission.created_at.desc())
        .limit(limit)
        .all()
    )
    for submission in submissions:
        assignment = submission.assignment
        course = assignment.course if assignment and assignment.course and assignment.course.user_id in owners else None
        state = getattr(submission.submission_state, "value", submission.submission_state) or "unknown"
        history.append({
            "id": f"turn-in-{submission.id}",
            "kind": "classroom_turn_in",
            "assignment_id": submission.assignment_id,
            "assignment_title": assignment.title if assignment else "Assignment",
            "course_name": course.name if course else "Course",
            "status": state,
            "started_at": submission.submitted_at or submission.created_at,
            "finished_at": submission.submitted_at,
            "created_at": submission.created_at,
            "error": None,
            "retryable": state != SubmissionState.TURNED_IN.value and bool(submission.google_doc_id and submission.google_drive_file_id),
        })

    def _sort_timestamp(item):
        stamp = item.get("started_at") or item.get("created_at")
        if not stamp:
            return 0.0
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        return stamp.timestamp()

    history.sort(key=_sort_timestamp, reverse=True)
    return history[:limit]


def _get_semester_start_dt(
    db: Session,
    override: Optional[str] = None,
    user_id: str = "legacy",
) -> Optional[datetime]:
    """Get semester start date from database settings if configured"""
    val = override if isinstance(override, str) else None
    if not val:
        setting = db.query(Setting).filter(
            Setting.key == f"classroom:{user_id}:semester_start_date"
        ).first()
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
            if override:
                raise HTTPException(status_code=400, detail="Invalid 'since' date format. Use YYYY-MM-DD or ISO 8601.")
            logger.warning("Invalid semester_start_date setting for user %s: %s", user_id, val)
            return None
    return None


def _is_on_or_after(val, since_dt: Optional[datetime]) -> bool:
    if not since_dt or not val:
        return True
    try:
        if isinstance(val, datetime):
            target = val if val.tzinfo else val.replace(tzinfo=timezone.utc)
            return target >= since_dt
        if hasattr(val, 'year'):
            return val >= since_dt.date()
        return True
    except Exception:
        return True


def _filter_by_since_dt(items, since_dt: Optional[datetime], date_fields: List[str]):
    """Filter items by since_dt using specified date fields."""
    if not since_dt:
        return items
    return [item for item in items if any(
        getattr(item, field, None) and _is_on_or_after(getattr(item, field), since_dt)
        for field in date_fields
    )]


def _get_user_dashboard_data(db: Session, user_id: str, since_dt: Optional[datetime]):
    """Get all dashboard data for a user in a consolidated query."""
    course_repo = CourseRepository(db)
    assignment_repo = AssignmentRepository(db)
    schedule_repo = ClassScheduleRepository(db)
    attendance_repo = AttendanceRecordRepository(db)
    exam_repo = ExamRepository(db)

    courses = course_repo.get_all(user_id=user_id)
    courses = _filter_by_since_dt(courses, since_dt, ['created_at', 'updated_at'])
    owned_course_ids = {course.id for course in courses}

    all_assignments = assignment_repo.get_all(user_id=user_id)
    all_assignments = _filter_by_since_dt(all_assignments, since_dt, ['due_at', 'due_date', 'created_at', 'updated_at'])

    upcoming_schedules = [
        schedule for schedule in schedule_repo.get_upcoming(7, user_id=user_id)
        if schedule.course_id in owned_course_ids
    ]
    upcoming_schedules = _filter_by_since_dt(upcoming_schedules, since_dt, ['date'])

    attendance_records = [
        record for record in attendance_repo.get_all(user_id=user_id)
        if record.course_id in owned_course_ids
    ]
    attendance_records = _filter_by_since_dt(attendance_records, since_dt, ['last_updated', 'created_at'])

    upcoming_exams = [
        exam for exam in exam_repo.get_upcoming(30, user_id=user_id)
        if exam.course_id is None or exam.course_id in owned_course_ids
    ]
    upcoming_exams = _filter_by_since_dt(upcoming_exams, since_dt, ['date'])

    return {
        "courses": courses,
        "all_assignments": all_assignments,
        "upcoming_schedules": upcoming_schedules,
        "attendance_records": attendance_records,
        "upcoming_exams": upcoming_exams,
        "owned_course_ids": owned_course_ids,
    }


@router.get("/overview", response_model=dict)
def get_dashboard_overview(
    since: Optional[str] = Query(None, description="Filter data since this date (YYYY-MM-DD or ISO 8601)"),
    db: Session = Depends(get_db),
    user: dict = Depends(require_current_user),
):
    user_id = str((user or {}).get("id") or "dev_student_user")
    since_dt = _get_semester_start_dt(db, since, user_id)
    data = _get_user_dashboard_data(db, user_id, since_dt)

    submitted_states = {"TURNED_IN", "RETURNED"}
    is_submitted = lambda assignment: assignment.status in [AssignmentStatus.SUBMITTED, AssignmentStatus.APPROVED] or (assignment.submission_state and assignment.submission_state.value in submitted_states)
    pending_assignments = [a for a in data["all_assignments"] if not is_submitted(a) and a.status in [AssignmentStatus.PENDING, AssignmentStatus.DRAFT, AssignmentStatus.READY_FOR_REVIEW]]
    
    def is_past_due(assignment):
        due_at = assignment.due_at or assignment.due_date
        if due_at is None:
            return False
        if due_at.tzinfo is None:
            due_at = due_at.replace(tzinfo=timezone.utc)
        return due_at < datetime.now(timezone.utc)

    overdue_assignments = [a for a in data["all_assignments"] if is_past_due(a) and not is_submitted(a)]
    completed_assignments = [a for a in data["all_assignments"] if is_submitted(a)]

    active_courses = [c for c in data["courses"] if not c.course_state or c.course_state.upper() == "ACTIVE"]
    avg_attendance = sum(r.percentage for r in data["attendance_records"]) / len(data["attendance_records"]) if data["attendance_records"] else 0

    academic_key = f"portal:{user_id}:portal_academic_summary"
    academic_setting = db.query(Setting).filter(Setting.key == academic_key).first()
    academic_summary = None
    if academic_setting and academic_setting.value:
        try:
            academic_summary = json.loads(academic_setting.value)
        except Exception:
            pass

    course_map = {c.id: c.name for c in data["courses"]}
    
    # Only active, non-submitted assignments can be generating or ready for review
    candidate_assignments = [
        a for a in data["all_assignments"]
        if a.status not in (AssignmentStatus.SUBMITTED, AssignmentStatus.APPROVED)
    ]
    candidate_ids = [a.id for a in candidate_assignments]

    # Fast column projection without loading full text payloads or triggering relationship cascades
    sol_rows = db.query(
        AssignmentSolution.assignment_id,
        AssignmentSolution.generated_at,
        AssignmentSolution.validated_at,
        (AssignmentSolution.validated_content != None).label("has_validated_content")
    ).filter(AssignmentSolution.assignment_id.in_(candidate_ids)).all() if candidate_ids else []
    solution_by_assign = {s.assignment_id: s for s in sol_rows}

    # Batch progress settings for generating assignments
    generating_ids = [a.id for a in candidate_assignments if a.status == AssignmentStatus.GENERATING]
    progress_keys = [f"assignment_crew_progress_{aid}" for aid in generating_ids]
    progress_rows = db.query(Setting.key, Setting.value).filter(Setting.key.in_(progress_keys)).all() if progress_keys else []
    progress_by_key = {r.key: r.value for r in progress_rows}

    # Batch submissions for ready-for-review assignments
    ready_assign_ids = [
        a.id for a in candidate_assignments
        if (a.status == AssignmentStatus.READY_FOR_REVIEW or (solution_by_assign.get(a.id) and solution_by_assign.get(a.id).has_validated_content))
    ]
    sub_rows = db.query(
        Submission.assignment_id,
        Submission.google_doc_id
    ).filter(Submission.assignment_id.in_(ready_assign_ids)).all() if ready_assign_ids else []
    sub_by_assign = {s.assignment_id: s for s in sub_rows}

    active_crew_runs = []
    ready_for_review_solutions = []
    stale_generating_ids = []

    now_utc = datetime.now(timezone.utc)
    stale_threshold = timedelta(minutes=20)

    for a in candidate_assignments:
        sol = solution_by_assign.get(a.id)
        is_generating = False
        crew_progress = None

        if a.status == AssignmentStatus.GENERATING:
            progress_key = f"assignment_crew_progress_{a.id}"
            progress_val = progress_by_key.get(progress_key)
            if progress_val:
                try:
                    crew_progress = json.loads(progress_val)
                except Exception:
                    crew_progress = None

            last_activity = sol.generated_at if sol else (a.updated_at or a.created_at)
            if isinstance(crew_progress, dict) and crew_progress.get("updated_at"):
                try:
                    updated_dt = datetime.fromisoformat(crew_progress["updated_at"])
                    if updated_dt.tzinfo is None:
                        updated_dt = updated_dt.replace(tzinfo=timezone.utc)
                    if last_activity:
                        if last_activity.tzinfo is None:
                            last_activity = last_activity.replace(tzinfo=timezone.utc)
                        last_activity = max(last_activity, updated_dt)
                    else:
                        last_activity = updated_dt
                except Exception:
                    pass

            if last_activity and last_activity.tzinfo is None:
                last_activity = last_activity.replace(tzinfo=timezone.utc)

            # Auto-recover stale generating assignments
            if last_activity and (now_utc - last_activity) > stale_threshold:
                stale_generating_ids.append(a.id)
            else:
                is_finished = False
                if isinstance(crew_progress, dict):
                    if crew_progress.get("error") or crew_progress.get("status") == "failed":
                        is_finished = True
                    elif crew_progress.get("current_step") and crew_progress.get("total_steps"):
                        if crew_progress["current_step"] >= crew_progress["total_steps"]:
                            is_finished = True
                if not is_finished:
                    is_generating = True

        if is_generating:
            active_crew_runs.append({
                "assignment_id": a.id,
                "title": a.title,
                "course_name": course_map.get(a.course_id, "Coursework"),
                "due_at": a.due_at,
                "status": "generating",
                "crew_progress": crew_progress,
                "generated_at": sol.generated_at if sol else None,
            })
        elif a.status == AssignmentStatus.READY_FOR_REVIEW or (sol and sol.has_validated_content):
            sub = sub_by_assign.get(a.id)
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

    if stale_generating_ids:
        try:
            db.query(Assignment).filter(Assignment.id.in_(stale_generating_ids)).update({Assignment.status: AssignmentStatus.DRAFT}, synchronize_session=False)
            db.commit()
        except Exception as commit_err:
            db.rollback()
            logger.warning("Could not commit stale auto-recovery: %s", commit_err)

    missing_labs = [a for a in data["all_assignments"] if (getattr(a, "is_lab", False) or "lab" in (a.title or "").lower()) and not is_submitted(a)]

    return {
        "courses_count": len(active_courses),
        "assignments": {
            "total": len(data["all_assignments"]),
            "pending": len(pending_assignments),
            "overdue": len(overdue_assignments),
            "completed": len(completed_assignments),
            "missing_labs": len(missing_labs),
        },
        "upcoming_classes": len(data["upcoming_schedules"]),
        "upcoming_exams": len(data["upcoming_exams"]),
        "average_attendance": round(avg_attendance, 2),
        "academic_summary": academic_summary,
        "ai_agent_hub": {
            "active_crew_runs": active_crew_runs,
            "ready_for_review": ready_for_review_solutions[:5],
            "total_solved": len(ready_for_review_solutions),
            "active_count": len(active_crew_runs),
        },
    }


@router.get("/upcoming", response_model=dict)
def get_upcoming_items(
    days: int = Query(7, ge=1, le=30, description="Number of days to look ahead"),
    since: Optional[str] = Query(None, description="Filter data since this date (YYYY-MM-DD or ISO 8601)"),
    db: Session = Depends(get_db),
    user: dict = Depends(require_current_user),
):
    user_id = str((user or {}).get("id") or "dev_student_user")
    since_dt = _get_semester_start_dt(db, since, user_id)
    data = _get_user_dashboard_data(db, user_id, since_dt)

    now = datetime.now(timezone.utc)
    cutoff = now + timedelta(days=days)

    upcoming_assignments = [
        a for a in data["all_assignments"]
        if a.due_at and a.due_at <= cutoff
        and a.status not in [AssignmentStatus.SUBMITTED, AssignmentStatus.APPROVED]
    ]

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
            for s in data["upcoming_schedules"]
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
            for e in data["upcoming_exams"]
            if e.date and e.date <= cutoff
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

    # 1. Retrieve all attendance records for this user (or legacy fallback)
    all_records = (
        db.query(AttendanceRecord)
        .filter(AttendanceRecord.user_id.in_(user_owner_ids(user_id)))
        .order_by(AttendanceRecord.last_updated.desc().nullslast(), AttendanceRecord.id.desc())
        .all()
    )
    seen_subjects = set()
    records = []
    for r in all_records:
        sub_key = normalize_subject_name(r.subject or "")
        if sub_key and sub_key not in seen_subjects:
            seen_subjects.add(sub_key)
            records.append(r)

    # 2. Retrieve all courses owned by user, legacy, or referenced by attendance records
    courses = (
        db.query(Course)
        .filter(
            Course.user_id.in_(user_owner_ids(user_id))
        )
        .all()
    )
    course_by_id = {course.id: course for course in courses}
    owned_subjects = {
        normalize_subject_name(course.name)
        for course in courses
        if course.name
    }
    weekly_classes = {}
    for entry in db.query(TimetableEntry).filter(TimetableEntry.user_id.in_(user_owner_ids(user_id))).all():
        subject_key = normalize_subject_name(entry.subject)
        if subject_key and subject_key in owned_subjects:
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
    user_id = str((user or {}).get("id") or "dev_student_user")
    assignment_repo = AssignmentRepository(db)
    all_assignments = assignment_repo.get_all(user_id=user_id)
    
    since_dt = _get_semester_start_dt(db, since, user_id)
    if since_dt:
        all_assignments = [a for a in all_assignments if (a.due_at and a.due_at >= since_dt) or (a.created_at and a.created_at >= since_dt) or (a.updated_at and a.updated_at >= since_dt) or a.due_at is None]

    by_status = {}
    for status in AssignmentStatus:
        by_status[status.value] = len([a for a in all_assignments if a.status == status])

    return {
        "by_status": by_status,
        "total": len(all_assignments),
    }


@router.post("/active-crew-runs/{assignment_id}/dismiss", response_model=dict)
def dismiss_active_crew_run(
    assignment_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(require_current_user),
):
    """Dismiss or cancel a stuck or unwanted active crew solver run."""
    user_id = str((user or {}).get("id") or "dev_student_user")
    assignment = db.query(Assignment).filter(
        Assignment.id == assignment_id,
        Assignment.user_id.in_(user_owner_ids(user_id)),
    ).first()
    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")

    if assignment.status == AssignmentStatus.GENERATING:
        assignment.status = AssignmentStatus.DRAFT

    sol = db.query(AssignmentSolution).filter(AssignmentSolution.assignment_id == assignment_id).first()
    if sol and not sol.validated_content:
        sol.validation_errors = "Solver run dismissed by user."

    progress_key = f"assignment_crew_progress_{assignment_id}"
    db.query(Setting).filter(Setting.key == progress_key).delete()
    db.commit()

    return {"success": True, "message": "Assignment solver run dismissed successfully."}


@router.post("/clear-timetable", response_model=dict)
def clear_dashboard_timetable(
    db: Session = Depends(get_db),
    user: dict = Depends(require_current_user),
):
    """Clear all timetable entries and upcoming schedules from dashboard (CRUD Reset)"""
    from app.db.models import TimetableEntry, ClassSchedule
    from app.core.redis import invalidate_attendance_summary_cache
    user_id = str((user or {}).get("id") or "dev_student_user")

    from app.core.config import settings
    timetable_owner_filter = TimetableEntry.user_id.in_(user_owner_ids(user_id))
    schedule_owner_filter = ClassSchedule.user_id.in_(user_owner_ids(user_id))
    if user_id == "dev_student_user" and not settings.is_production:
        timetable_owner_filter = or_(timetable_owner_filter, TimetableEntry.user_id.is_(None))
        schedule_owner_filter = or_(schedule_owner_filter, ClassSchedule.user_id.is_(None))
    tt_count = db.query(TimetableEntry).filter(timetable_owner_filter).delete(synchronize_session=False)

    now_utc = datetime.now(timezone.utc)
    sch_count = db.query(ClassSchedule).filter(
        ClassSchedule.external_id.like("portal-sch:%"),
        schedule_owner_filter,
        ClassSchedule.start_time >= now_utc
    ).delete(synchronize_session=False)

    db.commit()
    invalidate_attendance_summary_cache()
    return {"success": True, "deleted_classes": tt_count, "deleted_schedules": sch_count}
