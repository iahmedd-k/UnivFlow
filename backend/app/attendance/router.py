from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from app.db.database import get_db
from app.db.repositories import AttendanceRecordRepository
from app.db.models import AttendanceRecord, Course

router = APIRouter(prefix="/attendance", tags=["Attendance"])


@router.get("", response_model=List[dict])
def get_attendance_records(db: Session = Depends(get_db)):
    repo = AttendanceRecordRepository(db)
    records = repo.get_all()
    result = []
    for r in records:
        course = db.query(Course).filter(Course.id == r.course_id).first()
        result.append({
            "id": r.id,
            "external_id": r.external_id,
            "course_id": r.course_id,
            "course_name": course.name if course else None,
            "subject": r.subject,
            "attended": r.attended,
            "total": r.total,
            "percentage": r.percentage,
            "last_updated": r.last_updated,
            "created_at": r.created_at,
        })
    return result


@router.get("/{record_id}", response_model=dict)
def get_attendance_record(record_id: int, db: Session = Depends(get_db)):
    record = db.query(AttendanceRecord).filter(AttendanceRecord.id == record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Attendance record not found")
    course = db.query(Course).filter(Course.id == record.course_id).first()
    return {
        "id": record.id,
        "external_id": record.external_id,
        "course_id": record.course_id,
        "course_name": course.name if course else None,
        "subject": record.subject,
        "attended": record.attended,
        "total": record.total,
        "percentage": record.percentage,
        "last_updated": record.last_updated,
        "created_at": record.created_at,
    }


@router.get("/course/{course_id}", response_model=dict)
def get_attendance_by_course(course_id: int, db: Session = Depends(get_db)):
    repo = AttendanceRecordRepository(db)
    record = repo.get_by_course(course_id)
    if not record:
        raise HTTPException(status_code=404, detail="Attendance record not found for this course")
    course = db.query(Course).filter(Course.id == course_id).first()
    return {
        "id": record.id,
        "external_id": record.external_id,
        "course_id": record.course_id,
        "course_name": course.name if course else None,
        "subject": record.subject,
        "attended": record.attended,
        "total": record.total,
        "percentage": record.percentage,
        "last_updated": record.last_updated,
        "created_at": record.created_at,
    }