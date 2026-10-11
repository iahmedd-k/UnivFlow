from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from app.db.database import get_db
from app.db.repositories import AttendanceRecordRepository
from app.db.models import AttendanceRecord, Course
from app.services.alert_service import calculate_attendance_recovery, calculate_safe_bunks

router = APIRouter(prefix="/attendance", tags=["Attendance"])


def _format_record(r: AttendanceRecord, course_name: str | None) -> dict:
    pct = r.percentage
    attended = r.attended
    total = r.total
    has_counts = total is not None and total > 0 and attended is not None and 0 <= attended <= total
    
    recovery_needed = 0
    safe_bunks = 0
    if has_counts and pct is not None:
        if pct < 75.0:
            recovery_needed = calculate_attendance_recovery(attended, total, threshold=75.0)
        else:
            safe_bunks = calculate_safe_bunks(attended, total, threshold=75.0)

    return {
        "id": r.id,
        "external_id": r.external_id,
        "course_id": r.course_id,
        "course_name": course_name,
        "subject": r.subject,
        "attended": attended,
        "total": total,
        "percentage": pct,
        "recovery_needed": recovery_needed,
        "safe_bunks": safe_bunks,
        "last_updated": r.last_updated,
        "created_at": r.created_at,
    }


@router.get("", response_model=List[dict])
def get_attendance_records(db: Session = Depends(get_db)):
    repo = AttendanceRecordRepository(db)
    records = repo.get_all()
    result = []
    for r in records:
        course = db.query(Course).filter(Course.id == r.course_id).first()
        result.append(_format_record(r, course.name if course else None))
    return result


@router.get("/{record_id}", response_model=dict)
def get_attendance_record(record_id: int, db: Session = Depends(get_db)):
    record = db.query(AttendanceRecord).filter(AttendanceRecord.id == record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Attendance record not found")
    course = db.query(Course).filter(Course.id == record.course_id).first()
    return _format_record(record, course.name if course else None)


@router.get("/course/{course_id}", response_model=dict)
def get_attendance_by_course(course_id: int, db: Session = Depends(get_db)):
    repo = AttendanceRecordRepository(db)
    record = repo.get_by_course(course_id)
    if not record:
        raise HTTPException(status_code=404, detail="Attendance record not found for this course")
    course = db.query(Course).filter(Course.id == course_id).first()
    return _format_record(record, course.name if course else None)