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


@router.get("/exams", response_model=List[dict])
def get_exams(
    days: int = Query(30, ge=1, le=365),
    since: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    repo = ExamRepository(db)
    start = _semester_start(db, since)
    exams = [item for item in repo.get_upcoming(days) if not start or not item.date or item.date >= start]
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


@router.get("/quizzes", response_model=List[dict])
def get_quizzes(
    days: int = Query(30, ge=1, le=365),
    since: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    repo = QuizRepository(db)
    start = _semester_start(db, since)
    quizzes = [item for item in repo.get_upcoming(days) if not start or not item.date or item.date >= start]
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
