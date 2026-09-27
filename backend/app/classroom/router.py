from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks, Body
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone
import json
from googleapiclient.errors import HttpError

from app.db.database import get_db
from app.db.repositories import CourseRepository, ClassScheduleRepository, AssignmentTemplateRepository
from app.db.models import Course, ClassSchedule, Announcement, Setting, AssignmentTemplate
from app.core.logging import logger
from app.services.classroom_sync import get_classroom_service
from app.services.google_docs import get_google_docs_service

router = APIRouter(prefix="/classroom", tags=["Classroom"])


def _get_semester_start_dt(db: Session, override: Optional[str] = None) -> Optional[datetime]:
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


@router.get("/settings", response_model=dict)
def get_classroom_settings(db: Session = Depends(get_db)):
    """Get Classroom synchronization and semester settings"""
    setting = db.query(Setting).filter(Setting.key == "semester_start_date").first()
    return {
        "semester_start_date": setting.value.strip().replace('"', '') if setting and setting.value else None
    }


@router.post("/settings", response_model=dict)
@router.put("/settings", response_model=dict)
def save_classroom_settings(payload: Dict[str, Any] = Body(...), db: Session = Depends(get_db)):
    """Save semester start date setting"""
    start_date = payload.get("semester_start_date")
    setting = db.query(Setting).filter(Setting.key == "semester_start_date").first()
    if not setting:
        setting = Setting(key="semester_start_date", description="Semester start date filter for syncing")
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
):
    query = db.query(Announcement).filter(Announcement.source.like("Google Classroom%"))
    if course_id is not None:
        query = query.filter(Announcement.course_id == course_id)
    if search:
        match = f"%{search}%"
        query = query.filter((Announcement.title.ilike(match)) | (Announcement.content.ilike(match)))

    since_dt = _get_semester_start_dt(db, since)
    if since_dt:
        query = query.filter((Announcement.published_at >= since_dt) | (Announcement.published_at.is_(None)))

    posts = query.order_by(Announcement.published_at.desc().nullslast()).all()
    course_ids = {post.course_id for post in posts if post.course_id is not None}
    courses = {course.id: course.name for course in db.query(Course).filter(Course.id.in_(course_ids)).all()} if course_ids else {}
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
    db: Session = Depends(get_db)
):
    query = db.query(Course)
    if active_only:
        query = query.filter(Course.course_state.in_(["ACTIVE", "active", ""]) | Course.course_state.is_(None))
    since_dt = _get_semester_start_dt(db, since)
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
    db: Session = Depends(get_db)
):
    repo = CourseRepository(db)
    course = db.query(Course).filter(Course.id == course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    
    since_dt = _get_semester_start_dt(db, since)
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
    db: Session = Depends(get_db)
):
    """Trigger full Google Classroom sync from semester start date onwards"""
    service = get_classroom_service(db)
    if not service:
        raise HTTPException(status_code=503, detail="Google Classroom not configured. Complete OAuth first.")

    start_date = None
    if payload and "semester_start_date" in payload:
        start_date = payload["semester_start_date"]
    elif semester_start_date:
        start_date = semester_start_date

    if start_date:
        setting = db.query(Setting).filter(Setting.key == "semester_start_date").first()
        if not setting:
            setting = Setting(key="semester_start_date", description="Semester start date filter for syncing")
            db.add(setting)
        setting.value = str(start_date).strip().replace('"', '')
        db.commit()

    run_status = db.query(Setting).filter(Setting.key == "classroom_sync_status").first()
    if not run_status:
        run_status = Setting(key="classroom_sync_status", description="Most recent Google Classroom sync run")
        db.add(run_status)
    run_status.value = json.dumps({"status": "running", "started_at": datetime.now(timezone.utc).isoformat()})
    db.commit()

    def run_sync():
        from app.db.database import SessionLocal
        sync_db = SessionLocal()
        try:
            svc = get_classroom_service(sync_db)
            if svc:
                result = svc.sync_all()
                logger.info(f"Classroom sync result: {result}")
                status = "failed" if result.get("errors") else "completed"
                run = sync_db.query(Setting).filter(Setting.key == "classroom_sync_status").first()
                if run:
                    previous = json.loads(run.value or "{}")
                    run.value = json.dumps({**previous, "status": status, "finished_at": datetime.now(timezone.utc).isoformat(), "result": result})
                    sync_db.commit()
            else:
                raise RuntimeError("Google Classroom credentials could not be loaded.")
        except Exception as error:
            run = sync_db.query(Setting).filter(Setting.key == "classroom_sync_status").first()
            if run:
                previous = json.loads(run.value or "{}")
                run.value = json.dumps({**previous, "status": "failed", "error": str(error), "finished_at": datetime.now(timezone.utc).isoformat()})
                sync_db.commit()
            logger.exception("Google Classroom sync failed")
        finally:
            sync_db.close()

    background_tasks.add_task(run_sync)
    return {"message": "Classroom sync started in background", "status": "started"}


@router.post("/sync/course/{course_external_id}", response_model=dict)
def sync_single_course(course_external_id: str, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Sync a specific course by external ID"""
    service = get_classroom_service(db)
    if not service:
        raise HTTPException(status_code=503, detail="Google Classroom not configured")

    course = db.query(Course).filter(Course.external_id == course_external_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found in local DB")

    def run_course_sync():
        from app.db.database import SessionLocal
        sync_db = SessionLocal()
        try:
            svc = get_classroom_service(sync_db)
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
def sync_status(db: Session = Depends(get_db)):
    """Get sync status and stats"""
    from sqlalchemy import func
    from app.db.models import Assignment, GoogleCredential
    course_count = db.query(func.count(Course.id)).scalar() or 0
    assignment_count = db.query(func.count(Assignment.id)).scalar() or 0

    cred = db.query(GoogleCredential).first()
    has_creds = cred is not None
    run = db.query(Setting).filter(Setting.key == "classroom_sync_status").first()
    sync_run = json.loads(run.value) if run and run.value else None

    setting = db.query(Setting).filter(Setting.key == "semester_start_date").first()
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
    db: Session = Depends(get_db)
):
    """Get assignments for a specific course (from local DB)"""
    from app.db.models import Assignment
    query = db.query(Assignment).filter(Assignment.course_id == course_id)
    
    since_dt = _get_semester_start_dt(db, since)
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
def get_course_students(course_id: int, db: Session = Depends(get_db)):
    """Get students for a course from Google Classroom API"""
    service = get_classroom_service(db)
    if not service:
        raise HTTPException(status_code=503, detail="Google Classroom not configured")

    course = db.query(Course).filter(Course.id == course_id).first()
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
    return [
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


# ===== Assignment Templates =====

@router.get("/templates", response_model=List[dict])
def get_assignment_templates(db: Session = Depends(get_db)):
    """List all assignment templates"""
    repo = AssignmentTemplateRepository(db)
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


@router.post("/templates", response_model=dict)
def create_assignment_template(
    name: str = Body(...),
    google_doc_id: str = Body(...),
    description: Optional[str] = Body(None),
    google_drive_file_id: Optional[str] = Body(None),
    mime_type: Optional[str] = Body(None),
    is_default: bool = Body(False),
    db: Session = Depends(get_db)
):
    """Create a new assignment template from a Google Doc"""
    repo = AssignmentTemplateRepository(db)
    docs_service = get_google_docs_service(db)
    
    if not docs_service:
        raise HTTPException(status_code=503, detail="Google Docs not configured")
    
    # Verify the document exists
    doc = docs_service.get_document(google_doc_id)
    if not doc:
        raise HTTPException(status_code=400, detail="Google Doc not found or not accessible")
    
    if is_default:
        # Unset any existing default
        existing_default = repo.get_default()
        if existing_default:
            existing_default.is_default = False
    
    template = repo.create({
        "name": name,
        "description": description,
        "google_doc_id": google_doc_id,
        "google_drive_file_id": google_drive_file_id,
        "mime_type": mime_type or doc.get("mimeType"),
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
def set_default_template(template_id: int, db: Session = Depends(get_db)):
    """Set a template as default"""
    repo = AssignmentTemplateRepository(db)
    template = repo.set_default(template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    return {
        "id": template.id,
        "name": template.name,
        "is_default": template.is_default,
    }


@router.delete("/templates/{template_id}", response_model=dict)
def delete_assignment_template(template_id: int, db: Session = Depends(get_db)):
    """Delete an assignment template"""
    repo = AssignmentTemplateRepository(db)
    template = repo.delete(template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    return {"deleted": True, "id": template_id}


@router.get("/templates/drive-files", response_model=List[dict])
def list_drive_docs_for_templates(
    query: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """List Google Docs from Drive for template selection"""
    docs_service = get_google_docs_service(db)
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


# ===== Student Turn-in =====

@router.post("/assignments/{assignment_id}/turn-in", response_model=dict)
def turn_in_assignment(
    assignment_id: int,
    template_id: Optional[int] = Body(None),
    drive_file_ids: Optional[List[str]] = Body(None),
    db: Session = Depends(get_db)
):
    """Student turn-in: copy template (or create blank doc), attach files, submit to Classroom"""
    from app.db.models import Assignment, Submission, SubmissionState
    from googleapiclient.errors import HttpError
    
    service = get_classroom_service(db)
    if not service:
        raise HTTPException(status_code=503, detail="Google Classroom not configured")
    
    docs_service = get_google_docs_service(db)
    if not docs_service:
        raise HTTPException(status_code=503, detail="Google Docs not configured")
    
    assignment = db.query(Assignment).filter(Assignment.id == assignment_id).first()
    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")
    
    course = db.query(Course).filter(Course.id == assignment.course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    
    # Determine template
    if template_id:
        repo = AssignmentTemplateRepository(db)
        template = repo.get_by_id(template_id)
    else:
        repo = AssignmentTemplateRepository(db)
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
    
    # Attach additional files if provided
    if drive_file_ids:
        for file_id in drive_file_ids:
            try:
                docs_service.share_file(file_id, "me", "writer")
            except HttpError:
                pass
    
    # Submit to Classroom
    try:
        submission = service.service.courses().courseWork().studentSubmissions().modifyAttachments(
            courseId=course.external_id,
            courseWorkId=assignment.external_id,
            userId="me",
            body={
                "addAttachments": [
                    {"driveFile": {"id": student_doc_id}}
                ] + ([{"driveFile": {"id": fid}} for fid in drive_file_ids] if drive_file_ids else [])
            }
        ).execute()
    except HttpError as e:
        logger.error(f"Failed to submit to Classroom: {e}")
        raise HTTPException(status_code=502, detail="Failed to submit to Google Classroom")
    
    # Update local submission record
    existing = db.query(Submission).filter(Submission.assignment_id == assignment_id).first()
    if not existing:
        existing = Submission(assignment_id=assignment_id)
        db.add(existing)
    
    existing.google_doc_id = student_doc_id
    existing.google_drive_file_id = student_doc_id
    existing.classroom_attachment_id = submission.get("id")
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
        "classroom_submission_id": submission.get("id"),
        "message": "Assignment turned in successfully"
    }


# ===== AI Solution Generation =====

@router.post("/assignments/{assignment_id}/solution/generate", response_model=dict)
def generate_assignment_solution(
    assignment_id: int,
    provider: str = Body("groq"),
    model: str = Body("openai/gpt-oss-120b"),
    background_tasks: BackgroundTasks = None,
    db: Session = Depends(get_db)
):
    """Generate AI solution for assignment (async)"""
    from app.db.models import AssignmentSolution
    
    assignment = db.query(Assignment).filter(Assignment.id == assignment_id).first()
    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")
    
    # Get or create solution record
    solution = db.query(AssignmentSolution).filter(AssignmentSolution.assignment_id == assignment_id).first()
    if not solution:
        solution = AssignmentSolution(assignment_id=assignment_id)
        db.add(solution)
    
    solution.ai_provider = provider
    solution.retry_count = 0
    solution.validation_errors = None
    db.commit()
    
    def run_generation():
        from app.db.database import SessionLocal
        from app.services.ai_solution import generate_solution
        sync_db = SessionLocal()
        try:
            result = generate_solution(sync_db, assignment_id, provider, model)
            logger.info(f"AI solution generated for assignment {assignment_id}: {result}")
        except Exception as e:
            logger.error(f"AI solution generation failed: {e}")
        finally:
            sync_db.close()
    
    if background_tasks:
        background_tasks.add_task(run_generation)
    else:
        # Run synchronously for now
        run_generation()
    
    return {
        "status": "started",
        "assignment_id": assignment_id,
        "message": "AI solution generation started"
    }


@router.get("/assignments/{assignment_id}/solution/status", response_model=dict)
def get_solution_status(assignment_id: int, db: Session = Depends(get_db)):
    """Get AI solution generation status"""
    from app.db.models import AssignmentSolution
    solution = db.query(AssignmentSolution).filter(AssignmentSolution.assignment_id == assignment_id).first()
    if not solution:
        return {"status": "not_started"}
    return {
        "status": "completed" if solution.validated_content else "generating" if solution.draft_content else "not_started",
        "draft_content": solution.draft_content,
        "validated_content": solution.validated_content,
        "validation_errors": solution.validation_errors,
        "retry_count": solution.retry_count,
        "ai_provider": solution.ai_provider,
        "generated_at": solution.generated_at,
        "validated_at": solution.validated_at,
    }


@router.get("/assignments/{assignment_id}/submissions", response_model=List[dict])
def get_assignment_submissions(
    assignment_id: int,
    since: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """Get student submissions for an assignment from Google Classroom API"""
    service = get_classroom_service(db)
    if not service:
        raise HTTPException(status_code=503, detail="Google Classroom not configured")

    assignment = db.query(Assignment).filter(Assignment.id == assignment_id).first()
    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")

    since_dt = _get_semester_start_dt(db, since)
    if since_dt:
        # Check if assignment is within semester range
        assignment_due = assignment.due_at or assignment.due_date
        assignment_created = assignment.created_at
        if assignment_due and assignment_due < since_dt:
            if not (assignment_created and assignment_created >= since_dt):
                return []
    
    course = db.query(Course).filter(Course.id == assignment.course_id).first()
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
