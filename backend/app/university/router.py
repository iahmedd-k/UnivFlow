from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime, timedelta, timezone

from app.db.database import get_db
from app.db.repositories import ExamRepository, AnnouncementRepository
from app.db.models import Exam, Announcement, Setting, Course
from app.auth.clerk_auth import get_current_user_optional
from app.auth.ownership import require_user_id, user_owner_ids

router = APIRouter(prefix="/university", tags=["University"])


def _semester_start(db: Session, value: Optional[str] = None, user_id: str = "") -> Optional[datetime]:
    raw = value
    if not raw and user_id:
        setting = db.query(Setting).filter(Setting.key == f"classroom:{user_id}:semester_start_date").first()
        raw = setting.value if setting and setting.value else None
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(str(raw).strip().replace('"', '').replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
    except ValueError:
        return None


def _is_on_or_after(dt: Optional[datetime], start: Optional[datetime]) -> bool:
    if not dt or not start:
        return True
    dt_aware = dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
    start_aware = start.replace(tzinfo=timezone.utc) if start.tzinfo is None else start
    return dt_aware >= start_aware


@router.get("/exams", response_model=List[dict])
def get_exams(
    days: int = Query(30, ge=1, le=365),
    since: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    clerk_user: dict | None = Depends(get_current_user_optional),
):
    user_id = require_user_id(clerk_user)
    owners = user_owner_ids(user_id)
    start = _semester_start(db, since, user_id)
    now = datetime.now(timezone.utc)
    exams = db.query(Exam).filter(
        Exam.user_id.in_(owners),
        Exam.date >= now,
        Exam.date <= now + timedelta(days=days),
    ).order_by(Exam.date).all()
    exams = [item for item in exams if _is_on_or_after(item.date, start)]
    return [
        {
            "id": e.id,
            "external_id": e.external_id,
            "course_id": e.course_id,
            "title": e.title,
            "date": e.date,
            "time": e.time,
            "room": e.room,
            "status": e.status,
            "created_at": e.created_at,
            "updated_at": e.updated_at,
        }
        for e in exams
    ]


@router.get("/exams/{exam_id}", response_model=dict)
def get_exam(exam_id: int, db: Session = Depends(get_db), clerk_user: dict | None = Depends(get_current_user_optional)):
    user_id = require_user_id(clerk_user)
    exam = db.query(Exam).filter(Exam.id == exam_id, Exam.user_id.in_(user_owner_ids(user_id))).first()
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")
    return {
        "id": exam.id,
        "external_id": exam.external_id,
        "course_id": exam.course_id,
        "title": exam.title,
        "date": exam.date,
        "time": exam.time,
        "room": exam.room,
        "status": exam.status,
        "created_at": exam.created_at,
        "updated_at": exam.updated_at,
    }


from pydantic import BaseModel, Field
import hashlib


class ExamInput(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    course_id: Optional[int] = None
    date: Optional[datetime] = None
    time: Optional[str] = Field(default="", max_length=50)
    room: Optional[str] = Field(default="", max_length=100)
    status: Optional[str] = Field(default="scheduled", max_length=50)


class ExamUpdate(BaseModel):
    title: Optional[str] = Field(default=None, max_length=500)
    date: Optional[datetime] = None
    time: Optional[str] = Field(default=None, max_length=50)
    room: Optional[str] = Field(default=None, max_length=100)
    status: Optional[str] = Field(default=None, max_length=50)


@router.post("/exams", response_model=dict)
def create_exam(item: ExamInput, db: Session = Depends(get_db), clerk_user: dict | None = Depends(get_current_user_optional)):
    """Create a new exam (CRUD Create)"""
    user_id = require_user_id(clerk_user)
    if item.course_id is not None and not db.query(Course.id).filter(Course.id == item.course_id, Course.user_id.in_(user_owner_ids(user_id))).first():
        raise HTTPException(status_code=404, detail="Course not found.")
    ext_id = f"manual-exam:{hashlib.sha256(item.title.encode('utf-8')).hexdigest()[:16]}:{int(datetime.now(timezone.utc).timestamp())}"
    exam = Exam(
        user_id=user_id,
        external_id=ext_id,
        course_id=item.course_id,
        title=item.title.strip(),
        date=item.date,
        time=item.time.strip() if item.time else None,
        room=item.room.strip() if item.room else None,
        status=item.status or "scheduled",
    )
    db.add(exam)
    db.commit()
    db.refresh(exam)
    return {
        "id": exam.id,
        "external_id": exam.external_id,
        "course_id": exam.course_id,
        "title": exam.title,
        "date": exam.date,
        "time": exam.time,
        "room": exam.room,
        "status": exam.status,
        "created_at": exam.created_at,
        "updated_at": exam.updated_at,
    }


@router.put("/exams/{exam_id}", response_model=dict)
def update_exam(exam_id: int, item: ExamUpdate, db: Session = Depends(get_db), clerk_user: dict | None = Depends(get_current_user_optional)):
    """Update an exam (CRUD Update)"""
    user_id = require_user_id(clerk_user)
    exam = db.query(Exam).filter(Exam.id == exam_id, Exam.user_id.in_(user_owner_ids(user_id))).first()
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")
    if item.title is not None:
        exam.title = item.title.strip()
    if item.date is not None:
        exam.date = item.date
    if item.time is not None:
        exam.time = item.time.strip()
    if item.room is not None:
        exam.room = item.room.strip()
    if item.status is not None:
        exam.status = item.status
    db.commit()
    db.refresh(exam)
    return {
        "id": exam.id,
        "external_id": exam.external_id,
        "course_id": exam.course_id,
        "title": exam.title,
        "date": exam.date,
        "time": exam.time,
        "room": exam.room,
        "status": exam.status,
        "created_at": exam.created_at,
        "updated_at": exam.updated_at,
    }


@router.delete("/exams/{exam_id}", response_model=dict)
def delete_exam(exam_id: int, db: Session = Depends(get_db), clerk_user: dict | None = Depends(get_current_user_optional)):
    """Delete an exam (CRUD Delete)"""
    user_id = require_user_id(clerk_user)
    exam = db.query(Exam).filter(Exam.id == exam_id, Exam.user_id.in_(user_owner_ids(user_id))).first()
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")
    db.delete(exam)
    db.commit()
    return {"deleted": True, "id": exam_id}


@router.get("/announcements", response_model=List[dict])
def get_announcements(
    limit: int = Query(50, ge=1, le=200),
    since: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    clerk_user: dict | None = Depends(get_current_user_optional),
):
    user_id = require_user_id(clerk_user)
    query = db.query(Announcement).filter(Announcement.user_id.in_(user_owner_ids(user_id)))
    start = _semester_start(db, since, user_id)
    if start:
        query = query.filter((Announcement.published_at >= start) | (Announcement.created_at >= start) | Announcement.published_at.is_(None))
    announcements = query.order_by(Announcement.published_at.desc().nullslast()).limit(limit).all()
    return [
        {
            "id": a.id,
            "external_id": a.external_id,
            "title": a.title,
            "content": a.content,
            "source": a.source,
            "fingerprint": a.fingerprint,
            "published_at": a.published_at,
            "created_at": a.created_at,
        }
        for a in announcements
    ]


@router.get("/announcements/{announcement_id}", response_model=dict)
def get_announcement(announcement_id: int, db: Session = Depends(get_db), clerk_user: dict | None = Depends(get_current_user_optional)):
    user_id = require_user_id(clerk_user)
    announcement = db.query(Announcement).filter(Announcement.id == announcement_id, Announcement.user_id.in_(user_owner_ids(user_id))).first()
    if not announcement:
        raise HTTPException(status_code=404, detail="Announcement not found")
    return {
        "id": announcement.id,
        "external_id": announcement.external_id,
        "title": announcement.title,
        "content": announcement.content,
        "source": announcement.source,
        "fingerprint": announcement.fingerprint,
        "published_at": announcement.published_at,
        "created_at": announcement.created_at,
    }
