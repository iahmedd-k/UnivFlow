from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime, timedelta, timezone

from app.db.database import get_db
from app.db.repositories import ExamRepository, QuizRepository, AnnouncementRepository
from app.db.models import Exam, Quiz, Announcement, Setting

router = APIRouter(prefix="/university", tags=["University"])


def _semester_start(db: Session, value: Optional[str] = None) -> Optional[datetime]:
    raw = value
    if not raw:
        setting = db.query(Setting).filter(Setting.key == "semester_start_date").first()
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
    db: Session = Depends(get_db)
):
    repo = ExamRepository(db)
    start = _semester_start(db, since)
    exams = [item for item in repo.get_upcoming(days) if _is_on_or_after(item.date, start)]
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
def get_exam(exam_id: int, db: Session = Depends(get_db)):
    exam = db.query(Exam).filter(Exam.id == exam_id).first()
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


class QuizInput(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    course_id: Optional[int] = None
    date: Optional[datetime] = None
    time: Optional[str] = Field(default="", max_length=50)
    room: Optional[str] = Field(default="", max_length=100)
    status: Optional[str] = Field(default="scheduled", max_length=50)


class QuizUpdate(BaseModel):
    title: Optional[str] = Field(default=None, max_length=500)
    date: Optional[datetime] = None
    time: Optional[str] = Field(default=None, max_length=50)
    room: Optional[str] = Field(default=None, max_length=100)
    status: Optional[str] = Field(default=None, max_length=50)


@router.post("/exams", response_model=dict)
def create_exam(item: ExamInput, db: Session = Depends(get_db)):
    """Create a new exam (CRUD Create)"""
    ext_id = f"manual-exam:{hashlib.sha256(item.title.encode('utf-8')).hexdigest()[:16]}:{int(datetime.now(timezone.utc).timestamp())}"
    exam = Exam(
        user_id="legacy",
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
def update_exam(exam_id: int, item: ExamUpdate, db: Session = Depends(get_db)):
    """Update an exam (CRUD Update)"""
    exam = db.query(Exam).filter(Exam.id == exam_id).first()
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
def delete_exam(exam_id: int, db: Session = Depends(get_db)):
    """Delete an exam (CRUD Delete)"""
    exam = db.query(Exam).filter(Exam.id == exam_id).first()
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")
    db.delete(exam)
    db.commit()
    return {"deleted": True, "id": exam_id}


@router.get("/quizzes", response_model=List[dict])
def get_quizzes(
    days: int = Query(30, ge=1, le=365),
    since: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    repo = QuizRepository(db)
    start = _semester_start(db, since)
    quizzes = [item for item in repo.get_upcoming(days) if _is_on_or_after(item.date, start)]
    return [
        {
            "id": q.id,
            "external_id": q.external_id,
            "course_id": q.course_id,
            "title": q.title,
            "date": q.date,
            "time": q.time,
            "room": q.room,
            "status": q.status,
            "created_at": q.created_at,
            "updated_at": q.updated_at,
        }
        for q in quizzes
    ]


@router.get("/quizzes/{quiz_id}", response_model=dict)
def get_quiz(quiz_id: int, db: Session = Depends(get_db)):
    quiz = db.query(Quiz).filter(Quiz.id == quiz_id).first()
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz not found")
    return {
        "id": quiz.id,
        "external_id": quiz.external_id,
        "course_id": quiz.course_id,
        "title": quiz.title,
        "date": quiz.date,
        "time": quiz.time,
        "room": quiz.room,
        "status": quiz.status,
        "created_at": quiz.created_at,
        "updated_at": quiz.updated_at,
    }


@router.post("/quizzes", response_model=dict)
def create_quiz(item: QuizInput, db: Session = Depends(get_db)):
    """Create a new quiz (CRUD Create)"""
    ext_id = f"manual-quiz:{hashlib.sha256(item.title.encode('utf-8')).hexdigest()[:16]}:{int(datetime.now(timezone.utc).timestamp())}"
    quiz = Quiz(
        user_id="legacy",
        external_id=ext_id,
        course_id=item.course_id,
        title=item.title.strip(),
        date=item.date,
        time=item.time.strip() if item.time else None,
        room=item.room.strip() if item.room else None,
        status=item.status or "scheduled",
    )
    db.add(quiz)
    db.commit()
    db.refresh(quiz)
    return {
        "id": quiz.id,
        "external_id": quiz.external_id,
        "course_id": quiz.course_id,
        "title": quiz.title,
        "date": quiz.date,
        "time": quiz.time,
        "room": quiz.room,
        "status": quiz.status,
        "created_at": quiz.created_at,
        "updated_at": quiz.updated_at,
    }


@router.put("/quizzes/{quiz_id}", response_model=dict)
def update_quiz(quiz_id: int, item: QuizUpdate, db: Session = Depends(get_db)):
    """Update a quiz (CRUD Update)"""
    quiz = db.query(Quiz).filter(Quiz.id == quiz_id).first()
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz not found")
    if item.title is not None:
        quiz.title = item.title.strip()
    if item.date is not None:
        quiz.date = item.date
    if item.time is not None:
        quiz.time = item.time.strip()
    if item.room is not None:
        quiz.room = item.room.strip()
    if item.status is not None:
        quiz.status = item.status
    db.commit()
    db.refresh(quiz)
    return {
        "id": quiz.id,
        "external_id": quiz.external_id,
        "course_id": quiz.course_id,
        "title": quiz.title,
        "date": quiz.date,
        "time": quiz.time,
        "room": quiz.room,
        "status": quiz.status,
        "created_at": quiz.created_at,
        "updated_at": quiz.updated_at,
    }


@router.delete("/quizzes/{quiz_id}", response_model=dict)
def delete_quiz(quiz_id: int, db: Session = Depends(get_db)):
    """Delete a quiz (CRUD Delete)"""
    quiz = db.query(Quiz).filter(Quiz.id == quiz_id).first()
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz not found")
    db.delete(quiz)
    db.commit()
    return {"deleted": True, "id": quiz_id}


@router.get("/announcements", response_model=List[dict])
def get_announcements(
    limit: int = Query(50, ge=1, le=200),
    since: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    query = db.query(Announcement)
    start = _semester_start(db, since)
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
def get_announcement(announcement_id: int, db: Session = Depends(get_db)):
    announcement = db.query(Announcement).filter(Announcement.id == announcement_id).first()
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
