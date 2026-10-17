from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks, Body, Request, File, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime, timezone
import json
import html
import base64
import zipfile
from io import BytesIO
from googleapiclient.errors import HttpError

from app.db.database import get_db
from app.db.repositories import CourseRepository, ClassScheduleRepository, AssignmentTemplateRepository
from app.db.models import (
    Course, Assignment, AssignmentSolution, AssignmentStatus,
    Submission, SubmissionState, ClassSchedule, Announcement,
    Setting, AssignmentTemplate, BrowserAutomationJob
)
from app.core.logging import logger
from app.core.config import settings
from app.services.classroom_sync import get_classroom_service
from app.services.google_docs import get_google_docs_service
from app.auth.clerk_auth import get_current_user_optional
from app.services.browser_sessions import BrowserSessionClient
import time
import threading


def _assignment_generated_images(db: Session, assignment_id: int) -> list[dict]:
    """Return generated images for an assignment.
    Currently no persistent storage for generated images exists; returns empty list.
    """
    return []


router = APIRouter(prefix="/classroom", tags=["Classroom"])

# Per-user concurrency sync locks and student roster cache
_classroom_sync_locks: Dict[str, threading.Lock] = {}
_sync_lock_mutex = threading.Lock()
_students_cache: Dict[str, Tuple[float, list]] = {}  # key -> (timestamp, data)


def _classroom_user_id(clerk_user: Optional[dict]) -> str:
    user_id = str((clerk_user or {}).get("id") or "")
    if user_id:
        return user_id
    if settings.environment == "development":
        return "dev_student_user"
    raise HTTPException(status_code=401, detail="Sign in to access your Google Classroom data.")


def _get_owned_assignment(db: Session, assignment_id: int, user_id: str) -> Assignment:
    assignment = db.query(Assignment).filter(
        Assignment.id == assignment_id,
        Assignment.user_id == user_id,
    ).first()
    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")
    return assignment


def _get_user_lock(user_id: str) -> threading.Lock:
    with _sync_lock_mutex:
        if user_id not in _classroom_sync_locks:
            _classroom_sync_locks[user_id] = threading.Lock()
        return _classroom_sync_locks[user_id]


def _get_semester_start_dt(db: Session, override: Optional[str] = None, user_id: str = "default") -> datetime:
    val = override
    if not val:
        setting_key = (
            f"classroom:{user_id}:semester_start_date"
            if user_id != "default"
            else "semester_start_date"
        )
        setting = db.query(Setting).filter(Setting.key == setting_key).first()
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
    now = datetime.now(timezone.utc)
    year = now.year
    if now.month >= 8:
        return datetime(year, 9, 1, 0, 0, 0, tzinfo=timezone.utc)
    return datetime(year, 2, 1, 0, 0, 0, tzinfo=timezone.utc)


@router.get("/settings", response_model=dict)
def get_classroom_settings(
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional)
):
    """Get Classroom synchronization and semester settings (isolated per-user)"""
    user_id = _classroom_user_id(clerk_user)
    setting = db.query(Setting).filter(
        Setting.key == f"classroom:{user_id}:semester_start_date"
    ).first()
    if setting and setting.value:
        return {"semester_start_date": setting.value.strip().replace('"', '')}
    now = datetime.now(timezone.utc)
    year = now.year
    if now.month >= 8:
        default = datetime(year, 9, 1, 0, 0, 0, tzinfo=timezone.utc)
    else:
        default = datetime(year, 2, 1, 0, 0, 0, tzinfo=timezone.utc)
    return {"semester_start_date": default.isoformat()}


@router.post("/settings", response_model=dict)
@router.put("/settings", response_model=dict)
def save_classroom_settings(
    payload: Dict[str, Any] = Body(...),
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional)
):
    """Save semester start date setting per user"""
    user_id = _classroom_user_id(clerk_user)
    start_date = payload.get("semester_start_date")
    setting_key = f"classroom:{user_id}:semester_start_date"
    setting = db.query(Setting).filter(Setting.key == setting_key).first()
    if not setting:
        setting = Setting(key=setting_key, description=f"Semester start date filter for user {user_id}")
        db.add(setting)

    if start_date:
        setting.value = str(start_date).strip().replace('"', '')
    else:
        setting.value = None
    db.commit()
    return {
        "message": "Classroom settings updated",
        "semester_start_date": setting.value
    }


@router.get("/announcements", response_model=List[dict])
def get_classroom_announcements(
    course_id: Optional[int] = Query(None),
    search: Optional[str] = Query(None, max_length=200),
    since: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional),
):
    user_id = _classroom_user_id(clerk_user)
    # Only return announcements from active current-semester courses
    query = (
        db.query(Announcement)
        .join(Course, Announcement.course_id == Course.id)
        .filter(
            Announcement.source.like("Google Classroom%"),
            Course.user_id == user_id,
            Course.course_state.in_(["ACTIVE", "active", ""]) | Course.course_state.is_(None)
        )
    )
    if course_id is not None:
        query = query.filter(Announcement.course_id == course_id)
    if search:
        match = f"%{search}%"
        query = query.filter((Announcement.title.ilike(match)) | (Announcement.content.ilike(match)))

    since_dt = _get_semester_start_dt(db, since, user_id=user_id)
    if since_dt:
        query = query.filter(Announcement.published_at >= since_dt)

    posts = query.order_by(Announcement.published_at.desc().nullslast()).all()
    course_ids = {post.course_id for post in posts if post.course_id is not None}
    courses = {
        course.id: course.name
        for course in db.query(Course).filter(
            Course.id.in_(course_ids),
            Course.user_id == user_id,
        ).all()
    } if course_ids else {}
    return [
        {
            "id": post.id,
            "external_id": post.external_id,
            "course_id": post.course_id,
            "course_name": courses.get(post.course_id, "Google Classroom"),
            "title": post.title,
            "content": post.content,
            "url": post.url,
            "published_at": post.published_at,
        }
        for post in posts
    ]


@router.get("/courses", response_model=List[dict])
def get_courses(
    active_only: bool = Query(True),
    since: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional),
):
    user_id = _classroom_user_id(clerk_user)
    query = db.query(Course).filter(Course.user_id == user_id)
    if active_only:
        query = query.filter(Course.course_state.in_(["ACTIVE", "active", ""]) | Course.course_state.is_(None))
    since_dt = _get_semester_start_dt(db, since, user_id=user_id)
    if since_dt:
        query = query.filter((Course.created_at >= since_dt) | (Course.updated_at >= since_dt) | Course.created_at.is_(None))
    courses = query.order_by(Course.name.asc()).all()
    return [
        {
            "id": c.id,
            "external_id": c.external_id,
            "name": c.name,
            "section": c.section,
            "description": c.description,
            "room": c.room,
            "teacher_name": c.teacher_name,
            "course_state": c.course_state,
            "alternate_link": c.alternate_link,
            "created_at": c.created_at,
            "updated_at": c.updated_at,
        }
        for c in courses
    ]


@router.get("/courses/{course_id}", response_model=dict)
def get_course(
    course_id: int,
    since: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional),
):
    repo = CourseRepository(db)
    user_id = _classroom_user_id(clerk_user)
    course = db.query(Course).filter(Course.id == course_id, Course.user_id == user_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    since_dt = _get_semester_start_dt(db, since, user_id=user_id)
    if since_dt:
        if not (course.created_at and course.created_at >= since_dt) and \
           not (course.updated_at and course.updated_at >= since_dt) and \
           course.created_at is not None:
            raise HTTPException(status_code=404, detail="Course not found")
    
    return {
        "id": course.id,
        "external_id": course.external_id,
        "name": course.name,
        "section": course.section,
        "description": course.description,
        "room": course.room,
        "teacher_name": course.teacher_name,
        "course_state": course.course_state,
        "alternate_link": course.alternate_link,
        "created_at": course.created_at,
        "updated_at": course.updated_at,
    }


@router.get("/schedules", response_model=List[dict])
def get_schedules(
    days: int = Query(7, ge=1, le=30),
    since: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    repo = ClassScheduleRepository(db)
    schedules = repo.get_upcoming(days)
    
    since_dt = _get_semester_start_dt(db, since)
    if since_dt:
        schedules = [s for s in schedules if s.date and s.date >= since_dt.date()]
    
    return [
        {
            "id": s.id,
            "external_id": s.external_id,
            "course_id": s.course_id,
            "subject": s.subject,
            "date": s.date,
            "start_time": s.start_time,
            "end_time": s.end_time,
            "teacher": s.teacher,
            "room": s.room,
            "status": s.status,
            "created_at": s.created_at,
            "updated_at": s.updated_at,
        }
        for s in schedules
    ]


@router.get("/schedules/today", response_model=List[dict])
def get_today_schedules(
    since: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    repo = ClassScheduleRepository(db)
    schedules = repo.get_today()
    
    since_dt = _get_semester_start_dt(db, since)
    if since_dt:
        schedules = [s for s in schedules if s.date and s.date >= since_dt.date()]
    
    return [
        {
            "id": s.id,
            "external_id": s.external_id,
            "course_id": s.course_id,
            "subject": s.subject,
            "date": s.date,
            "start_time": s.start_time,
            "end_time": s.end_time,
            "teacher": s.teacher,
            "room": s.room,
            "status": s.status,
        }
        for s in schedules
    ]


@router.get("/schedules/{schedule_id}", response_model=dict)
def get_schedule(schedule_id: int, db: Session = Depends(get_db)):
    schedule = db.query(ClassSchedule).filter(ClassSchedule.id == schedule_id).first()
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return {
        "id": schedule.id,
        "external_id": schedule.external_id,
        "course_id": schedule.course_id,
        "subject": schedule.subject,
        "date": schedule.date,
        "start_time": schedule.start_time,
        "end_time": schedule.end_time,
        "teacher": schedule.teacher,
        "room": schedule.room,
        "status": schedule.status,
        "created_at": schedule.created_at,
        "updated_at": schedule.updated_at,
    }


# === Google Classroom Sync Endpoints ===

@router.post("/sync", response_model=dict)
def sync_classroom(
    background_tasks: BackgroundTasks,
    payload: Optional[Dict[str, Any]] = Body(None),
    semester_start_date: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional)
):
    """Trigger full Google Classroom sync from semester start date onwards with concurrency control"""
    user_id = _classroom_user_id(clerk_user)
    lock = _get_user_lock(user_id)

    if not lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="A synchronization is already running for your account.")

    service = get_classroom_service(db, user_id=user_id)
    if not service:
        lock.release()
        raise HTTPException(status_code=503, detail="Google Classroom not configured. Complete OAuth first.")

    start_date = None
    if payload and "semester_start_date" in payload:
        start_date = payload["semester_start_date"]
    elif semester_start_date:
        start_date = semester_start_date

    semester_key = f"classroom:{user_id}:semester_start_date"
    if start_date:
        setting = db.query(Setting).filter(Setting.key == semester_key).first()
        if not setting:
            setting = Setting(key=semester_key, description="Semester start date filter for syncing")
            db.add(setting)
        setting.value = str(start_date).strip().replace('"', '')
        db.commit()

    status_key = f"classroom:{user_id}:sync_status"
    run_status = db.query(Setting).filter(Setting.key == status_key).first()
    if not run_status:
        run_status = Setting(key=status_key, description="Most recent Google Classroom sync run")
        db.add(run_status)
    run_status.value = json.dumps({"status": "running", "started_at": datetime.now(timezone.utc).isoformat()})
    db.commit()

    def run_sync(uid: str, s_key: str):
        from app.db.database import SessionLocal
        sync_db = SessionLocal()
        u_lock = _get_user_lock(uid)
        try:
            svc = get_classroom_service(sync_db, user_id=uid)
            if svc:
                result = svc.sync_all()
                logger.info(f"Classroom sync result for {uid}: {result}")
                errors = result.get("errors") or []
                status = "failed" if errors else "completed"
                sync_error = "; ".join(errors) if errors else None
                run = sync_db.query(Setting).filter(Setting.key == s_key).first()
                if run:
                    previous = json.loads(run.value or "{}")
                    run.value = json.dumps({
                        **previous,
                        "status": status,
                        "error": sync_error,
                        "finished_at": datetime.now(timezone.utc).isoformat(),
                        "result": result
                    })
                    sync_db.commit()
            else:
                raise RuntimeError("Google Classroom credentials could not be loaded.")
        except Exception as error:
            run = sync_db.query(Setting).filter(Setting.key == s_key).first()
            if run:
                previous = json.loads(run.value or "{}")
                run.value = json.dumps({**previous, "status": "failed", "error": str(error), "finished_at": datetime.now(timezone.utc).isoformat()})
                sync_db.commit()
            logger.exception("Google Classroom sync failed")
        finally:
            sync_db.close()
            if u_lock.locked():
                u_lock.release()

    background_tasks.add_task(run_sync, user_id, status_key)
    return {"message": "Classroom sync started in background", "status": "started"}


@router.post("/sync/course/{course_external_id}", response_model=dict)
def sync_single_course(
    course_external_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional),
):
    """Sync a specific course by external ID"""
    user_id = _classroom_user_id(clerk_user)
    service = get_classroom_service(db, user_id=user_id)
    if not service:
        raise HTTPException(status_code=503, detail="Google Classroom not configured")

    course = db.query(Course).filter(
        Course.external_id == course_external_id,
        Course.user_id == user_id,
    ).first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found in local DB")

    def run_course_sync():
        from app.db.database import SessionLocal
        sync_db = SessionLocal()
        try:
            svc = get_classroom_service(sync_db, user_id=user_id)
            if svc:
                api_course = svc.service.courses().get(id=course_external_id).execute()
                svc._sync_course(api_course)
                svc._sync_coursework(course_external_id)
                logger.info(f"Synced course {course_external_id}")
        finally:
            sync_db.close()

    background_tasks.add_task(run_course_sync)
    return {"message": f"Course {course_external_id} sync started", "status": "started"}


@router.get("/sync/status", response_model=dict)
def sync_status(
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional)
):
    """Get sync status and stats isolated per user"""
    from sqlalchemy import func
    from app.db.models import Assignment, GoogleCredential
    user_id = _classroom_user_id(clerk_user)

    course_count = db.query(func.count(Course.id)).filter(Course.user_id == user_id).scalar() or 0
    assignment_count = db.query(func.count(Assignment.id)).filter(Assignment.user_id == user_id).scalar() or 0

    cred = db.query(GoogleCredential).filter(GoogleCredential.user_id == user_id).first()
    has_creds = cred is not None

    status_key = f"classroom:{user_id}:sync_status"
    run = db.query(Setting).filter(Setting.key == status_key).first()
    sync_run = json.loads(run.value) if run and run.value else None

    sem_key = f"classroom:{user_id}:semester_start_date"
    setting = db.query(Setting).filter(Setting.key == sem_key).first()
    semester_start = setting.value.strip().replace('"', '') if setting and setting.value else None

    return {
        "courses_in_db": course_count,
        "assignments_in_db": assignment_count,
        "google_connected": has_creds,
        "sync_run": sync_run,
        "semester_start_date": semester_start,
        "last_sync": sync_run.get("finished_at") if sync_run else None,
    }


@router.get("/courses/{course_id}/assignments", response_model=List[dict])
def get_course_assignments(
    course_id: int,
    since: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional)
):
    """Get assignments for a specific course (from local DB)"""
    from app.db.models import Assignment
    user_id = _classroom_user_id(clerk_user)
    owned_course = db.query(Course.id).filter(
        Course.id == course_id,
        Course.user_id == user_id,
    ).first()
    if not owned_course:
        raise HTTPException(status_code=404, detail="Course not found")
    query = db.query(Assignment).filter(
        Assignment.course_id == course_id,
        Assignment.user_id == user_id,
    )
    
    since_dt = _get_semester_start_dt(db, since, user_id=user_id)
    if since_dt:
        query = query.filter(
            (Assignment.due_at >= since_dt) |
            (Assignment.due_date >= since_dt) |
            ((Assignment.due_at.is_(None)) & (
                (Assignment.created_at >= since_dt) | (Assignment.updated_at >= since_dt)
            ))
        )
    
    assignments = query.order_by(Assignment.due_at.asc().nullslast()).all()
    return [
        {
            "id": a.id,
            "external_id": a.external_id,
            "title": a.title,
            "description": a.description,
            "due_at": a.due_at,
            "due_date": a.due_date,
            "url": a.url,
            "state": a.state.value if a.state else None,
            "status": a.status.value if a.status else None,
        }
        for a in assignments
    ]


@router.get("/courses/{course_id}/students", response_model=List[dict])
def get_course_students(
    course_id: int,
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional),
):
    """Get students for a course from Google Classroom API with in-memory TTL caching"""
    user_id = _classroom_user_id(clerk_user)
    cache_key = f"roster_{user_id}_{course_id}"
    cached = _students_cache.get(cache_key)
    now = time.time()
    if cached and (now - cached[0] < 300):  # 5 minutes TTL
        return cached[1]

    service = get_classroom_service(db, user_id=user_id)
    if not service:
        raise HTTPException(status_code=503, detail="Google Classroom not configured")

    course = db.query(Course).filter(Course.id == course_id, Course.user_id == user_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    try:
        students = service.get_course_students(course.external_id)
    except HttpError as error:
        if error.resp.status in (401, 403):
            raise HTTPException(
                status_code=403,
                detail="Google Classroom needs roster access. Reconnect your Google account and approve the updated permissions.",
            ) from error
        raise HTTPException(status_code=502, detail="Google Classroom could not return this roster.") from error

    result = [
        {
            "id": s.get("userId"),
            "name": s.get("profile", {}).get("name", {}).get("fullName", "Student"),
            "email": s.get("profile", {}).get("emailAddress"),
            "photo_url": s.get("profile", {}).get("photoUrl"),
            "user_id": s.get("userId"),
            "profile": s.get("profile", {}),
        }
        for s in students
    ]
    _students_cache[cache_key] = (now, result)
    return result


# ===== Assignment Templates =====

@router.get("/templates", response_model=List[dict])
def get_assignment_templates(
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional),
):
    """List all assignment templates"""
    repo = AssignmentTemplateRepository(db, user_id=_classroom_user_id(clerk_user))
    templates = repo.get_all()
    return [
        {
            "id": t.id,
            "name": t.name,
            "description": t.description,
            "google_doc_id": t.google_doc_id,
            "google_drive_file_id": t.google_drive_file_id,
            "mime_type": t.mime_type,
            "is_default": t.is_default,
            "created_at": t.created_at,
            "updated_at": t.updated_at,
        }
        for t in templates
    ]


@router.post("/templates/starter", response_model=dict)
def create_starter_assignment_template(
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional),
):
    """Create a real editable report template in the connected user's Google Drive."""
    user_id = _classroom_user_id(clerk_user)
    repo = AssignmentTemplateRepository(db, user_id=user_id)
    current = repo.get_default()
    if current:
        return {"id": current.id, "name": current.name, "description": current.description,
                "google_doc_id": current.google_doc_id, "google_drive_file_id": current.google_drive_file_id,
                "mime_type": current.mime_type, "is_default": True, "already_exists": True}
    docs_service = get_google_docs_service(db, user_id=user_id)
    if not docs_service:
        raise HTTPException(status_code=503, detail="Connect Google Drive before creating a report template.")
    content = (
        "AIR UNIVERSITY, ISLAMABAD\n"
        "FACULTY OF COMPUTING & ARTIFICIAL INTELLIGENCE\n"
        "================================================================================\n"
        "ACADEMIC LAB REPORT / ASSIGNMENT SUBMISSION\n"
        "================================================================================\n\n"
        "COURSE:            {{SUBJECT_NAME}}\n"
        "COURSE CODE:       {{COURSE_CODE}}\n"
        "ASSIGNMENT / LAB:  {{ASSIGNMENT_TITLE}}\n"
        "INSTRUCTOR:        {{INSTRUCTOR_NAME}}\n"
        "SUBMISSION DATE:   {{SUBMISSION_DATE}}\n"
        "DUE DATE:          {{DUE_DATE}}\n\n"
        "--------------------------------------------------------------------------------\n"
        "STUDENT INFORMATION\n"
        "--------------------------------------------------------------------------------\n"
        "STUDENT NAME:      {{STUDENT_NAME}}\n"
        "ROLL NUMBER / ID:  {{ROLL_NO}}\n"
        "PROGRAM / SECTION: {{CLASS}}\n"
        "STUDENT EMAIL:     {{EMAIL}}\n"
        "INSTITUTION:       {{UNIVERSITY_NAME}}\n"
        "================================================================================\n\n"
        "LAB WORK & SOLUTION\n\n"
        "{{SOLUTION_CONTENT}}\n"
    )
    doc = docs_service.create_document("Uniflow Academic Report Template", content)
    if not doc or not doc.get("documentId"):
        raise HTTPException(status_code=502, detail="Google Docs could not create the report template.")
    template = repo.create({
        "name": "Uniflow Academic Report Template",
        "description": "Editable cover page with assignment, student, course, and solution placeholders.",
        "google_doc_id": doc["documentId"],
        "google_drive_file_id": doc["documentId"],
        "mime_type": "application/vnd.google-apps.document",
        "is_default": True,
    })
    return {"id": template.id, "name": template.name, "description": template.description,
            "google_doc_id": template.google_doc_id, "google_drive_file_id": template.google_drive_file_id,
            "mime_type": template.mime_type, "is_default": True}


@router.post("/templates", response_model=dict)
def create_assignment_template(
    name: str = Body(...),
    google_doc_id: str = Body(...),
    description: Optional[str] = Body(None),
    google_drive_file_id: Optional[str] = Body(None),
    mime_type: Optional[str] = Body(None),
    is_default: bool = Body(False),
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional),
):
    """Create a new assignment template from a Google Doc"""
    user_id = _classroom_user_id(clerk_user)
    repo = AssignmentTemplateRepository(db, user_id=user_id)
    docs_service = get_google_docs_service(db, user_id=user_id)
    
    doc_mime = mime_type or "application/vnd.google-apps.document"
    if docs_service:
        try:
            doc = docs_service.get_document(google_doc_id)
            if doc and "mimeType" in doc:
                doc_mime = doc["mimeType"]
        except Exception as e:
            logger.warning(f"Could not fetch doc metadata from Google API: {e}")
    
    if is_default:
        # Unset any existing default
        existing_default = repo.get_default()
        if existing_default:
            existing_default.is_default = False
    
    template = repo.create({
        "name": name,
        "description": description,
        "google_doc_id": google_doc_id,
        "google_drive_file_id": google_drive_file_id or google_doc_id,
        "mime_type": doc_mime,
        "is_default": is_default,
    })
    return {
        "id": template.id,
        "name": template.name,
        "description": template.description,
        "google_doc_id": template.google_doc_id,
        "google_drive_file_id": template.google_drive_file_id,
        "mime_type": template.mime_type,
        "is_default": template.is_default,
    }


@router.put("/templates/{template_id}/default", response_model=dict)
def set_default_template(
    template_id: int,
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional),
):
    """Set a template as default"""
    repo = AssignmentTemplateRepository(db, user_id=_classroom_user_id(clerk_user))
    template = repo.set_default(template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    return {
        "id": template.id,
        "name": template.name,
        "is_default": template.is_default,
    }


@router.delete("/templates/{template_id}", response_model=dict)
def delete_assignment_template(
    template_id: int,
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional),
):
    """Delete an assignment template"""
    repo = AssignmentTemplateRepository(db, user_id=_classroom_user_id(clerk_user))
    template = repo.delete(template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    return {"deleted": True, "id": template_id}


@router.get("/templates/drive-files", response_model=List[dict])
def list_drive_docs_for_templates(
    query: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional),
):
    """List Google Docs from Drive for template selection"""
    docs_service = get_google_docs_service(db, user_id=_classroom_user_id(clerk_user))
    if not docs_service:
        raise HTTPException(status_code=503, detail="Google Docs not configured")
    
    q = "mimeType='application/vnd.google-apps.document' and trashed=false"
    if query:
        q += f" and name contains '{query}'"
    
    files = docs_service.list_files(query=q, page_size=50)
    return [
        {
            "id": f["id"],
            "name": f["name"],
            "mimeType": f["mimeType"],
            "createdTime": f.get("createdTime"),
            "modifiedTime": f.get("modifiedTime"),
            "webViewLink": f.get("webViewLink"),
        }
        for f in files
    ]


class TurnInPayload(BaseModel):
    template_id: Optional[int] = None
    drive_file_ids: Optional[List[str]] = None
    file_names: Optional[List[str]] = Field(None, alias="fileNames")

    class Config:
        populate_by_name = True


@router.post("/assignments/{assignment_id}/turn-in", response_model=dict)
async def turn_in_assignment(
    assignment_id: int,
    request: Request,
    template_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional),
):
    """Student turn-in: copy template (or create blank doc), attach files, submit to Classroom"""
    from app.db.models import Assignment, Submission, SubmissionState
    from googleapiclient.errors import HttpError

    uploaded_files = []
    payload = None
    if "multipart/form-data" in request.headers.get("content-type", ""):
        form = await request.form()
        raw_template_id = form.get("template_id") or form.get("templateId")
        if raw_template_id:
            try:
                template_id = int(raw_template_id)
            except (TypeError, ValueError) as error:
                raise HTTPException(status_code=422, detail="Invalid template_id") from error
        uploaded_files = form.getlist("files")
        if any(not hasattr(file, "read") or not getattr(file, "filename", None) for file in uploaded_files):
            raise HTTPException(status_code=422, detail="Each requested file must include a filename and file content")
    else:
        body = await request.json() if request.headers.get("content-length", "0") != "0" else {}
        payload = TurnInPayload.model_validate(body) if body else None
        if payload and payload.file_names and not payload.drive_file_ids:
            raise HTTPException(
                status_code=422,
                detail="File names are not uploadable files. Upload the files or provide Google Drive file IDs.",
            )

    user_id = _classroom_user_id(clerk_user)
    service = get_classroom_service(db, user_id=user_id)
    if not service:
        raise HTTPException(status_code=503, detail="Google Classroom not configured")
    
    docs_service = get_google_docs_service(db, user_id=user_id)
    if not docs_service:
        raise HTTPException(status_code=503, detail="Google Docs not configured")
    
    assignment = _get_owned_assignment(db, assignment_id, user_id)
    
    course = db.query(Course).filter(
        Course.id == assignment.course_id,
        Course.user_id == user_id,
    ).first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    
    # Determine template from either JSON body or query parameter
    chosen_template_id = (payload.template_id if payload and payload.template_id is not None else None) or template_id
    drive_file_ids = list(payload.drive_file_ids or []) if payload else []

    # Upload requested files to the connected user's Drive before attaching them.
    # A failed upload aborts the request; filenames alone must never be reported as submitted.
    drive_file_ids.extend(await _upload_submission_files(docs_service, uploaded_files))

    if chosen_template_id:
        repo = AssignmentTemplateRepository(db, user_id=user_id)
        template = repo.get_by_id(chosen_template_id)
    else:
        repo = AssignmentTemplateRepository(db, user_id=user_id)
        template = repo.get_default()
    
    student_doc_id = None
    
    if template:
        # Copy template to student's Drive
        try:
            copied = docs_service.drive_service.files().copy(
                fileId=template.google_drive_file_id or template.google_doc_id,
                body={"name": f"{assignment.title} - Submission"}
            ).execute()
            student_doc_id = copied.get("id")
        except HttpError as e:
            logger.error(f"Failed to copy template: {e}")
            # Fallback: create blank doc
            doc = docs_service.create_document(f"{assignment.title} - Submission")
            student_doc_id = doc.get("documentId") if doc else None
    else:
        # Create blank doc
        doc = docs_service.create_document(f"{assignment.title} - Submission")
        student_doc_id = doc.get("documentId") if doc else None
    
    if not student_doc_id:
        raise HTTPException(status_code=500, detail="Failed to create submission document")

    # Fill report cover placeholders in the copied student submission document.
    if template:
        profile_row = db.query(Setting).filter(Setting.key == f"clerk_user_{user_id}").first()
        profile = {}
        if profile_row and profile_row.value:
            try:
                profile = json.loads(profile_row.value)
            except (TypeError, json.JSONDecodeError):
                profile = {}
        student_name = " ".join(part for part in (profile.get("first_name"), profile.get("last_name")) if part).strip()
        today = datetime.now().strftime("%B %d, %Y")
        fields = {
            "{{STUDENT_NAME}}": student_name,
            "{{EMAIL}}": profile.get("email", ""),
            "{{STUDENT_ID}}": "", "{{ROLL_NO}}": "", "{{UNIVERSITY_NAME}}": "",
            "{{CLASS}}": course.section or "", "{{SECTION}}": course.section or "",
            "{{SUBJECT_NAME}}": course.name or "", "{{COURSE_NAME}}": course.name or "",
            "{{COURSE_CODE}}": "", "{{ASSIGNMENT_TITLE}}": assignment.title or "",
            "{{INSTRUCTOR_NAME}}": course.teacher_name or "",
            "{{SUBMISSION_DATE}}": today,
            "{{DUE_DATE}}": assignment.due_at.isoformat() if assignment.due_at else "",
            "{{SEMESTER}}": "", "{{SOLUTION_CONTENT}}": "",
        }
        for placeholder, value in fields.items():
            docs_service.replace_text(student_doc_id, placeholder, str(value or ""))
    
    # Attach additional files if provided
    if drive_file_ids:
        for file_id in drive_file_ids:
            try:
                docs_service.share_file(file_id, "me", "writer")
            except HttpError:
                pass
    
    # Attach the created cover document and all requested files to the student's
    # actual Classroom submission, then turn it in only after attachment succeeds.
    submission_id = _attach_submission_files(
        service.service,
        course.external_id,
        assignment.external_id,
        [student_doc_id, *drive_file_ids],
    )
    try:
        service.service.courses().courseWork().studentSubmissions().turnIn(
            courseId=course.external_id,
            courseWorkId=assignment.external_id,
            id=submission_id,
        ).execute()
    except Exception as error:
        err_str = str(error)
        logger.error(f"Failed to turn in Classroom submission {submission_id}: {error}")
        if "already been submitted" in err_str.lower() or "FAILED_PRECONDITION" in err_str:
            raise HTTPException(
                status_code=409,
                detail="This assignment has already been turned in on Google Classroom. Please unsubmit it first if you wish to turn in a revised version.",
            ) from error
        raise HTTPException(
            status_code=502,
            detail=f"Files were attached, but Google Classroom could not turn in the submission: {err_str}",
        ) from error
    
    # Update local submission record
    existing = db.query(Submission).filter(Submission.assignment_id == assignment_id).first()
    if not existing:
        existing = Submission(assignment_id=assignment_id)
        db.add(existing)
    
    existing.google_doc_id = student_doc_id
    existing.google_drive_file_id = student_doc_id
    existing.classroom_attachment_id = submission_id
    existing.submitted_at = datetime.now(timezone.utc)
    existing.submission_state = SubmissionState.TURNED_IN
    existing.approved_by_user = True
    existing.approved_at = datetime.now(timezone.utc)
    
    db.commit()
    db.refresh(existing)
    
    return {
        "success": True,
        "submission_id": existing.id,
        "google_doc_id": student_doc_id,
        "classroom_submission_id": submission_id,
        "message": "Assignment turned in successfully"
    }


@router.post("/assignments/{assignment_id}/unsubmit", response_model=dict)
def unsubmit_assignment(
    assignment_id: int,
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional),
):
    """Unsubmit an assignment on Google Classroom to allow modifications and revisions."""
    from app.db.models import Assignment, Submission, SubmissionState, Course

    user_id = _classroom_user_id(clerk_user)
    service = get_classroom_service(db, user_id=user_id)
    if not service:
        raise HTTPException(status_code=503, detail="Google Classroom not configured")

    assignment = _get_owned_assignment(db, assignment_id, user_id)

    course = db.query(Course).filter(
        Course.id == assignment.course_id,
        Course.user_id == user_id,
    ).first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    try:
        res = service.service.courses().courseWork().studentSubmissions().list(
            courseId=course.external_id,
            courseWorkId=assignment.external_id,
            userId="me"
        ).execute()
        submissions = res.get("studentSubmissions", [])
        if not submissions:
            raise HTTPException(status_code=404, detail="No submission found on Google Classroom")

        submission_id = submissions[0]["id"]
        service.service.courses().courseWork().studentSubmissions().reclaim(
            courseId=course.external_id,
            courseWorkId=assignment.external_id,
            id=submission_id
        ).execute()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to unsubmit assignment {assignment_id}: {e}")
        raise HTTPException(status_code=502, detail=f"Could not unsubmit on Classroom: {str(e)}")

    assignment.submission_state = SubmissionState.CREATED
    sub = db.query(Submission).filter(Submission.assignment_id == assignment_id).first()
    if sub:
        sub.submission_state = SubmissionState.CREATED
    db.commit()

    return {
        "success": True,
        "assignment_id": assignment_id,
        "message": "Assignment successfully unsubmitted on Google Classroom. You can now edit and re-turn in."
    }


async def _upload_submission_files(docs_service, uploaded_files) -> List[str]:
    """Upload every requested file and return its Drive ID, failing closed on any error."""
    drive_file_ids = []
    for uploaded_file in uploaded_files:
        try:
            content = await uploaded_file.read()
            uploaded = docs_service.upload_file(
                name=uploaded_file.filename,
                content=content,
                mime_type=uploaded_file.content_type or "application/octet-stream",
            )
        except Exception as error:
            logger.error(f"Failed to upload requested file {uploaded_file.filename}: {error}")
            raise HTTPException(
                status_code=502,
                detail=f"Failed to upload {uploaded_file.filename} to Google Drive",
            ) from error
        if not uploaded or not uploaded.get("id"):
            raise HTTPException(
                status_code=502,
                detail=f"Google Drive did not return a file ID for {uploaded_file.filename}",
            )
        drive_file_ids.append(uploaded["id"])
    return drive_file_ids


def _attach_submission_files(classroom_service, course_id: str, coursework_id: str, file_ids: List[str]) -> str:
    """Attach Drive file IDs to the signed-in student's Classroom submission."""
    submissions_api = classroom_service.courses().courseWork().studentSubmissions()
    try:
        result = submissions_api.list(
            courseId=course_id,
            courseWorkId=coursework_id,
            userId="me",
            pageSize=100,
        ).execute()
        student_submissions = result.get("studentSubmissions", [])
        if not student_submissions or not student_submissions[0].get("id"):
            raise HTTPException(status_code=409, detail="No Google Classroom submission is available for this assignment")

        submission_id = student_submissions[0]["id"]
        submissions_api.modifyAttachments(
            courseId=course_id,
            courseWorkId=coursework_id,
            id=submission_id,
            body={"addAttachments": [{"driveFile": {"id": file_id}} for file_id in file_ids]},
        ).execute()
        return submission_id
    except HTTPException:
        raise
    except Exception as error:
        logger.error(f"Failed to attach Drive files to Google Classroom: {error}")
        raise HTTPException(status_code=502, detail="Failed to attach files to Google Classroom") from error


@router.post("/assignments/{assignment_id}/materials/upload", response_model=dict)
async def upload_assignment_material(
    assignment_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional),
):
    """Upload a local assignment problem sheet / PDF / document directly into assignment materials."""
    from app.db.models import Assignment, AssignmentMaterial
    from pathlib import Path
    import re

    user_id = _classroom_user_id(clerk_user)
    _get_owned_assignment(db, assignment_id, user_id)

    materials_dir = Path(__file__).resolve().parent.parent.parent / "tmp" / "materials"
    materials_dir.mkdir(parents=True, exist_ok=True)

    safe_filename = re.sub(r'[^a-zA-Z0-9_\-\.]', '_', file.filename or "uploaded_material.pdf")
    dest_path = materials_dir / f"assignment_{assignment_id}_{safe_filename}"

    content = await file.read()
    dest_path.write_bytes(content)

    extracted_text = ""
    if safe_filename.lower().endswith(".txt"):
        try:
            extracted_text = content.decode("utf-8", errors="ignore")
        except Exception:
            pass
    elif safe_filename.lower().endswith(".pdf"):
        try:
            import io
            import pypdf
            reader = pypdf.PdfReader(io.BytesIO(content))
            extracted_text = "\n".join(page.extract_text() or "" for page in reader.pages)
        except Exception:
            pass

    mat = AssignmentMaterial(
        assignment_id=assignment_id,
        material_type="local_upload",
        title=file.filename,
        content=extracted_text if extracted_text else None,
        mime_type=file.content_type,
    )
    db.add(mat)
    db.commit()

    return {
        "status": "uploaded",
        "material_id": mat.id,
        "filename": file.filename,
        "bytes": len(content),
        "local_path": str(dest_path.resolve())
    }


# ===== AI Solution Generation & Agentic Flow =====

class GenerateSolutionRequest(BaseModel):
    provider: Optional[str] = "crewai"
    model: Optional[str] = None
    create_google_doc: Optional[bool] = True


@router.post("/assignments/{assignment_id}/solution/generate", response_model=dict)
def generate_assignment_solution(
    assignment_id: int,
    payload: Optional[GenerateSolutionRequest] = None,
    background_tasks: BackgroundTasks = None,
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional),
):
    """Trigger the multi-agent assignment solver flow (async with background tasks)."""
    from app.db.models import AssignmentSolution, AssignmentStatus

    req = payload or GenerateSolutionRequest()
    provider = req.provider or "groq"
    model = req.model or "openai/gpt-oss-120b"
    create_google_doc = req.create_google_doc if req.create_google_doc is not None else True

    user_id = _classroom_user_id(clerk_user)
    assignment = db.query(Assignment).filter(
        Assignment.id == assignment_id,
        Assignment.user_id == user_id,
    ).first()
    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")
    # Get or create solution record
    solution = db.query(AssignmentSolution).filter(AssignmentSolution.assignment_id == assignment_id).first()
    if assignment.status == AssignmentStatus.GENERATING:
        started = solution.generated_at if solution else None
        if started and started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        is_stale = not started or (datetime.now(timezone.utc) - started).total_seconds() > 20 * 60
        if not is_stale:
            raise HTTPException(status_code=409, detail="A solution is already being generated for this assignment.")
    if not solution:
        solution = AssignmentSolution(assignment_id=assignment_id)
        db.add(solution)

    solution.ai_provider = provider
    solution.retry_count = 0
    solution.validation_errors = None
    solution.draft_content = None
    solution.validated_content = None
    solution.validated_at = None
    solution.generated_at = datetime.now(timezone.utc)
    assignment.status = AssignmentStatus.GENERATING
    db.commit()

    def run_generation():
        from app.db.database import SessionLocal
        sync_db = SessionLocal()
        try:
            if provider == "claude_browser":
                from app.services.claude_browser_solver import solve_assignment_via_claude_browser
                result = solve_assignment_via_claude_browser(
                    db=sync_db,
                    assignment_id=assignment_id,
                    user_id=user_id,
                    force=True,
                )
                logger.info(f"Claude Browser solution generated for assignment {assignment_id}: status={result.get('status')}")
                if result.get("status") == "already_running":
                    logger.info(f"Claude Browser solve for assignment {assignment_id} skipped because another solve is already running.")
                    from app.db.models import Assignment, AssignmentStatus
                    asg = sync_db.query(Assignment).filter(
                        Assignment.id == assignment_id,
                        Assignment.user_id == user_id,
                    ).first()
                    if asg and asg.status == AssignmentStatus.GENERATING:
                        asg.status = AssignmentStatus.DRAFT
                        sync_db.commit()
                elif result.get("status") == "draft":
                    from app.db.models import Assignment, AssignmentSolution, AssignmentStatus
                    sol = sync_db.query(AssignmentSolution).filter(AssignmentSolution.assignment_id == assignment_id).first()
                    asg = sync_db.query(Assignment).filter(
                        Assignment.id == assignment_id,
                        Assignment.user_id == user_id,
                    ).first()
                    if sol:
                        sol.validation_errors = result.get("error")
                    if asg:
                        asg.status = AssignmentStatus.DRAFT
                    sync_db.commit()
                elif result.get("status") in ("needs_login", "error"):
                    from app.db.models import Assignment, AssignmentSolution, AssignmentStatus
                    sol = sync_db.query(AssignmentSolution).filter(AssignmentSolution.assignment_id == assignment_id).first()
                    asg = sync_db.query(Assignment).filter(
                        Assignment.id == assignment_id,
                        Assignment.user_id == user_id,
                    ).first()
                    if sol:
                        sol.validation_errors = result.get("error")
                    if asg:
                        asg.status = AssignmentStatus.FAILED
                    sync_db.commit()
            else:
                from app.services.ai_solution import generate_agentic_solution
                result = generate_agentic_solution(
                    db=sync_db,
                    assignment_id=assignment_id,
                    provider=provider,
                    model=model,
                    create_google_doc=create_google_doc,
                    user_id=user_id,
                )
                logger.info(f"Multi-Agent solution generated for assignment {assignment_id}: status={result.get('status')}")
        except Exception as e:
            logger.error(f"Multi-Agent solution generation failed for assignment {assignment_id}: {e}")
            try:
                from app.db.models import Assignment, AssignmentSolution, AssignmentStatus
                failed_assignment = sync_db.query(Assignment).filter(
                    Assignment.id == assignment_id,
                    Assignment.user_id == user_id,
                ).first()
                failed_solution = sync_db.query(AssignmentSolution).filter(AssignmentSolution.assignment_id == assignment_id).first()
                if failed_solution:
                    failed_solution.validation_errors = str(e)
                if failed_assignment:
                    failed_assignment.status = AssignmentStatus.FAILED
                sync_db.commit()
            except Exception as commit_error:
                logger.error(f"Could not persist solution failure status for {assignment_id}: {commit_error}")
        finally:
            sync_db.close()

    if background_tasks:
        background_tasks.add_task(run_generation)
    else:
        run_generation()

    return {
        "status": "started",
        "assignment_id": assignment_id,
        "provider": provider,
        "message": f"Autonomous assignment solver workflow started ({provider})."
    }


@router.post("/claude-browser/open", response_model=dict)
def open_claude_browser(clerk_user: Optional[dict] = Depends(get_current_user_optional)):
    """Start this user's private hosted Claude browser and return a short-lived viewer link."""
    return BrowserSessionClient().open(_classroom_user_id(clerk_user))


class ClaudeCookieSyncRequest(BaseModel):
    session_key: str
    user_agent: Optional[str] = None


@router.post("/claude-browser/sync-session", response_model=dict)
def sync_claude_session(
    payload: ClaudeCookieSyncRequest,
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional),
):
    """Sync the student's existing Claude sessionKey cookie from the extension or settings."""
    user_id = _classroom_user_id(clerk_user)
    raw_key = payload.session_key.strip()
    # Strip optional surrounding quotes or cookie name prefixes if user pasted full cookie
    if "sessionKey=" in raw_key:
        raw_key = raw_key.split("sessionKey=")[-1].split(";")[0].strip()
    raw_key = raw_key.strip('"\'')
    if len(raw_key) < 20:
        raise HTTPException(
            status_code=400,
            detail="Invalid Claude session key. Ensure you copied the full sessionKey value.",
        )

    key_setting = db.query(Setting).filter(
        Setting.key == f"classroom:{user_id}:claude_session_key"
    ).first()
    if not key_setting:
        key_setting = Setting(
            key=f"classroom:{user_id}:claude_session_key",
            description="User's Claude session cookie for direct zero-latency solving.",
        )
        db.add(key_setting)
    key_setting.value = raw_key

    if payload.user_agent:
        ua_setting = db.query(Setting).filter(
            Setting.key == f"classroom:{user_id}:claude_user_agent"
        ).first()
        if not ua_setting:
            ua_setting = Setting(
                key=f"classroom:{user_id}:claude_user_agent",
                description="User's browser User-Agent for Claude session alignment.",
            )
            db.add(ua_setting)
        ua_setting.value = payload.user_agent.strip()

    db.commit()
    logger.info("Synced Claude session cookie for user %s", user_id)
    return {
        "status": "connected",
        "has_session_key": True,
        "message": "Claude session connected successfully. You can now enable automatic solving.",
    }


@router.delete("/claude-browser/session", response_model=dict)
def disconnect_claude_session(
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional),
):
    """Disconnect the student's synced Claude sessionKey cookie."""
    user_id = _classroom_user_id(clerk_user)
    db.query(Setting).filter(
        Setting.key.in_([
            f"classroom:{user_id}:claude_session_key",
            f"classroom:{user_id}:claude_user_agent",
        ])
    ).delete(synchronize_session=False)
    db.commit()
    return {"status": "disconnected", "has_session_key": False}


@router.delete("/claude-browser/profile", response_model=dict)
def delete_claude_browser_profile(
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional),
):
    user_id = _classroom_user_id(clerk_user)
    running_job = db.query(BrowserAutomationJob.id).filter(
        BrowserAutomationJob.user_id == user_id,
        BrowserAutomationJob.status == "running",
    ).first()
    if running_job:
        raise HTTPException(status_code=409, detail="Wait for the running assignment job to finish before deleting your Claude profile.")

    BrowserSessionClient().delete_profile(user_id)
    setting = db.query(Setting).filter(
        Setting.key == f"classroom:{user_id}:auto_solve_enabled"
    ).first()
    if setting:
        setting.value = "false"

    # Also delete synced session key
    db.query(Setting).filter(
        Setting.key.in_([
            f"classroom:{user_id}:claude_session_key",
            f"classroom:{user_id}:claude_user_agent",
        ])
    ).delete(synchronize_session=False)

    waiting_jobs = db.query(BrowserAutomationJob).filter(
        BrowserAutomationJob.user_id == user_id,
        BrowserAutomationJob.status.in_(["pending", "needs_login"]),
    ).all()
    for job in waiting_jobs:
        job.status = "needs_login"
        job.error = "Claude profile was deleted. Reconnect and resume this job after signing in."
        job.finished_at = datetime.now(timezone.utc)
    db.commit()
    return {"profile_deleted": True, "automatic_solving_enabled": False, "has_session_key": False}


@router.get("/claude-browser/status", response_model=dict)
def get_claude_browser_status(
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional),
):
    user_id = _classroom_user_id(clerk_user)
    try:
        result = BrowserSessionClient().status(user_id)
    except Exception:
        result = {"active": False, "profile_exists": False, "viewer_url": None}

    setting = db.query(Setting).filter(
        Setting.key == f"classroom:{user_id}:auto_solve_enabled"
    ).first()

    session_key_setting = db.query(Setting).filter(
        Setting.key == f"classroom:{user_id}:claude_session_key"
    ).first()
    has_session_key = bool(session_key_setting and session_key_setting.value)

    jobs = db.query(BrowserAutomationJob).filter(
        BrowserAutomationJob.user_id == user_id,
    ).order_by(BrowserAutomationJob.queued_at.desc()).limit(10).all()

    is_browser_active = bool(result.get("active"))
    return {
        **result,
        "is_open": is_browser_active,
        "has_session_key": has_session_key,
        "connected": has_session_key or is_browser_active,
        "automatic_solving_enabled": bool(setting and setting.value == "true"),
        "jobs": [
            {
                "id": job.id,
                "assignment_id": job.assignment_id,
                "assignment_title": job.assignment.title if job.assignment else None,
                "status": job.status,
                "attempts": job.attempts,
                "error": job.error,
                "queued_at": job.queued_at,
                "finished_at": job.finished_at,
            }
            for job in jobs
        ],
    }


@router.put("/claude-browser/automatic-solving", response_model=dict)
def set_automatic_claude_solving(
    enabled: bool = Body(..., embed=True),
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional),
):
    user_id = _classroom_user_id(clerk_user)
    session_key_setting = db.query(Setting).filter(
        Setting.key == f"classroom:{user_id}:claude_session_key"
    ).first()
    has_session_key = bool(session_key_setting and session_key_setting.value)
    browser_active = False
    try:
        browser_active = bool(BrowserSessionClient().status(user_id).get("active"))
    except Exception:
        pass

    if enabled and not (has_session_key or browser_active):
        raise HTTPException(
            status_code=409,
            detail="Connect your Claude account (via 1-click sync or starting the private browser) before enabling automatic solving.",
        )
    key = f"classroom:{user_id}:auto_solve_enabled"
    setting = db.query(Setting).filter(Setting.key == key).first()
    if not setting:
        setting = Setting(key=key, description="User opt-in for automatic Claude browser solving.")
        db.add(setting)
    setting.value = "true" if enabled else "false"
    if not enabled:
        now = datetime.now(timezone.utc)
        waiting_jobs = db.query(BrowserAutomationJob).filter(
            BrowserAutomationJob.user_id == user_id,
            BrowserAutomationJob.status.in_(["pending", "needs_login"]),
        ).all()
        for job in waiting_jobs:
            job.status = "cancelled"
            job.finished_at = now
            job.error = "Automatic solving was disabled before this job started."
    db.commit()
    return {"automatic_solving_enabled": enabled}


@router.post("/claude-browser/jobs/resume", response_model=dict)
def resume_claude_jobs(
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional),
):
    user_id = _classroom_user_id(clerk_user)
    enabled = db.query(Setting).filter(
        Setting.key == f"classroom:{user_id}:auto_solve_enabled",
        Setting.value == "true",
    ).first()
    if not enabled:
        raise HTTPException(status_code=409, detail="Enable automatic solving before resuming assignment jobs.")
    if not BrowserSessionClient().status(user_id).get("active"):
        raise HTTPException(status_code=409, detail="Start your private Claude browser before resuming assignment jobs.")
    jobs = db.query(BrowserAutomationJob).filter(
        BrowserAutomationJob.user_id == user_id,
        BrowserAutomationJob.status.in_(["needs_login", "failed"]),
    ).all()
    for job in jobs:
        job.status = "pending"
        job.queued_at = datetime.now(timezone.utc)
        job.finished_at = None
        job.error = None
        job.attempts = 0
    db.commit()
    return {"resumed": len(jobs)}


@router.post("/assignments/{assignment_id}/export-doc", response_model=dict)
def export_assignment_doc(
    assignment_id: int,
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional),
):
    """Export the validated assignment solution directly to a new Google Doc in Google Drive."""
    from app.db.models import AssignmentSolution
    from app.services.ai_solution import export_solution_to_google_doc

    user_id = _classroom_user_id(clerk_user)
    assignment = _get_owned_assignment(db, assignment_id, user_id)

    solution = db.query(AssignmentSolution).filter(AssignmentSolution.assignment_id == assignment_id).first()
    if not solution or not (solution.validated_content or solution.draft_content):
        raise HTTPException(status_code=400, detail="No solution content found to export. Generate a solution first.")

    content = solution.validated_content or solution.draft_content
    doc_info = export_solution_to_google_doc(db, assignment, content, user_id=user_id)
    if not doc_info:
        raise HTTPException(status_code=502, detail="Failed to create Google Doc. Please ensure Google account is connected with Drive permissions.")

    return {
        "success": True,
        "assignment_id": assignment_id,
        **doc_info
    }


@router.get("/assignments/{assignment_id}/solution/status", response_model=dict)
def get_solution_status(
    assignment_id: int,
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional),
):
    """Get AI solution generation status, content, and linked Google Doc."""
    from app.db.models import AssignmentSolution, Submission
    _get_owned_assignment(db, assignment_id, _classroom_user_id(clerk_user))
    solution = db.query(AssignmentSolution).filter(AssignmentSolution.assignment_id == assignment_id).first()
    if not solution:
        return {"status": "not_started"}

    from app.services.ai_solution import (
        extract_assignment_deliverables,
        extract_execution_metadata,
        strip_execution_metadata,
    )
    content = solution.validated_content or solution.draft_content or ""
    deliverables = extract_assignment_deliverables(strip_execution_metadata(content))
    execution_results = extract_execution_metadata(content)
    result_by_name = {item.get("filename"): item for item in execution_results}
    code_files = []
    for index, source_file in enumerate(deliverables["files"]):
        code_files.append({
            **source_file,
            "download_url": f"/api/v1/classroom/assignments/{assignment_id}/solution/files/{index}",
            "run": result_by_name.get(source_file["name"]),
        })

    terminal_screenshots = []
    if execution_results:
        from app.services.terminal_renderer import TerminalCardRenderer
        for result in execution_results:
            data_uri = result.get("screenshot_data_uri")
            if not data_uri:
                png = TerminalCardRenderer.generate_terminal_png(
                    result.get("command") or f"Run {result.get('filename') or 'solution file'}",
                    result.get("terminal_output") or "No terminal output was produced.",
                    title=f"Assignment run — {result.get('filename') or 'solution'}",
                )
                data_uri = f"data:image/png;base64,{base64.b64encode(png).decode('ascii')}"
            terminal_screenshots.append({
                "task": result.get("task"),
                "filename": result.get("filename"),
                "tool": result.get("tool", "Autonomous Runner"),
                "data_uri": data_uri,
            })

    submission = db.query(Submission).filter(Submission.assignment_id == assignment_id).first()
    google_doc_id = submission.google_doc_id if submission else None
    google_doc_url = f"https://docs.google.com/document/d/{google_doc_id}/edit" if google_doc_id else None
    progress_row = db.query(Setting).filter(Setting.key == f"assignment_crew_progress_{assignment_id}").first()
    try:
        crew_progress = json.loads(progress_row.value) if progress_row and progress_row.value else None
    except (TypeError, json.JSONDecodeError):
        crew_progress = None

    # Auto-clear stale or raw browser crash logs if assignment is not generating or is in DRAFT
    if solution.validation_errors and not (solution.validated_content or solution.draft_content):
        stale_error_indicators = (
            "Browser logs:",
            "Looks like you launched a headed browser",
            "Missing X server",
            "Target page, context or browser has been closed",
            "BrowserType.launch",
            "BrowserType.connect_over_cdp",
            "Could not connect to Chrome on port",
            "Cannot connect to the hosted browser",
            "Connection refused",
            "out of free messages",
        )
        is_raw_browser_log = any(ind in solution.validation_errors for ind in stale_error_indicators)
        if (assignment and assignment.status == AssignmentStatus.DRAFT) or is_raw_browser_log:
            logger.info("Auto-clearing stale browser error logs for assignment %s", assignment_id)
            solution.validation_errors = None
            db.commit()

    assignment = _get_owned_assignment(db, assignment_id, _classroom_user_id(clerk_user))
    has_content = bool(solution.validated_content or solution.draft_content)
    is_completed = bool(solution.validated_content)
    is_failed = bool(solution.validation_errors) and not has_content
    is_generating = bool(assignment and assignment.status == AssignmentStatus.GENERATING) and not is_completed and not is_failed

    user_id = _classroom_user_id(clerk_user)
    rate_limit_row = db.query(Setting).filter(Setting.key == f"classroom:{user_id}:claude_rate_limit").first()
    claude_rate_limit = None
    if rate_limit_row and rate_limit_row.value:
        try:
            claude_rate_limit = json.loads(rate_limit_row.value)
        except Exception:
            claude_rate_limit = None

    cleaned_validation_errors = solution.validation_errors
    if cleaned_validation_errors:
        if "Browser logs:" in cleaned_validation_errors:
            cleaned_validation_errors = cleaned_validation_errors.split("Browser logs:")[0].strip()
        if "Call log:" in cleaned_validation_errors:
            cleaned_validation_errors = cleaned_validation_errors.split("Call log:")[0].strip()

    enriched_tasks = []
    for task_item in deliverables.get("tasks", []):
        t_id = str(task_item.get("task"))
        matching_res = next((r for r in execution_results if str(r.get("task")) == t_id), None)
        matching_shot = next((s for s in terminal_screenshots if str(s.get("task")) == t_id), None)
        enriched_task = {
            **task_item,
            "run": matching_res,
            "screenshot_data_uri": task_item.get("screenshot_data_uri") or (matching_shot.get("data_uri") if matching_shot else None),
        }
        enriched_tasks.append(enriched_task)

    collected_images = _assignment_generated_images(db, assignment_id)
    if not collected_images:
        for t_item in enriched_tasks:
            for img in t_item.get("image_uris", []):
                collected_images.append({
                    "task": t_item.get("task"),
                    "caption": img.get("caption"),
                    "data_uri": img.get("uri"),
                })

    return {
        "status": "completed" if is_completed else "failed" if is_failed else "generating" if is_generating else "not_started",
        "draft_content": strip_execution_metadata(solution.draft_content or ""),
        "validated_content": strip_execution_metadata(solution.validated_content or ""),
        "tasks": enriched_tasks,
        "generated_files": code_files,
        "terminal_outputs": execution_results,
        "terminal_screenshots": terminal_screenshots,
        "generated_images": collected_images,
        "crew_progress": crew_progress,
        "code_files_download_url": f"/api/v1/classroom/assignments/{assignment_id}/solution/files" if deliverables["files"] else None,
        "validation_errors": cleaned_validation_errors,
        "claude_rate_limit": claude_rate_limit,
        "retry_count": solution.retry_count,
        "ai_provider": solution.ai_provider,
        "generated_at": solution.generated_at,
        "validated_at": solution.validated_at,
        "google_doc_id": google_doc_id,
        "google_doc_url": google_doc_url,
    }


@router.post("/assignments/{assignment_id}/solution/clear-error", response_model=dict)
@router.delete("/assignments/{assignment_id}/solution/error", response_model=dict)
def clear_solution_error(
    assignment_id: int,
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional),
):
    """Clear validation errors/logs for an assignment solution so the user has a fresh slate."""
    _get_owned_assignment(db, assignment_id, _classroom_user_id(clerk_user))
    solution = db.query(AssignmentSolution).filter(AssignmentSolution.assignment_id == assignment_id).first()
    if solution and solution.validation_errors:
        solution.validation_errors = None
        db.commit()
    return {"status": "cleared", "assignment_id": assignment_id}


@router.get("/assignments/{assignment_id}/solution/files")
def download_solution_files(
    assignment_id: int,
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional),
):
    """Download one source file per generated task in a ZIP archive."""
    from app.services.ai_solution import extract_assignment_deliverables, extract_execution_metadata, strip_execution_metadata

    _get_owned_assignment(db, assignment_id, _classroom_user_id(clerk_user))
    solution = db.query(AssignmentSolution).filter(AssignmentSolution.assignment_id == assignment_id).first()
    if not solution or not (solution.validated_content or solution.draft_content):
        raise HTTPException(status_code=404, detail="No generated solution is available.")
    deliverables = extract_assignment_deliverables(strip_execution_metadata(solution.validated_content or solution.draft_content or ""))
    files = deliverables["files"]
    if not files:
        raise HTTPException(status_code=404, detail="No task source code files were found in this solution.")

    archive = BytesIO()
    with zipfile.ZipFile(archive, mode="w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for source_file in files:
            bundle.writestr(source_file["name"], source_file["content"])
        execution_results = extract_execution_metadata(solution.validated_content or solution.draft_content or "")
        for index, output in enumerate(execution_results or deliverables["terminal_outputs"]):
            filename = output.get("filename") or f"terminal_output_task_{output.get('task', index + 1)}.txt"
            text = output.get("terminal_output") or output.get("content") or "No terminal output was produced."
            bundle.writestr(f"terminal_output_{filename}.txt", text + "\n")
    return Response(
        content=archive.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="assignment_{assignment_id}_code.zip"'},
    )


@router.get("/assignments/{assignment_id}/solution/files/{file_index}")
def download_solution_file(
    assignment_id: int,
    file_index: int,
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional),
):
    """Download one generated source file by its stable list position."""
    from app.services.ai_solution import extract_assignment_deliverables, strip_execution_metadata

    _get_owned_assignment(db, assignment_id, _classroom_user_id(clerk_user))
    solution = db.query(AssignmentSolution).filter(AssignmentSolution.assignment_id == assignment_id).first()
    if not solution or not (solution.validated_content or solution.draft_content):
        raise HTTPException(status_code=404, detail="No generated solution is available.")
    content = strip_execution_metadata(solution.validated_content or solution.draft_content or "")
    files = extract_assignment_deliverables(content)["files"]
    if file_index < 0 or file_index >= len(files):
        raise HTTPException(status_code=404, detail="Generated source file not found.")
    source_file = files[file_index]
    safe_name = source_file["name"].replace('"', "")
    return Response(
        content=source_file["content"],
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}"'},
    )


@router.get("/assignments/{assignment_id}/solution/report")
def download_solution_report(
    assignment_id: int,
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional),
):
    """Download a self-contained HTML report with generated code and run screenshots."""
    from app.services.ai_solution import extract_code_deliverables, extract_execution_metadata, strip_execution_metadata
    from app.services.terminal_renderer import TerminalCardRenderer

    user_id = _classroom_user_id(clerk_user)
    assignment = _get_owned_assignment(db, assignment_id, user_id)
    solution = db.query(AssignmentSolution).filter(AssignmentSolution.assignment_id == assignment_id).first()
    if not solution or not (solution.validated_content or solution.draft_content):
        raise HTTPException(status_code=404, detail="No generated solution report is available.")

    content = solution.validated_content or solution.draft_content or ""
    clean_content = strip_execution_metadata(content)
    deliverables = extract_code_deliverables(clean_content)
    execution_results = extract_execution_metadata(content)
    result_by_name = {item.get("filename"): item for item in execution_results}
    course = db.query(Course).filter(
        Course.id == assignment.course_id,
        Course.user_id == user_id,
    ).first()
    profile_row = db.query(Setting).filter(Setting.key == f"clerk_user_{user_id}").first()
    profile = {}
    if profile_row and profile_row.value:
        try:
            profile = json.loads(profile_row.value)
        except (TypeError, json.JSONDecodeError):
            profile = {}
    student_name = " ".join(part for part in (profile.get("first_name"), profile.get("last_name")) if part).strip() or "Student"
    instructor = course.teacher_name if course and course.teacher_name else "Instructor not provided"
    course_name = course.name if course else "Course"

    sections = []
    for source_file in deliverables["files"]:
        result = result_by_name.get(source_file["name"], {})
        output_text = result.get("terminal_output") or "No terminal output was produced."
        png = TerminalCardRenderer.generate_terminal_png(
            result.get("command") or f"Run {source_file['name']}", output_text,
            title=f"Assignment run — {source_file['name']}",
        )
        screenshot = f"data:image/png;base64,{base64.b64encode(png).decode('ascii')}"
        status = result.get("status", "not_run").replace("_", " ").title()
        sections.append(
            f"<section class=\"task\"><h2>Task {html.escape(str(source_file['task']))} · {html.escape(source_file['name'])}</h2>"
            f"<p class=\"meta\">{html.escape(source_file['language'])} · Run status: {html.escape(status)} · Exit code: {html.escape(str(result.get('exit_code') if result.get('exit_code') is not None else 'n/a'))}</p>"
            f"<h3>Source code</h3><pre><code>{html.escape(source_file['content'])}</code></pre>"
            f"<h3>Terminal output</h3><pre><code>{html.escape(output_text)}</code></pre>"
            f"<figure><img alt=\"Terminal screenshot for {html.escape(source_file['name'])}\" src=\"{screenshot}\"/><figcaption>Run evidence · {html.escape(source_file['name'])}</figcaption></figure></section>"
        )
    for generated_image in _assignment_generated_images(db, assignment_id):
        image_uri = generated_image.get("data_uri", "")
        prompt = html.escape(generated_image.get("prompt", "Generated assignment illustration"))
        if image_uri.startswith("data:image/"):
            sections.append(
                f'<section class="task"><h2>Generated illustration</h2>'
                f'<p class="meta">Prompt: {prompt}</p><figure><img alt="Generated assignment illustration" '
                f'src="{image_uri}"/><figcaption>AI-generated image · review before including in a submission</figcaption></figure></section>'
            )
    if not sections:
        sections.append(f"<section class=\"task\"><h2>Solution</h2><pre><code>{html.escape(clean_content)}</code></pre><p class=\"meta\">No separate code files were extracted from this solution.</p></section>")

    report = f"""<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>{html.escape(assignment.title or 'Assignment')} · Solution report</title><style>
      *{{box-sizing:border-box}}body{{margin:0;background:#f3f4f7;color:#20232d;font:15px/1.55 Arial,sans-serif}}.cover{{min-height:92vh;padding:12vh 12%;display:flex;flex-direction:column;justify-content:center;background:#fff;border-bottom:1px solid #ddd}}.brand{{color:#6557c9;font-weight:700;letter-spacing:.12em;text-transform:uppercase}}h1{{font-size:36px;line-height:1.2;margin:20px 0 30px}}.cover dl{{display:grid;grid-template-columns:180px 1fr;gap:10px 20px;max-width:650px}}dt{{color:#747987}}dd{{margin:0;font-weight:600}}main{{max-width:920px;margin:40px auto;padding:0 20px}}.task{{margin:24px 0;padding:30px;background:#fff;border:1px solid #e3e5eb;border-radius:12px;break-inside:avoid}}h2{{margin:0 0 6px;font-size:21px}}h3{{margin:24px 0 8px;font-size:13px;text-transform:uppercase;letter-spacing:.08em;color:#717687}}.meta,figcaption{{font-size:12px;color:#737888}}pre{{overflow:auto;white-space:pre-wrap;overflow-wrap:anywhere;margin:0;padding:16px;border-radius:8px;background:#111827;color:#ecf0f8;font:12px/1.6 Consolas,monospace}}figure{{margin:18px 0 0}}img{{display:block;width:100%;height:auto;border-radius:8px}}figcaption{{margin-top:7px}}@media print{{body{{background:white}}.cover{{min-height:95vh;page-break-after:always}}main{{margin:0 auto}}.task{{box-shadow:none}}}}
      </style></head><body><header class=\"cover\"><p class=\"brand\">Uniflow · Academic report</p><h1>{html.escape(assignment.title or 'Assignment solution')}</h1><dl><dt>Course</dt><dd>{html.escape(course_name)}</dd><dt>Student</dt><dd>{html.escape(student_name)}</dd><dt>Student ID</dt><dd>{html.escape(str(profile.get('student_id') or profile.get('roll_no') or 'Not provided'))}</dd><dt>Instructor</dt><dd>{html.escape(instructor)}</dd><dt>Due date</dt><dd>{html.escape(assignment.due_at.strftime('%B %d, %Y') if assignment.due_at else 'Not specified')}</dd><dt>Report date</dt><dd>{datetime.now().strftime('%B %d, %Y')}</dd></dl></header><main>{''.join(sections)}</main></body></html>"""
    return Response(
        content=report,
        media_type="text/html; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="assignment_{assignment_id}_report.html"'},
    )


@router.get("/assignments/{assignment_id}/solution/report/docx")
def download_solution_report_docx(
    assignment_id: int,
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional),
):
    """Download a Word report based on the generated Google Doc template, with run screenshots embedded."""
    from docx import Document
    from docx.shared import Inches
    from app.services.ai_solution import extract_code_deliverables, extract_execution_metadata, strip_execution_metadata
    from app.services.terminal_renderer import TerminalCardRenderer

    user_id = _classroom_user_id(clerk_user)
    assignment = _get_owned_assignment(db, assignment_id, user_id)
    solution = db.query(AssignmentSolution).filter(AssignmentSolution.assignment_id == assignment_id).first()
    if not solution or not (solution.validated_content or solution.draft_content):
        raise HTTPException(status_code=404, detail="No generated solution report is available.")

    course = db.query(Course).filter(
        Course.id == assignment.course_id,
        Course.user_id == user_id,
    ).first()
    submission = db.query(Submission).filter(Submission.assignment_id == assignment.id).first()
    docs_service = get_google_docs_service(db, user_id=user_id)
    docx_content = docs_service.export_doc_as_docx(submission.google_doc_id) if docs_service and submission and submission.google_doc_id else None
    document = Document(BytesIO(docx_content)) if docx_content else Document()

    content = solution.validated_content or solution.draft_content or ""
    clean_content = strip_execution_metadata(content)
    deliverables = extract_code_deliverables(clean_content)
    execution_results = extract_execution_metadata(content)
    results_by_name = {item.get("filename"): item for item in execution_results}

    if not docx_content:
        profile_row = db.query(Setting).filter(Setting.key == f"clerk_user_{user_id}").first()
        profile = {}
        if profile_row and profile_row.value:
            try:
                profile = json.loads(profile_row.value)
            except (TypeError, json.JSONDecodeError):
                profile = {}
        student = " ".join(part for part in (profile.get("first_name"), profile.get("last_name")) if part).strip() or "Student"
        document.add_heading("Uniflow · Academic report", 0)
        document.add_heading(assignment.title or "Assignment solution", level=1)
        document.add_paragraph(f"Course: {course.name if course else 'Course'}")
        document.add_paragraph(f"Student: {student}")
        document.add_paragraph(f"Instructor: {course.teacher_name if course and course.teacher_name else 'Not provided'}")
        document.add_paragraph(f"Due date: {assignment.due_at.strftime('%B %d, %Y') if assignment.due_at else 'Not specified'}")
        document.add_page_break()
        for source_file in deliverables["files"]:
            document.add_heading(f"Task {source_file['task']} · {source_file['name']}", level=1)
            document.add_heading("Source code", level=2)
            document.add_paragraph(source_file["content"])
            result = results_by_name.get(source_file["name"], {})
            document.add_heading("Terminal output", level=2)
            document.add_paragraph(result.get("terminal_output") or "No terminal output was produced.")

    if execution_results:
        document.add_page_break()
        document.add_heading("Code execution evidence", level=1)
        for result in execution_results:
            file_name = result.get("filename") or "Generated source"
            document.add_heading(file_name, level=2)
            run_state = result.get("status", "not_run").replace("_", " ").title()
            document.add_paragraph(f"Run status: {run_state} · Exit code: {result.get('exit_code') if result.get('exit_code') is not None else 'n/a'}")
            screenshot = TerminalCardRenderer.generate_terminal_png(
                result.get("command") or f"Run {file_name}",
                result.get("terminal_output") or "No terminal output was produced.",
                title=f"Assignment run — {file_name}",
            )
            document.add_picture(BytesIO(screenshot), width=Inches(6.2))
            document.add_paragraph(f"Run screenshot · {file_name}")

    generated_images = _assignment_generated_images(db, assignment_id)
    if generated_images:
        document.add_page_break()
        document.add_heading("Generated illustrations", level=1)
        for image in generated_images:
            prompt = image.get("prompt", "")
            document.add_paragraph(f"Prompt: {prompt}")
            data_uri = image.get("data_uri", "")
            if data_uri.startswith("data:image/") and "," in data_uri:
                try:
                    document.add_picture(BytesIO(base64.b64decode(data_uri.split(",", 1)[1])), width=Inches(5.8))
                    document.add_paragraph("AI-generated illustration · verify content and attribution requirements.")
                except (ValueError, OSError):
                    document.add_paragraph("Image data could not be embedded in this Word export.")

    output = BytesIO()
    document.save(output)
    return Response(
        content=output.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="assignment_{assignment_id}_report.docx"'},
    )


@router.get("/assignments/{assignment_id}/submissions", response_model=List[dict])
def get_assignment_submissions(
    assignment_id: int,
    since: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional),
):
    """Get student submissions for an assignment from Google Classroom API"""
    user_id = _classroom_user_id(clerk_user)
    service = get_classroom_service(db, user_id=user_id)
    if not service:
        raise HTTPException(status_code=503, detail="Google Classroom not configured")

    assignment = _get_owned_assignment(db, assignment_id, user_id)

    since_dt = _get_semester_start_dt(db, since, user_id=user_id)
    if since_dt:
        # Check if assignment is within semester range
        assignment_due = assignment.due_at or assignment.due_date
        assignment_created = assignment.created_at
        if assignment_due and assignment_due < since_dt:
            if not (assignment_created and assignment_created >= since_dt):
                return []
    
    course = db.query(Course).filter(
        Course.id == assignment.course_id,
        Course.user_id == user_id,
    ).first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    submissions = service.get_student_submissions(course.external_id, assignment.external_id)
    return [
        {
            "id": s.get("id"),
            "user_id": s.get("userId"),
            "state": s.get("state"),
            "assigned_grade": s.get("assignedGrade"),
            "draft_grade": s.get("draftGrade"),
            "late": s.get("late"),
            "submitted_at": s.get("submittedAt"),
        }
        for s in submissions
    ]
