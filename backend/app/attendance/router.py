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


from typing import List, Optional
from datetime import datetime, timezone
import hashlib
from pydantic import BaseModel, Field
from app.core.redis import invalidate_attendance_summary_cache


class AttendanceRecordInput(BaseModel):
    course_id: int
    subject: str = Field(min_length=1, max_length=255)
    attended: int = Field(ge=0)
    total: int = Field(ge=0)


class AttendanceRecordUpdate(BaseModel):
    attended: Optional[int] = Field(default=None, ge=0)
    total: Optional[int] = Field(default=None, ge=0)
    subject: Optional[str] = Field(default=None, max_length=255)


@router.get("/course/{course_id}", response_model=dict)
def get_attendance_by_course(course_id: int, db: Session = Depends(get_db)):
    repo = AttendanceRecordRepository(db)
    record = repo.get_by_course(course_id)
    if not record:
        raise HTTPException(status_code=404, detail="Attendance record not found for this course")
    course = db.query(Course).filter(Course.id == course_id).first()
    return _format_record(record, course.name if course else None)


@router.post("", response_model=dict)
def create_attendance_record(item: AttendanceRecordInput, db: Session = Depends(get_db)):
    """Create a new attendance record (CRUD Create)"""
    if item.attended > item.total:
        raise HTTPException(status_code=422, detail="Attended classes cannot exceed total classes.")
    
    course = db.query(Course).filter(Course.id == item.course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found.")

    pct = round((item.attended / item.total) * 100, 2) if item.total > 0 else 0.0
    ext_id = f"manual-att:{item.course_id}:{hashlib.sha256(item.subject.encode('utf-8')).hexdigest()[:16]}"
    
    record = db.query(AttendanceRecord).filter(AttendanceRecord.external_id == ext_id).first()
    if not record:
        record = AttendanceRecord(
            user_id="legacy",
            external_id=ext_id,
            course_id=item.course_id,
            subject=item.subject.strip(),
            attended=item.attended,
            total=item.total,
            percentage=pct,
        )
        db.add(record)
    else:
        record.attended = item.attended
        record.total = item.total
        record.percentage = pct
        record.subject = item.subject.strip()

    db.commit()
    invalidate_attendance_summary_cache()
    db.refresh(record)
    return _format_record(record, course.name)


@router.put("/{record_id}", response_model=dict)
def update_attendance_record(record_id: int, item: AttendanceRecordUpdate, db: Session = Depends(get_db)):
    """Update an attendance record (CRUD Update)"""
    record = db.query(AttendanceRecord).filter(AttendanceRecord.id == record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Attendance record not found.")

    new_attended = item.attended if item.attended is not None else record.attended
    new_total = item.total if item.total is not None else record.total

    if new_attended > new_total:
        raise HTTPException(status_code=422, detail="Attended classes cannot exceed total classes.")

    if item.subject is not None:
        record.subject = item.subject.strip()
    record.attended = new_attended
    record.total = new_total
    record.percentage = round((new_attended / new_total) * 100, 2) if new_total > 0 else 0.0
    record.last_updated = datetime.now(timezone.utc)

    db.commit()
    invalidate_attendance_summary_cache()
    db.refresh(record)
    course = db.query(Course).filter(Course.id == record.course_id).first()
    return _format_record(record, course.name if course else None)


@router.delete("/{record_id}", response_model=dict)
def delete_attendance_record(record_id: int, db: Session = Depends(get_db)):
    """Delete an attendance record (CRUD Delete)"""
    record = db.query(AttendanceRecord).filter(AttendanceRecord.id == record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Attendance record not found.")
    db.delete(record)
    db.commit()
    invalidate_attendance_summary_cache()
    return {"deleted": True, "id": record_id}