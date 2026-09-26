from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime, timedelta

from app.db.database import get_db
from app.db.repositories import CourseRepository, ClassScheduleRepository
from app.db.models import Course, ClassSchedule
from app.services.classroom_sync import get_classroom_service

router = APIRouter(prefix="/classroom", tags=["Classroom"])


@router.get("/courses", response_model=List[dict])
def get_courses(db: Session = Depends(get_db)):
    repo = CourseRepository(db)
    courses = repo.get_all()
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
def get_course(course_id: int, db: Session = Depends(get_db)):
    repo = CourseRepository(db)
    course = db.query(Course).filter(Course.id == course_id).first()
    if not course:
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
    db: Session = Depends(get_db)
):
    repo = ClassScheduleRepository(db)
    schedules = repo.get_upcoming(days)
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
def get_today_schedules(db: Session = Depends(get_db)):
    repo = ClassScheduleRepository(db)
    schedules = repo.get_today()
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
def sync_classroom(background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Trigger full Google Classroom sync"""
    service = get_classroom_service(db)
    if not service:
        raise HTTPException(status_code=503, detail="Google Classroom not configured. Complete OAuth first.")

    def run_sync():
        from app.db.database import SessionLocal
        sync_db = SessionLocal()
        try:
            svc = get_classroom_service(sync_db)
            if svc:
                result = svc.sync_all()
                logger.info(f"Manual Classroom sync result: {result}")
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
                # Re-fetch course from API and sync
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
    course_count = db.query(func.count(Course.id)).scalar()
    assignment_count = db.query(func.count(Course.id)).scalar()

    # Check if credentials exist
    cred = db.query(Course).first()  # Just check if we have courses
    has_creds = db.query(Course).first() is not None  # Simplified

    return {
        "courses_in_db": course_count,
        "assignments_in_db": assignment_count,
        "google_connected": has_creds,
        "last_sync": None,  # Could add a sync_log table
    }


@router.get("/courses/{course_id}/assignments", response_model=List[dict])
def get_course_assignments(course_id: int, db: Session = Depends(get_db)):
    """Get assignments for a specific course (from local DB)"""
    from app.db.repositories import AssignmentRepository
    repo = AssignmentRepository(db)
    assignments = db.query(Assignment).filter(Assignment.course_id == course_id).order_by(Assignment.due_at.asc().nullslast()).all()
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

    students = service.get_course_students(course.external_id)
    return [
        {
            "user_id": s.get("userId"),
            "profile": s.get("profile", {}),
        }
        for s in students
    ]


@router.get("/assignments/{assignment_id}/submissions", response_model=List[dict])
def get_assignment_submissions(assignment_id: int, db: Session = Depends(get_db)):
    """Get student submissions for an assignment from Google Classroom API"""
    service = get_classroom_service(db)
    if not service:
        raise HTTPException(status_code=503, detail="Google Classroom not configured")

    assignment = db.query(Assignment).filter(Assignment.id == assignment_id).first()
    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")

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