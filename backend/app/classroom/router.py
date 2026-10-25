from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks, Body, Request, File, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any, Tuple, Union
from datetime import datetime, timezone, timedelta
from hashlib import sha256
import json
import html
import base64
import zipfile
import re
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
from app.core.security import encrypt_token_if_needed
from app.services.classroom_sync import get_classroom_service
from app.services.google_docs import get_google_docs_service
from app.auth.clerk_auth import get_current_user_optional
from app.auth.ownership import require_user_id, user_owner_ids
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
    return require_user_id(clerk_user)


def _get_owned_assignment(db: Session, assignment_id: int, user_id: str) -> Assignment:
    owners = user_owner_ids(user_id)
    assignment = db.query(Assignment).filter(
        Assignment.id == assignment_id,
        Assignment.user_id.in_(owners),
    ).first()
    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")
    return assignment


def _get_user_lock(user_id: str):
    from app.core.redis import get_user_lock
    return get_user_lock("classroom_sync", user_id, ttl_seconds=300)


def _get_semester_start_dt(db: Session, override: Optional[str] = None, user_id: str = "default") -> datetime:
    from app.core.user_settings import get_semester_start_date
    return get_semester_start_date(db, user_id=user_id, override=override)


@router.get("/settings", response_model=dict)
def get_classroom_settings(
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional)
):
    """Get Classroom synchronization and semester settings (isolated per-user)"""
    from app.core.user_settings import get_semester_start_date
    user_id = _classroom_user_id(clerk_user)
    dt = get_semester_start_date(db, user_id=user_id)
    return {"semester_start_date": dt.isoformat()}


@router.post("/settings", response_model=dict)
@router.put("/settings", response_model=dict)
def save_classroom_settings(
    payload: Dict[str, Any] = Body(...),
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional)
):
    """Save semester start date setting per user"""
    from app.core.user_settings import set_semester_start_date
    user_id = _classroom_user_id(clerk_user)
    start_date = payload.get("semester_start_date")
    set_semester_start_date(db, user_id, str(start_date).strip().replace('"', '') if start_date else None)
    return {
        "message": "Classroom settings updated",
        "semester_start_date": str(start_date).strip().replace('"', '') if start_date else None
    }


class StudentProfilePayload(BaseModel):
    student_name: str
    roll_no: str
    university: Optional[str] = "AIR UNIVERSITY, ISLAMABAD"
    department: Optional[str] = "Department of Computer Science & Information Technology"
    section: Optional[str] = ""


@router.get("/student-profile", response_model=dict)
def get_student_profile(
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional)
):
    """Get student academic identity for document cover pages, Google Docs naming, and terminal prompts"""
    from app.services.claude_browser_solver import get_student_metadata
    user_id = _classroom_user_id(clerk_user)
    meta = get_student_metadata(db, course=None, user_id=user_id)
    return {
        "student_name": meta.get("student_name", "Student"),
        "roll_no": meta.get("roll_no", ""),
        "university": meta.get("university", "AIR UNIVERSITY, ISLAMABAD"),
        "department": meta.get("department", "Department of Computer Science & Information Technology"),
        "section": meta.get("section", ""),
    }


@router.put("/student-profile", response_model=dict)
def update_student_profile(
    payload: StudentProfilePayload,
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional)
):
    """Save student full name, roll/reg no, and institutional info for Google Docs and terminal outputs"""
    user_id = _classroom_user_id(clerk_user)
    setting_key = f"student_profile_{user_id}"
    setting = db.query(Setting).filter(Setting.key == setting_key).first()
    if not setting:
        setting = Setting(key=setting_key, description=f"Student academic profile for {user_id}")
        db.add(setting)

    data = payload.dict()
    setting.value = json.dumps(data)
    db.commit()
    return {"message": "Student profile updated successfully", "profile": data}


class OnboardingSavePayload(BaseModel):
    student_name: Optional[str] = None
    roll_no: Optional[str] = None
    semester_start_date: Optional[str] = None
    claude_session_key: Optional[str] = None
    portal_cookies: Optional[str] = None
    dismiss: Optional[bool] = True


@router.get("/onboarding-status", response_model=dict)
def get_onboarding_status(
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional)
):
    """Aggregated status of student setup to determine if onboarding modal should be shown."""
    from app.services.claude_browser_solver import get_student_metadata
    from app.db.repositories import GoogleCredentialRepository
    from app.auth.router import _cached_google_emails

    user_id = _classroom_user_id(clerk_user)

    # 1. Dismissed check
    dismissed_setting = db.query(Setting).filter(
        Setting.key == f"classroom:{user_id}:onboarding_dismissed"
    ).first()
    is_dismissed = bool(dismissed_setting and dismissed_setting.value == "true")

    # 2. Student Profile (Name & Roll No)
    meta = get_student_metadata(db, course=None, user_id=user_id)
    raw_name = (meta.get("student_name") or "").strip()
    raw_roll = (meta.get("roll_no") or "").strip()
    profile_configured = bool(raw_name and raw_name.lower() not in ["student", "default student"] and raw_roll)

    # 3. Semester Start Date
    sem_setting = db.query(Setting).filter(
        Setting.key == f"classroom:{user_id}:semester_start_date"
    ).first()
    semester_configured = bool(sem_setting and sem_setting.value and sem_setting.value.strip())
    semester_start_date = sem_setting.value.strip().replace('"', '') if semester_configured else None

    # Default fallback semester date if unconfigured
    if not semester_start_date:
        now = datetime.now(timezone.utc)
        if now.month >= 8:
            semester_start_date = f"{now.year}-09-01"
        else:
            semester_start_date = f"{now.year}-02-01"

    # 4. Google Classroom OAuth Connection
    repo = GoogleCredentialRepository(db)
    cred = repo.get(user_id) if user_id else None
    google_connected = cred is not None and bool(cred.access_token)
    google_email = _cached_google_emails.get(user_id) if user_id else None
    if not google_email and google_connected:
        email_setting = db.query(Setting).filter(
            Setting.key == f"google_connected_email_{user_id}"
        ).first()
        if email_setting and email_setting.value:
            google_email = email_setting.value

    # 5. Claude AI session cookie
    claude_setting = db.query(Setting).filter(
        Setting.key == f"classroom:{user_id}:claude_session_key"
    ).first()
    claude_connected = bool(claude_setting and claude_setting.value and claude_setting.value.strip())

    # 6. University Portal session cookie
    portal_cookie_setting = db.query(Setting).filter(
        Setting.key.in_([
            f"portal:{user_id}:portal_session_cookies",
            f"portal:{user_id}:session_cookies"
        ])
    ).first()
    portal_connected = bool(portal_cookie_setting and portal_cookie_setting.value and portal_cookie_setting.value.strip())

    # Check which items are missing
    missing_items = []
    if not profile_configured:
        missing_items.append("profile")
    if not semester_configured:
        missing_items.append("semester_date")
    if not google_connected:
        missing_items.append("google_classroom")
    if not claude_connected:
        missing_items.append("claude_cookie")
    if not portal_connected:
        missing_items.append("portal_cookie")

    needs_onboarding = len(missing_items) > 0
    should_show = (not is_dismissed) and needs_onboarding

    return {
        "is_dismissed": is_dismissed,
        "needs_onboarding": needs_onboarding,
        "should_show": should_show,
        "missing_items": missing_items,
        "profile": {
            "configured": profile_configured,
            "student_name": raw_name if raw_name.lower() not in ["student", "default student"] else "",
            "roll_no": raw_roll,
        },
        "semester": {
            "configured": semester_configured,
            "semester_start_date": semester_start_date,
        },
        "google": {
            "connected": google_connected,
            "email": google_email,
        },
        "claude": {
            "connected": claude_connected,
        },
        "portal": {
            "connected": portal_connected,
        },
    }


@router.post("/onboarding-dismiss", response_model=dict)
def dismiss_onboarding(
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional)
):
    """Mark onboarding flow as dismissed so it is not shown again."""
    user_id = _classroom_user_id(clerk_user)
    setting_key = f"classroom:{user_id}:onboarding_dismissed"
    setting = db.query(Setting).filter(Setting.key == setting_key).first()
    if not setting:
        setting = Setting(key=setting_key, description=f"Onboarding dismissed flag for {user_id}")
        db.add(setting)
    setting.value = "true"
    db.commit()
    return {"status": "dismissed", "message": "Onboarding modal dismissed."}


@router.post("/onboarding-save", response_model=dict)
def save_onboarding_data(
    payload: OnboardingSavePayload,
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional)
):
    """Bulk save configured onboarding settings and dismiss."""
    user_id = _classroom_user_id(clerk_user)

    # 1. Profile
    if payload.student_name or payload.roll_no:
        profile_key = f"student_profile_{user_id}"
        p_setting = db.query(Setting).filter(Setting.key == profile_key).first()
        if not p_setting:
            p_setting = Setting(key=profile_key, description=f"Student academic profile for {user_id}")
            db.add(p_setting)
        current_data = {}
        if p_setting.value:
            try:
                current_data = json.loads(p_setting.value)
            except Exception:
                current_data = {}
        if payload.student_name:
            current_data["student_name"] = payload.student_name.strip()
        if payload.roll_no:
            current_data["roll_no"] = payload.roll_no.strip()
        if "university" not in current_data:
            current_data["university"] = "AIR UNIVERSITY, ISLAMABAD"
        if "department" not in current_data:
            current_data["department"] = "Department of Computer Science & Information Technology"
        p_setting.value = json.dumps(current_data)

    # 2. Semester date
    if payload.semester_start_date:
        sem_key = f"classroom:{user_id}:semester_start_date"
        s_setting = db.query(Setting).filter(Setting.key == sem_key).first()
        if not s_setting:
            s_setting = Setting(key=sem_key, description=f"Semester start date filter for user {user_id}")
            db.add(s_setting)
        s_setting.value = payload.semester_start_date.strip().replace('"', '')

    # 3. Claude session key
    if payload.claude_session_key and len(payload.claude_session_key.strip()) >= 15:
        c_key = payload.claude_session_key.strip()
        if "sessionKey=" in c_key:
            c_key = c_key.split("sessionKey=")[-1].split(";")[0].strip()
        c_key = c_key.strip('"\'')
        c_setting = db.query(Setting).filter(Setting.key == f"classroom:{user_id}:claude_session_key").first()
        if not c_setting:
            c_setting = Setting(key=f"classroom:{user_id}:claude_session_key", description="Claude session cookie")
            db.add(c_setting)
        c_setting.value = encrypt_token_if_needed(c_key)

    # 4. Portal cookies
    if payload.portal_cookies and payload.portal_cookies.strip():
        portal_key = f"portal:{user_id}:portal_session_cookies"
        row = db.query(Setting).filter(Setting.key == portal_key).first()
        if not row:
            row = Setting(key=portal_key, description="Student portal session cookies")
            db.add(row)
        row.value = payload.portal_cookies.strip()

        status_key = f"portal:{user_id}:portal_session_status"
        s_row = db.query(Setting).filter(Setting.key == status_key).first()
        if not s_row:
            s_row = Setting(key=status_key, description="Portal session status")
            db.add(s_row)
        s_row.value = "ACTIVE"

    # 5. Dismiss flag
    if payload.dismiss:
        d_key = f"classroom:{user_id}:onboarding_dismissed"
        d_setting = db.query(Setting).filter(Setting.key == d_key).first()
        if not d_setting:
            d_setting = Setting(key=d_key, description=f"Onboarding dismissed flag for {user_id}")
            db.add(d_setting)
        d_setting.value = "true"

    db.commit()
    return {"status": "success", "message": "Onboarding settings saved successfully"}



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
    # Portal timetable/attendance imports share the Course table for academic
    # views, but they are not Google Classroom courses and have no Classroom
    # coursework. Keeping them out of this endpoint prevents duplicate cards.
    query = query.filter(~Course.external_id.startswith("portal-"))
    if active_only:
        query = query.filter(Course.course_state.in_(["ACTIVE", "active", ""]) | Course.course_state.is_(None))
    since_dt = _get_semester_start_dt(db, since, user_id=user_id)
    if since_dt:
        query = query.filter((Course.created_at >= since_dt) | (Course.updated_at >= since_dt) | Course.created_at.is_(None))
    courses = query.order_by(Course.name.asc(), Course.id.asc()).all()
    # Be defensive with legacy databases that predate the per-user unique
    # constraint. Google Classroom's course ID is the canonical identity.
    unique_courses = {}
    for course in courses:
        unique_courses.setdefault(course.external_id, course)
    courses = list(unique_courses.values())
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
    """Trigger direct live Google Classroom sync: immediately fetches latest courses, coursework,
    and submission states to display on the frontend instantly, while running heavy Drive file
    downloads, S3 storage, and text indexing asynchronously in the background."""
    user_id = _classroom_user_id(clerk_user)
    service = get_classroom_service(db, user_id=user_id)
    if not service:
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

    since_dt = _get_semester_start_dt(db, override=start_date, user_id=user_id)

    # 1. IMMEDIATE LIVE FETCH: Direct call to GCR API for courses & coursework
    assignments = []
    try:
        assignments = service.fast_sync_assignments(since_date=since_dt)
    except Exception as fast_err:
        service.db.rollback()
        err_msg = str(fast_err)
        if "invalid_grant" in err_msg or "expired or revoked" in err_msg:
            logger.warning(f"Google OAuth token expired or revoked for {user_id}: {fast_err}")
            try:
                cached_assignments = service._get_assignments_for_user(since_date=since_dt)
            except Exception:
                service.db.rollback()
                cached_assignments = []
            return {
                "status": "reconnect_required",
                "message": "Google Classroom token has expired. Please reconnect your Google account.",
                "assignments": cached_assignments,
                "count": len(cached_assignments),
            }
        logger.warning(f"Fast coursework sync error for {user_id}: {fast_err}")
        try:
            assignments = service._get_assignments_for_user(since_date=since_dt)
        except Exception as query_err:
            service.db.rollback()
            logger.error(f"Could not load cached assignments after fast sync error: {query_err}")
            assignments = []

    # 2. RUN HEAVY SYNC IN BACKGROUND (Drive file downloads, S3 uploads, PDF text extraction)
    lock = _get_user_lock(user_id)
    acquired = lock.acquire(blocking=False)
    status_key = f"classroom:{user_id}:sync_status"

    if acquired:
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

    return {
        "message": f"Directly fetched {len(assignments)} assignments from Google Classroom.",
        "status": "ready",
        "assignments": assignments,
        "count": len(assignments),
        "background_sync": "running" if acquired else "already_running"
    }


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
    
    # Preserve privacy for older files that may have been made link-accessible.
    for drive_id in [student_doc_id, *drive_file_ids]:
        if not docs_service.remove_public_sharing(drive_id):
            raise HTTPException(status_code=502, detail="Could not verify private sharing for an attached Drive file.")
    
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
            body={},
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
            id=submission_id,
            body={},
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


def _attach_submission_files(
    classroom_service,
    course_id: str,
    coursework_id: str,
    file_ids: List[str],
    return_state: bool = False,
) -> Union[str, Tuple[str, str]]:
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

        sub_obj = student_submissions[0]
        submission_id = sub_obj["id"]
        sub_state = sub_obj.get("state", "NEW")

        # Check existing attachments so we don't try to re-add duplicate attachments
        existing_attachments = sub_obj.get("assignmentSubmission", {}).get("attachments", [])
        existing_drive_ids = set()
        for att in existing_attachments:
            drive_file = att.get("driveFile")
            if drive_file and drive_file.get("id"):
                existing_drive_ids.add(drive_file.get("id"))

        files_to_add = [fid for fid in file_ids if fid and fid not in existing_drive_ids]

        if files_to_add:
            try:
                submissions_api.modifyAttachments(
                    courseId=course_id,
                    courseWorkId=coursework_id,
                    id=submission_id,
                    body={"addAttachments": [{"driveFile": {"id": file_id}} for file_id in files_to_add]},
                ).execute()
            except Exception as attach_err:
                err_str = str(attach_err)
                logger.error(f"Failed to modifyAttachments on submission {submission_id}: {attach_err}")
                raise HTTPException(status_code=502, detail="Failed to attach files to Google Classroom") from attach_err

        if return_state:
            return submission_id, sub_state
        return submission_id
    except HTTPException:
        raise
    except Exception as error:
        logger.error(f"Failed to attach Drive files to Google Classroom: {error}")
        raise HTTPException(status_code=502, detail="Failed to attach files to Google Classroom") from error


def _resolve_student_assignment_url(assignment, course, classroom_service) -> str:
    """Resolve the authentic Google Classroom URL for student viewing and turn-in."""
    target_url = getattr(assignment, "url", None)
    if not target_url or "classroom.google.com" not in target_url:
        try:
            work_obj = classroom_service.courses().courseWork().get(
                courseId=course.external_id,
                id=assignment.external_id,
            ).execute()
            target_url = work_obj.get("alternateLink") or target_url
        except Exception as e:
            logger.warning("Could not fetch alternateLink from Google Classroom API: %s", e)

    if target_url and "/submissions/" in target_url:
        target_url = target_url.split("/submissions/")[0] + "/details"
    elif target_url and not target_url.endswith("/details") and "/a/" in target_url:
        target_url = target_url.rstrip("/") + "/details"
    elif not target_url:
        target_url = f"https://classroom.google.com/c/{course.external_id}/a/{assignment.external_id}/details"

    return target_url



def execute_quick_turn_in(db: Session, assignment_id: int, user_id: str, action: str = "turn_in") -> dict:
    """
    Immediate Quick Turn In / Deliverables Attachment:
    1. Checks/creates Google Doc with formatted solution and cover intro page.
    2. Packages all code deliverables and terminal outputs into a ZIP file.
    3. Uploads ZIP archive to student's Google Drive.
    4. Attaches BOTH Google Doc and ZIP file to Google Classroom coursework submission.
    5. If action == 'attach_only': leaves files safely attached as a draft.
       If action == 'turn_in': executes turnIn via API, or delegates to Companion Extension.
    """
    from app.services.ai_solution import (
        extract_assignment_deliverables,
        extract_execution_metadata,
        strip_execution_metadata,
        export_solution_to_google_doc,
        append_downloaded_assets_to_zip,
    )

    assignment = _get_owned_assignment(db, assignment_id, user_id)
    course = db.query(Course).filter(
        Course.id == assignment.course_id,
        Course.user_id == user_id,
    ).first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    service = get_classroom_service(db, user_id=user_id)
    if not service:
        raise HTTPException(status_code=503, detail="Google Classroom not configured")

    docs_service = get_google_docs_service(db, user_id=user_id)
    if not docs_service:
        raise HTTPException(status_code=503, detail="Google Docs not configured")

    solution = db.query(AssignmentSolution).filter(AssignmentSolution.assignment_id == assignment_id).first()
    existing_sub = db.query(Submission).filter(Submission.assignment_id == assignment_id).first()
    student_doc_id = existing_sub.google_doc_id if (existing_sub and existing_sub.google_doc_id) else None
    # The solution exporter persists its Doc ID before quick-turn-in attaches
    # anything. If a prior attempt stopped at the exporter/response-contract
    # boundary, that row has the same ID in both Doc/Drive columns and no
    # Classroom submission ID. Reuse it rather than generating orphan Docs.
    pending_export_doc = bool(
        existing_sub
        and existing_sub.google_doc_id
        and existing_sub.google_doc_id == existing_sub.google_drive_file_id
        and not existing_sub.classroom_attachment_id
    )

    raw_content = ""
    if solution:
        raw_content = solution.validated_content or solution.draft_content or ""

    if not raw_content and not student_doc_id:
        raise HTTPException(
            status_code=400,
            detail="No solution content found to turn in. Please generate an assignment solution first."
        )

    clean_content = strip_execution_metadata(raw_content) if raw_content else (assignment.description or "Assignment Solution Deliverable")
    content_digest = sha256(clean_content.encode("utf-8")).hexdigest()
    digest_key = f"quick_turn_in_digest_{sha256(user_id.encode('utf-8')).hexdigest()}_{assignment_id}"
    digest_row = db.query(Setting).filter(Setting.key == digest_key).first()
    same_content_as_previous = bool(digest_row and digest_row.value == content_digest)
    reusable_drive_pair = bool(
        same_content_as_previous and existing_sub and existing_sub.google_doc_id
        and existing_sub.google_drive_file_id
    )
    existing_state = getattr(existing_sub.submission_state, "value", existing_sub.submission_state) if existing_sub else None

    if existing_sub and same_content_as_previous and existing_state == SubmissionState.TURNED_IN.value:
        return {
            "success": True,
            "assignment_id": assignment_id,
            "course_id": course.id,
            "course_name": course.name,
            "submission_id": existing_sub.id,
            "google_doc_id": existing_sub.google_doc_id,
            "google_doc_url": f"https://docs.google.com/document/d/{existing_sub.google_doc_id}/edit" if existing_sub.google_doc_id else None,
            "zip_file_id": existing_sub.google_drive_file_id,
            "classroom_submission_id": existing_sub.classroom_attachment_id,
            "turned_in": True,
            "message": "This exact Claude draft has already been turned in to Google Classroom.",
        }

    student_doc_id = (
        existing_sub.google_doc_id
        if existing_sub and existing_sub.google_doc_id and (same_content_as_previous or pending_export_doc)
        else None
    )

    # 1. Ensure Google Doc exists for this submission
    if not student_doc_id:
        doc_info = export_solution_to_google_doc(db, assignment, raw_content, user_id=user_id)
        # export_solution_to_google_doc's public contract uses `doc_id` (and
        # `drive_file_id`); older callers/mocks may provide `google_doc_id`.
        # Accept both so a successfully created Doc is not reported as a failure.
        exported_doc_id = (
            (doc_info or {}).get("google_doc_id")
            or (doc_info or {}).get("doc_id")
            or (doc_info or {}).get("drive_file_id")
        )
        if not exported_doc_id:
            raise HTTPException(status_code=502, detail="Failed to create Google Doc for assignment solution")
        student_doc_id = exported_doc_id

    # 2. Package deliverables into a single ZIP archive
    deliverables = extract_assignment_deliverables(clean_content)
    files = deliverables.get("files", [])

    profile_row = db.query(Setting).filter(Setting.key == f"clerk_user_{user_id}").first()
    profile = {}
    if profile_row and profile_row.value:
        try:
            profile = json.loads(profile_row.value)
        except Exception:
            profile = {}
    student_name = " ".join(part for part in (profile.get("first_name"), profile.get("last_name")) if part).strip() or "Student"
    reg_id = profile.get("reg_id") or profile.get("roll_no") or profile.get("student_id") or ""

    safe_title = re.sub(r'[^a-zA-Z0-9_\-]', '_', assignment.title or "Assignment").strip('_')
    safe_student = re.sub(r'[^a-zA-Z0-9_\-]', '_', student_name).strip('_')
    reg_part = f"_{re.sub(r'[^a-zA-Z0-9_\-]', '_', reg_id).strip('_')}" if reg_id else ""
    zip_filename = f"{safe_student}_{safe_title}{reg_part}_Deliverables.zip"

    # Reuse the exact Drive pair for an unchanged draft when a previous attempt
    # stopped after file creation (for example, a Classroom API permission error).
    if reusable_drive_pair:
        zip_file_id = existing_sub.google_drive_file_id
    else:
        archive = BytesIO()
        with zipfile.ZipFile(archive, mode="w", compression=zipfile.ZIP_DEFLATED) as bundle:
            if files:
                for source_file in files:
                    fname = source_file.get("name") or f"task_{source_file.get('task', 1)}_solution.py"
                    bundle.writestr(fname, source_file.get("content", ""))
            else:
                bundle.writestr(f"{safe_title}_Solution.txt", clean_content)

            execution_results = extract_execution_metadata(raw_content) if raw_content else []
            append_downloaded_assets_to_zip(bundle, execution_results, solution_markdown=clean_content, files=files)
            for index, output in enumerate(execution_results or deliverables.get("terminal_outputs", [])):
                filename = output.get("filename") or f"task_{output.get('task', index + 1)}"
                is_unverified = output.get("verified") is False
                output_prefix = "claude_reported_output" if is_unverified else "terminal_output"
                text = output.get("terminal_output") or output.get("content") or "No terminal output was produced."
                bundle.writestr(f"{output_prefix}_{filename}.txt", text + "\n")

        zip_bytes = archive.getvalue()

        # 3. Upload ZIP to Google Drive
        uploaded_zip = docs_service.upload_file(name=zip_filename, content=zip_bytes, mime_type="application/zip")
        if not uploaded_zip or not uploaded_zip.get("id"):
            raise HTTPException(status_code=502, detail="Failed to upload deliverables ZIP to Google Drive")
        zip_file_id = uploaded_zip["id"]

    for drive_id in (student_doc_id, zip_file_id):
        if not docs_service.remove_public_sharing(drive_id):
            raise HTTPException(status_code=502, detail="Could not verify private sharing for a submission file; nothing was submitted.")

    # Save generated Drive IDs before Classroom attachment. This makes retries
    # idempotent and prevents a failed attachment from creating more orphan ZIPs.
    if not existing_sub:
        existing_sub = Submission(assignment_id=assignment_id, user_id=user_id)
        db.add(existing_sub)
    existing_sub.google_doc_id = student_doc_id
    existing_sub.google_drive_file_id = zip_file_id
    existing_sub.submission_state = SubmissionState.CREATED
    if not digest_row:
        digest_row = Setting(key=digest_key, description="Digest of last Claude draft submitted to Classroom")
        db.add(digest_row)
    digest_row.value = content_digest
    db.commit()
    db.refresh(existing_sub)

    # 4. Attach both Google Doc and ZIP file to Classroom submission.
    get_file_metadata = getattr(docs_service, "get_file", None)
    doc_metadata = get_file_metadata(student_doc_id) if callable(get_file_metadata) else None
    doc_metadata = doc_metadata or {}
    google_doc_name = doc_metadata.get("name") or f"{student_name}_{safe_title}{reg_part}"
    target_assignment_url = _resolve_student_assignment_url(assignment, course, service.service)

    try:
        submission_id, sub_state = _attach_submission_files(
            service.service,
            course.external_id,
            assignment.external_id,
            [student_doc_id, zip_file_id],
            return_state=True,
        )
    except HTTPException as attach_error:
        logger.error("Classroom attach files error for assignment %s: %s", assignment_id, attach_error)
        raise

    # If action is 'attach_only', keep files attached as draft and DO NOT call turnIn
    if action == "attach_only":
        if not existing_sub:
            existing_sub = Submission(assignment_id=assignment_id, user_id=user_id)
            db.add(existing_sub)

        existing_sub.google_doc_id = student_doc_id
        existing_sub.google_drive_file_id = zip_file_id
        existing_sub.classroom_attachment_id = submission_id
        existing_sub.submission_state = SubmissionState.CREATED
        existing_sub.approved_by_user = True
        existing_sub.approved_at = datetime.now(timezone.utc)
        if not digest_row:
            digest_row = Setting(key=digest_key, description="Digest of last Claude draft submitted to Classroom")
            db.add(digest_row)
        digest_row.value = content_digest
        assignment.submission_state = SubmissionState.CREATED
        assignment.status = AssignmentStatus.APPROVED
        db.commit()
        db.refresh(existing_sub)

        return {
            "success": True,
            "assignment_id": assignment_id,
            "course_id": course.id,
            "course_name": course.name,
            "submission_id": existing_sub.id,
            "google_doc_id": student_doc_id,
            "google_doc_url": f"https://docs.google.com/document/d/{student_doc_id}/edit",
            "zip_file_id": zip_file_id,
            "zip_filename": zip_filename,
            "classroom_submission_id": submission_id,
            "classroom_url": target_assignment_url,
            "action_taken": "attached_draft",
            "turned_in": False,
            "message": f"Deliverables ({zip_filename} & Google Doc) successfully attached to Google Classroom coursework as a draft. You can review or turn in anytime!",
        }

    # Action is 'turn_in'
    turned_in = False
    turn_in_note = ""
    extension_required = False

    if sub_state != "TURNED_IN":
        try:
            service.service.courses().courseWork().studentSubmissions().turnIn(
                courseId=course.external_id,
                courseWorkId=assignment.external_id,
                id=submission_id,
                body={},
            ).execute()
            turned_in = True
        except Exception as error:
            err_str = str(error)
            logger.warning(f"Classroom turnIn on {submission_id}: {error}")
            turned_in = False
            if "already been submitted" in err_str.lower():
                turned_in = True
                turn_in_note = " (Submission was already submitted on Google Classroom)."
            elif "closed" in err_str.lower() or "deadline" in err_str.lower() or "not open" in err_str.lower():
                turn_in_note = " (Submission deadline has passed or submissions are closed on Google Classroom; deliverables have been safely attached to coursework)."
            else:
                # Google restricted 3rd-party API turnIn for students -> Hand off to Companion Extension!
                extension_required = True
                turn_in_note = " (Deliverables attached. 1-click turn in ready via your Chrome extension)."
    else:
        turn_in_note = " (Submission was already marked turned in on Google Classroom; deliverables were updated)."

    # Update database records
    if not existing_sub:
        existing_sub = Submission(assignment_id=assignment_id, user_id=user_id)
        db.add(existing_sub)

    existing_sub.google_doc_id = student_doc_id
    existing_sub.google_drive_file_id = zip_file_id
    existing_sub.classroom_attachment_id = submission_id
    existing_sub.submitted_at = datetime.now(timezone.utc)
    submission_is_turned_in = turned_in or sub_state == "TURNED_IN"
    existing_sub.submission_state = SubmissionState.TURNED_IN if submission_is_turned_in else SubmissionState.CREATED
    existing_sub.approved_by_user = True
    existing_sub.approved_at = datetime.now(timezone.utc)
    if not digest_row:
        digest_row = Setting(key=digest_key, description="Digest of last Claude draft submitted to Classroom")
        db.add(digest_row)
    digest_row.value = content_digest

    assignment.submission_state = SubmissionState.TURNED_IN if submission_is_turned_in else SubmissionState.CREATED
    assignment.status = AssignmentStatus.SUBMITTED if submission_is_turned_in else AssignmentStatus.APPROVED
    db.commit()
    db.refresh(existing_sub)

    if turned_in:
        success_msg = f"Successfully turned in Google Doc and {zip_filename} to Google Classroom!"
    else:
        success_msg = f"Deliverables ({zip_filename} & Google Doc) successfully added to Google Classroom!{turn_in_note}"

    res = {
        "success": True,
        "assignment_id": assignment_id,
        "course_id": course.id,
        "course_name": course.name,
        "submission_id": existing_sub.id,
        "google_doc_id": student_doc_id,
        "google_doc_url": f"https://docs.google.com/document/d/{student_doc_id}/edit",
        "zip_file_id": zip_file_id,
        "zip_filename": zip_filename,
        "classroom_submission_id": submission_id,
        "classroom_url": target_assignment_url,
        "turned_in": turned_in,
        "message": success_msg,
    }
    if extension_required:
        res["action_required"] = "extension_turn_in"
    return res


def check_and_execute_course_auto_turn_in(db: Session, course_id: int, user_id: str) -> List[dict]:
    """
    Check if auto-turn-in is enabled strictly for THIS COURSE.
    If enabled, auto-turns in assignments/labs belonging only to this course
    if current time is within minutes_before (default 60 minutes) to deadline.
    """
    setting_key = f"auto_turnin_course_{user_id}_{course_id}"
    setting = db.query(Setting).filter(Setting.key == setting_key).first()
    if not setting or not setting.value:
        return []

    try:
        val = json.loads(setting.value)
        enabled = bool(val.get("enabled", False))
        minutes_before = int(val.get("minutes_before", 60))
    except Exception:
        enabled = setting.value.lower() == "true"
        minutes_before = 60

    if not enabled:
        return []

    now = datetime.now(timezone.utc)
    # Strictly query assignments belonging ONLY to this course
    course_assignments = db.query(Assignment).filter(
        Assignment.course_id == course_id,
        Assignment.user_id == user_id,
        Assignment.due_at.isnot(None),
    ).all()

    turned_in_results = []
    for asgn in course_assignments:
        sub_state = getattr(asgn.submission_state, "value", asgn.submission_state)
        if sub_state in {"TURNED_IN", "RETURNED"}:
            continue

        due_at = asgn.due_at
        if not due_at.tzinfo:
            due_at = due_at.replace(tzinfo=timezone.utc)

        time_to_deadline_mins = (due_at - now).total_seconds() / 60.0
        # Never auto-submit after the deadline; scan cadence can miss narrow windows.
        if 0.0 <= time_to_deadline_mins <= float(max(5, min(minutes_before, 1440))):
            prior_submission = db.query(Submission).filter(Submission.assignment_id == asgn.id).first()
            prior_state = (
                getattr(prior_submission.submission_state, "value", prior_submission.submission_state)
                if prior_submission else None
            )
            if prior_submission and prior_state in {SubmissionState.TURNED_IN.value, SubmissionState.RETURNED.value}:
                continue
            # CREATED means files may have been attached while Classroom rejected
            # turn-in. Let the scheduled flow retry within its configured window;
            # execute_quick_turn_in reuses the existing private files by digest.
            sol = db.query(AssignmentSolution).filter(AssignmentSolution.assignment_id == asgn.id).first()
            if sol and (sol.validated_content or sol.draft_content):
                try:
                    res = execute_quick_turn_in(db, asgn.id, user_id)
                    turned_in_results.append(res)
                    logger.info(f"Auto turned in assignment {asgn.id} for course {course_id}: {res}")
                except Exception as auto_err:
                    logger.error(f"Auto turn in error for assignment {asgn.id} in course {course_id}: {auto_err}")

    return turned_in_results


class QuickTurnInPayload(BaseModel):
    confirm_submission: bool = False
    action: Optional[str] = "turn_in"  # "turn_in" or "attach_only"


class CourseAutoTurnInPayload(BaseModel):
    enabled: bool = True
    submit_when_ready: bool = False   # Auto Turn In
    attach_when_ready: bool = False   # Auto Attach Only (Keep as Draft)
    minutes_before: int = Field(default=60, ge=5, le=1440)
    confirm_submission: bool = False


class CourseAutoTurnInCheckPayload(BaseModel):
    confirm_submission: bool = False


def auto_turn_in_completed_solution(db: Session, assignment_id: int, user_id: str) -> Optional[dict]:
    """Submit or attach a completed solution immediately only when student explicitly allowed it on dashboard."""
    assignment = db.query(Assignment).filter(
        Assignment.id == assignment_id,
        Assignment.user_id == user_id,
    ).first()
    if not assignment:
        return None

    setting = db.query(Setting).filter(
        Setting.key == f"auto_turnin_course_{user_id}_{assignment.course_id}"
    ).first()
    try:
        preferences = json.loads(setting.value or "{}") if setting else {}
    except (TypeError, json.JSONDecodeError):
        preferences = {}

    submit_when_ready = bool(preferences.get("submit_when_ready", False))
    attach_when_ready = bool(preferences.get("attach_when_ready", False))

    if not submit_when_ready and not attach_when_ready:
        return None

    solution = db.query(AssignmentSolution).filter(
        AssignmentSolution.assignment_id == assignment_id
    ).first()
    if not solution:
        return None
    if submit_when_ready and not solution.validated_content:
        return None
    if not (solution.validated_content or solution.draft_content):
        return None

    existing_submission = db.query(Submission).filter(
        Submission.assignment_id == assignment_id
    ).first()
    submission_state = (
        getattr(existing_submission.submission_state, "value", existing_submission.submission_state)
        if existing_submission else None
    )
    if submission_state in {SubmissionState.TURNED_IN.value, SubmissionState.RETURNED.value}:
        return None

    action = "turn_in" if submit_when_ready else "attach_only"
    return execute_quick_turn_in(db, assignment_id, user_id, action=action)


@router.post("/assignments/{assignment_id}/quick-turn-in", response_model=dict)
def quick_turn_in_assignment(
    assignment_id: int,
    payload: QuickTurnInPayload,
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional),
):
    """
    Immediate Quick Turn In / Deliverables Attachment:
    Uploads Google Doc + auto-zipped deliverables archive directly to Google Classroom.
    Supports action='attach_only' (draft) and action='turn_in' (turn in via API/extension).
    """
    if payload.confirm_submission is not True:
        raise HTTPException(status_code=400, detail="Explicit confirmation is required before submitting to Google Classroom.")
    user_id = _classroom_user_id(clerk_user)
    action = payload.action or "turn_in"
    return execute_quick_turn_in(db, assignment_id, user_id, action=action)


@router.post("/assignments/{assignment_id}/confirm-turn-in", response_model=dict)
def confirm_assignment_turn_in(
    assignment_id: int,
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional),
):
    """Record confirmation when extension successfully triggers the native turn-in on classroom.google.com."""
    user_id = _classroom_user_id(clerk_user)
    assignment = _get_owned_assignment(db, assignment_id, user_id)
    submission = db.query(Submission).filter(
        Submission.assignment_id == assignment_id,
        Submission.user_id == user_id,
    ).first()
    if not submission:
        submission = Submission(assignment_id=assignment_id, user_id=user_id)
        db.add(submission)

    submission.submission_state = SubmissionState.TURNED_IN
    submission.submitted_at = datetime.now(timezone.utc)
    submission.approved_by_user = True
    submission.approved_at = datetime.now(timezone.utc)
    assignment.submission_state = SubmissionState.TURNED_IN
    assignment.status = AssignmentStatus.SUBMITTED
    db.commit()
    return {"success": True, "assignment_id": assignment_id, "status": "SUBMITTED", "submission_state": "TURNED_IN"}


@router.post("/assignments/{assignment_id}/solution/email", response_model=dict)
def email_solution_manually(
    assignment_id: int,
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional),
):
    """Manually send/resend the generated solution and attached files to the user's selected email."""
    user_id = _classroom_user_id(clerk_user)
    from app.services.email import send_solution_delivery_email
    from app.services.alert_service import get_user_recipient_email

    recipient = get_user_recipient_email(db, user_id)
    if not recipient:
        raise HTTPException(status_code=400, detail="No verified recipient email found in your profile or settings.")

    sent = send_solution_delivery_email(db, assignment_id, user_id)
    if not sent:
        raise HTTPException(status_code=500, detail="Failed to send solution email. Ensure a solution has been generated.")

    return {"success": True, "recipient": recipient, "message": f"Solution and deliverables emailed to {recipient}!"}


@router.get("/courses/{course_id}/auto-turn-in", response_model=dict)
def get_course_auto_turn_in(
    course_id: int,
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional),
):
    """Retrieve auto turn-in status strictly for this course."""
    user_id = _classroom_user_id(clerk_user)
    course = db.query(Course).filter(Course.id == course_id, Course.user_id == user_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    setting_key = f"auto_turnin_course_{user_id}_{course_id}"
    setting = db.query(Setting).filter(Setting.key == setting_key).first()
    enabled = False
    minutes_before = 60
    submit_when_ready = False
    attach_when_ready = False
    if setting and setting.value:
        try:
            val = json.loads(setting.value)
            enabled = bool(val.get("enabled", False))
            minutes_before = int(val.get("minutes_before", 60))
            submit_when_ready = bool(val.get("submit_when_ready", False))
            attach_when_ready = bool(val.get("attach_when_ready", False))
        except Exception:
            enabled = setting.value.lower() == "true"

    latest_submission = (
        db.query(Submission)
        .join(Assignment, Submission.assignment_id == Assignment.id)
        .filter(
            Submission.user_id == user_id,
            Assignment.user_id == user_id,
            Assignment.course_id == course_id,
        )
        .order_by(Submission.submitted_at.desc().nullslast(), Submission.created_at.desc())
        .first()
    )
    next_check = datetime.now(timezone.utc) + timedelta(minutes=1) if enabled else None

    return {
        "course_id": course_id,
        "course_name": course.name,
        "enabled": enabled,
        "minutes_before": minutes_before,
        "submit_when_ready": submit_when_ready,
        "attach_when_ready": attach_when_ready,
        "last_run": (latest_submission.submitted_at or latest_submission.created_at) if latest_submission else None,
        "last_result": {
            "status": getattr(latest_submission.submission_state, "value", latest_submission.submission_state),
            "assignment_id": latest_submission.assignment_id,
        } if latest_submission else None,
        "next_run": next_check,
    }


@router.put("/courses/{course_id}/auto-turn-in", response_model=dict)
def update_course_auto_turn_in(
    course_id: int,
    payload: CourseAutoTurnInPayload,
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional),
):
    """
    Enable or disable auto turn-in or auto attachment strictly for this specific course.
    Automatically turns in before configured minutes to deadline or when ready.
    """
    user_id = _classroom_user_id(clerk_user)
    if (payload.enabled or payload.submit_when_ready or payload.attach_when_ready) and payload.confirm_submission is not True:
        raise HTTPException(status_code=400, detail="Confirm that you want Claude-generated deliverables submitted or attached automatically for this course.")
    course = db.query(Course).filter(Course.id == course_id, Course.user_id == user_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    setting_key = f"auto_turnin_course_{user_id}_{course_id}"
    setting = db.query(Setting).filter(Setting.key == setting_key).first()
    setting_val = {
        "enabled": payload.enabled,
        "submit_when_ready": payload.submit_when_ready,
        "attach_when_ready": payload.attach_when_ready,
        "minutes_before": payload.minutes_before,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "course_id": course_id,
        "course_name": course.name,
    }
    if not setting:
        setting = Setting(
            key=setting_key,
            value=json.dumps(setting_val),
            description=f"Auto turn-in setting strictly for course {course.name} ({course_id})"
        )
        db.add(setting)
    else:
        setting.value = json.dumps(setting_val)
    db.commit()

    # Enabling is prospective; saving preferences must never trigger an immediate submission.
    turned_in = []

    return {
        "course_id": course_id,
        "course_name": course.name,
        "enabled": payload.enabled,
        "submit_when_ready": payload.submit_when_ready,
        "minutes_before": payload.minutes_before,
        "turned_in": turned_in,
        "next_run": datetime.now(timezone.utc) + timedelta(minutes=1) if payload.enabled else None,
        "message": f"Auto turn-in for {course.name} {'enabled ' + str(payload.minutes_before) + ' minutes before the deadline' if payload.enabled else 'disabled'}"
    }


@router.post("/courses/{course_id}/check-auto-turn-in", response_model=dict)
def trigger_course_auto_turn_in_check(
    course_id: int,
    payload: CourseAutoTurnInCheckPayload,
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional),
):
    """Manually evaluate auto turn-in for this specific course."""
    if payload.confirm_submission is not True:
        raise HTTPException(status_code=400, detail="Confirm that you want eligible Claude drafts submitted for this course now.")
    user_id = _classroom_user_id(clerk_user)
    turned_in = check_and_execute_course_auto_turn_in(db, course_id, user_id)
    return {
        "course_id": course_id,
        "turned_in_count": len(turned_in),
        "results": turned_in
    }


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
    create_google_doc: Optional[bool] = True


@router.post("/assignments/{assignment_id}/solution/generate", response_model=dict)
def generate_assignment_solution(
    assignment_id: int,
    payload: Optional[GenerateSolutionRequest] = None,
    background_tasks: BackgroundTasks = None,
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional),
):
    """Trigger the Claude browser assignment solver (async with background tasks)."""
    from app.db.models import AssignmentSolution, AssignmentStatus

    req = payload or GenerateSolutionRequest()
    provider = "claude_browser"
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
    stale_before = datetime.now(timezone.utc) - timedelta(minutes=20)
    latest_start = db.query(AssignmentSolution.generated_at).filter(
        AssignmentSolution.assignment_id == assignment_id,
    ).scalar_subquery()
    claimed = db.query(Assignment).filter(
        Assignment.id == assignment_id,
        Assignment.user_id == user_id,
        or_(
            Assignment.status != AssignmentStatus.GENERATING,
            latest_start.is_(None),
            latest_start < stale_before,
        ),
    ).update({Assignment.status: AssignmentStatus.GENERATING}, synchronize_session=False)
    if claimed != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="A solution is already being generated for this assignment.")
    if not solution:
        solution = AssignmentSolution(assignment_id=assignment_id, user_id=user_id)
        db.add(solution)

    solution.ai_provider = provider
    solution.retry_count = (solution.retry_count or 0) + 1
    solution.validation_errors = None
    # Preserve existing solution.draft_content and solution.validated_content
    # so user can utilize the latest generated response and run quick-turn-in even during a retry!
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
                    create_google_doc=create_google_doc,
                )
                logger.info(f"Claude Browser solution generated for assignment {assignment_id}: status={result.get('status')}")
                if result.get("status") == "already_running":
                    logger.info("Claude solve %s is already active; preserving its generating state.", assignment_id)
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
                elif result.get("status") != "completed":
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
                elif result.get("status") == "completed":
                    # 1. Immediately deliver solution and files to student's email
                    try:
                        from app.services.email import send_solution_delivery_email
                        send_solution_delivery_email(sync_db, assignment_id, user_id)
                    except Exception as mail_err:
                        logger.warning("Could not dispatch auto-solution email for assignment %s: %s", assignment_id, mail_err)

                    # 2. Check if student opted in to auto-submission/attachment on dashboard
                    try:
                        submission_result = auto_turn_in_completed_solution(sync_db, assignment_id, user_id)
                        if submission_result and submission_result.get("success"):
                            logger.info("Auto submission/attachment completed for assignment %s: %s", assignment_id, submission_result)
                    except Exception:
                        logger.exception("Auto turn-in after solution generation failed for assignment %s", assignment_id)
            else:
                raise RuntimeError("Unsupported assignment solver")
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


@router.post("/gcr-browser/open", response_model=dict)
def open_google_classroom_browser(clerk_user: Optional[dict] = Depends(get_current_user_optional)):
    """Classroom automation is handled natively via Unpacked Extension; server browser retired."""
    return {
        "success": True,
        "extension_managed": True,
        "message": "Google Classroom is managed via your Uniflow Companion Extension in your authenticated Chrome browser.",
    }


@router.get("/gcr-browser/status", response_model=dict)
def get_google_classroom_browser_status(
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional),
):
    """Return this user's Google Classroom companion extension readiness status."""
    user_id = _classroom_user_id(clerk_user)
    cookie_setting = db.query(Setting).filter(
        Setting.key == f"classroom:{user_id}:google_session_cookies"
    ).first()
    has_synced_session = bool(cookie_setting and cookie_setting.value)
    return {
        "active": False,
        "profile_exists": has_synced_session,
        "viewer_url": None,
        "has_synced_session": has_synced_session,
        "extension_managed": True,
    }


@router.delete("/gcr-browser/profile", response_model=dict)
def delete_google_classroom_browser_profile(
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional),
):
    """Delete this user's saved Google Classroom session cookies."""
    user_id = _classroom_user_id(clerk_user)
    cookie_setting = db.query(Setting).filter(
        Setting.key == f"classroom:{user_id}:google_session_cookies"
    ).first()
    if cookie_setting:
        db.delete(cookie_setting)
        db.commit()
    return {"profile_deleted": True}


class GoogleClassroomCookieSyncRequest(BaseModel):
    cookies: Union[List[Dict[str, Any]], str]
    user_agent: Optional[str] = None


@router.post("/gcr-browser/sync-session", response_model=dict)
def sync_google_classroom_session(
    payload: GoogleClassroomCookieSyncRequest,
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional),
):
    """Sync the student's existing Google Classroom session cookies from the extension or settings."""
    user_id = _classroom_user_id(clerk_user)
    raw_cookies = payload.cookies
    cookie_list = []
    if isinstance(raw_cookies, str):
        # Allow cookie string format "name=val; name2=val2"
        for part in raw_cookies.split(";"):
            part = part.strip()
            if "=" in part:
                name, val = part.split("=", 1)
                cookie_list.append({
                    "name": name.strip(),
                    "value": val.strip(),
                    "domain": ".google.com",
                    "path": "/",
                    "secure": True,
                })
    elif isinstance(raw_cookies, list):
        cookie_list = [dict(c) for c in raw_cookies if isinstance(c, dict) and c.get("name") and c.get("value")]

    if not cookie_list:
        raise HTTPException(
            status_code=400,
            detail="No valid cookies provided. Ensure you are signed in to Google Classroom.",
        )

    # Check that at least one Google auth cookie is present
    auth_cookie_names = {"OSID", "SID", "HSID", "SSID", "APISID", "SAPISID", "__Secure-1PSID", "__Secure-3PSID"}
    has_auth_cookie = any(c.get("name") in auth_cookie_names or c.get("name", "").startswith("__Secure-") for c in cookie_list)
    if not has_auth_cookie:
        raise HTTPException(
            status_code=400,
            detail="Provided cookies do not include Google Classroom authentication tokens (e.g. OSID, SID). Log into classroom.google.com first.",
        )

    json_str = json.dumps(cookie_list)
    encrypted_cookies = encrypt_token_if_needed(json_str)

    key_setting = db.query(Setting).filter(
        Setting.key == f"classroom:{user_id}:google_session_cookies"
    ).first()
    if not key_setting:
        key_setting = Setting(
            key=f"classroom:{user_id}:google_session_cookies",
            description="User's Google Classroom session cookies for automated background turn-in.",
        )
        db.add(key_setting)
    key_setting.value = encrypted_cookies

    if payload.user_agent:
        ua_setting = db.query(Setting).filter(
            Setting.key == f"classroom:{user_id}:google_user_agent"
        ).first()
        if not ua_setting:
            ua_setting = Setting(
                key=f"classroom:{user_id}:google_user_agent",
                description="User's browser User-Agent for Google Classroom session alignment.",
            )
            db.add(ua_setting)
        ua_setting.value = payload.user_agent.strip()

    db.commit()
    logger.info("Synced %d Google Classroom cookies for user %s", len(cookie_list), user_id)
    return {
        "status": "connected",
        "has_synced_session": True,
        "cookie_count": len(cookie_list),
        "message": f"Successfully connected {len(cookie_list)} Google Classroom session cookies! Assignments can now be turned in automatically in the background.",
    }


@router.delete("/gcr-browser/session", response_model=dict)
def disconnect_google_classroom_session(
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional),
):
    """Disconnect the student's synced Google Classroom session cookies."""
    user_id = _classroom_user_id(clerk_user)
    db.query(Setting).filter(
        Setting.key.in_([
            f"classroom:{user_id}:google_session_cookies",
            f"classroom:{user_id}:google_user_agent",
        ])
    ).delete(synchronize_session=False)
    db.commit()
    return {"status": "disconnected", "has_synced_session": False}


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
    key_setting.value = encrypt_token_if_needed(raw_key)

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
    assignment = _get_owned_assignment(db, assignment_id, _classroom_user_id(clerk_user))
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
            is_diagram = result.get("language") in ("mermaid", "diagram", "drawio", "drawio.xml", "plantuml", "graphviz", "dot", "mmd", "puml", "xml", "mxfile", "svg")
            if not data_uri and is_diagram:
                image_asset = next((asset for asset in result.get("downloaded_assets", []) if asset.get("is_image") and asset.get("data_uri")), None)
                data_uri = image_asset.get("data_uri") if image_asset else None
            is_file_attachment = result.get("language") == "artifact"
            if not data_uri and not is_diagram and not is_file_attachment and result.get("verified") is not False and result.get("tool") != "Claude Text Output (no image artifact)":
                png = TerminalCardRenderer.generate_terminal_png(
                    result.get("command") or f"Run {result.get('filename') or 'solution file'}",
                    result.get("terminal_output") or "No terminal output was produced.",
                    title=f"Assignment run — {result.get('filename') or 'solution'}",
                )
                data_uri = f"data:image/png;base64,{base64.b64encode(png).decode('ascii')}"
            if not data_uri:
                continue
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

    has_content = bool(solution.validated_content or solution.draft_content)
    is_generating = bool(assignment and assignment.status == AssignmentStatus.GENERATING)
    is_completed = bool(solution.validated_content) and not is_generating
    is_failed = bool(solution.validation_errors) and not has_content and not is_generating

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
        "status": "generating" if is_generating else ("completed" if is_completed else ("failed" if is_failed else "not_started")),
        "has_content": has_content,
        "is_re_solving": is_generating and has_content,
        "draft_content": strip_execution_metadata(solution.draft_content or ""),
        "validated_content": strip_execution_metadata(solution.validated_content or ""),
        "tasks": enriched_tasks,
        "generated_files": code_files,
        "terminal_outputs": execution_results,
        "terminal_screenshots": terminal_screenshots,
        "generated_images": collected_images,
        "crew_progress": crew_progress,
        "code_files_download_url": f"/api/v1/classroom/assignments/{assignment_id}/solution/files" if deliverables["files"] or any(result.get("downloaded_assets") for result in execution_results) else None,
        "validation_errors": cleaned_validation_errors,
        "claude_rate_limit": claude_rate_limit,
        "retry_count": solution.retry_count,
        "ai_provider": solution.ai_provider,
        "generated_at": solution.generated_at,
        "validated_at": solution.validated_at,
        "verification_status": "unverified",
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
    from app.services.document_export import build_solution_zip

    _get_owned_assignment(db, assignment_id, _classroom_user_id(clerk_user))
    solution = db.query(AssignmentSolution).filter(AssignmentSolution.assignment_id == assignment_id).first()
    if not solution or not (solution.validated_content or solution.draft_content):
        raise HTTPException(status_code=404, detail="No generated solution is available.")

    raw_text = solution.validated_content or solution.draft_content or ""
    try:
        archive_bytes = build_solution_zip(assignment_id, raw_text)
    except ValueError as err:
        raise HTTPException(status_code=404, detail=str(err))

    return Response(
        content=archive_bytes,
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
    files = extract_assignment_deliverables(content).get("files", [])
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
    from app.services.document_export import build_solution_html_report

    user_id = _classroom_user_id(clerk_user)
    assignment = _get_owned_assignment(db, assignment_id, user_id)
    solution = db.query(AssignmentSolution).filter(AssignmentSolution.assignment_id == assignment_id).first()
    if not solution or not (solution.validated_content or solution.draft_content):
        raise HTTPException(status_code=404, detail="No generated solution report is available.")

    content = solution.validated_content or solution.draft_content or ""
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

    report_html = build_solution_html_report(
        assignment_title=assignment.title or "Assignment solution",
        course_name=course_name,
        instructor_name=instructor,
        student_name=student_name,
        student_id=str(profile.get("student_id") or profile.get("roll_no") or "Not provided"),
        due_at=assignment.due_at or assignment.due_date,
        raw_content=content,
        generated_images=_assignment_generated_images(db, assignment_id),
    )

    return Response(
        content=report_html,
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
    from app.services.document_export import build_solution_docx_report

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
    content = solution.validated_content or solution.draft_content or ""

    docx_bytes = build_solution_docx_report(
        assignment_title=assignment.title or "Assignment solution",
        course_name=course_name,
        instructor_name=instructor,
        student_name=student_name,
        due_at=assignment.due_at or assignment.due_date,
        raw_content=content,
        base_docx_bytes=docx_content,
        generated_images=_assignment_generated_images(db, assignment_id),
    )

    return Response(
        content=docx_bytes,
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
