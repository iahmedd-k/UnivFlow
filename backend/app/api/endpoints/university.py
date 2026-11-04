from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Body
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime, timedelta, timezone
import io, json, re
import os
import httpx
from pypdf import PdfReader
from PIL import Image
import pytesseract
from app.core.config import settings
from app.core.logging import logger

from app.db.database import get_db
from app.db.repositories import ExamRepository, AnnouncementRepository
from app.db.models import Exam, Quiz, Announcement, Setting, Course
from app.auth.clerk_auth import get_current_user_optional
from app.auth.ownership import require_user_id, user_owner_ids
from app.schemas.coursework import AcademicRecordListItem

router = APIRouter(prefix="/university", tags=["University"])

for tesseract_path in (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    os.path.expanduser(r"~\AppData\Local\Programs\Tesseract-OCR\tesseract.exe"),
):
    if os.path.exists(tesseract_path):
        pytesseract.pytesseract.tesseract_cmd = tesseract_path
        break


def _poppler_path() -> str | None:
    """Find Poppler for scanned PDF rendering on Windows and deployed hosts."""
    candidates = [
        os.getenv("POPPLER_PATH"),
        r"C:\Users\Dell\.cache\codex-runtimes\codex-primary-runtime\dependencies\native\poppler\Library\bin",
        r"C:\Program Files\poppler\Library\bin",
    ]
    return next((path for path in candidates if path and os.path.exists(path)), None)


def _ocr_image(image: Image.Image) -> str:
    prepared = image.convert("L")
    if prepared.width * prepared.height < 4_000_000:
        prepared = prepared.resize((prepared.width * 2, prepared.height * 2))
    return pytesseract.image_to_string(prepared, config="--psm 6")


@router.post("/exams/parse-slip", response_model=dict)
async def parse_exam_slip(file: UploadFile = File(...), clerk_user: dict | None = Depends(get_current_user_optional)):
    """Extract exam slip fields for user review; never saves uncertain OCR results."""
    require_user_id(clerk_user)
    filename = (file.filename or "").lower()
    content_type = (file.content_type or "").lower()
    payload = await file.read(20 * 1024 * 1024 + 1)
    if len(payload) > 20 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="The exam slip must be 20 MB or smaller.")
    try:
        if content_type == "application/pdf" or filename.endswith(".pdf"):
            text = "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(payload)).pages)
            if not text.strip():
                from pdf2image import convert_from_bytes
                pages = convert_from_bytes(
                    payload,
                    dpi=300,
                    first_page=1,
                    last_page=8,
                    poppler_path=_poppler_path(),
                    thread_count=2,
                )
                text = "\n".join(_ocr_image(page) for page in pages)
        elif content_type.startswith("image/"):
            text = _ocr_image(Image.open(io.BytesIO(payload)))
        else:
            raise HTTPException(status_code=415, detail="Upload a PDF or image exam slip.")
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Exam slip OCR failed: %s", exc)
        raise HTTPException(status_code=400, detail="Could not read this exam slip. Try a clearer PDF or image.") from exc
    if not text.strip():
        raise HTTPException(status_code=400, detail="No readable text was found in this exam slip.")
    key = settings.groq_api_key
    if not key:
        return {"exams": [], "raw_text": text[:12000], "message": "Text was extracted, but structured extraction is unavailable. Enter the exam details manually."}
    prompt = "Extract every examination from this roll number slip. Return only JSON: {exams:[{subject, date (YYYY-MM-DD), time, room, seating_plan, instructions}]}. Do not guess missing values; use empty strings. Text:\n" + text[:12000]
    try:
        response = httpx.post("https://api.groq.com/openai/v1/chat/completions", headers={"Authorization": f"Bearer {key}"}, json={"model":"openai/gpt-oss-20b","messages":[{"role":"user","content":prompt}],"temperature":0,"max_tokens":1800}, timeout=30)
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        match = re.search(r"\{[\s\S]*\}", content)
        parsed = json.loads(match.group()) if match else {}
        return {"exams": parsed.get("exams", []), "raw_text": text[:12000], "message": "Review all extracted fields before saving."}
    except Exception as exc:
        logger.warning("Exam slip extraction failed: %s", exc)
        return {"exams": [], "raw_text": text[:12000], "message": "Text was extracted, but the exam details need to be entered manually."}


@router.get("/study-material-indexes", response_model=dict)
def get_study_material_indexes(db: Session = Depends(get_db), clerk_user: dict | None = Depends(get_current_user_optional)):
    user_id = require_user_id(clerk_user)
    rows = db.query(Setting).filter(Setting.key.like(f"study_material_index:{user_id}:%")).all()
    indexes = []
    for row in rows:
        try:
            item = json.loads(row.value or "{}")
            item["material_id"] = row.key.rsplit(":", 1)[-1]
            indexes.append(item)
        except (TypeError, ValueError):
            logger.warning("Skipping invalid study material index setting %s", row.key)
    return {"items": indexes}


@router.put("/study-material-indexes/{material_id}", response_model=dict)
def save_study_material_index(material_id: str, payload: dict = Body(...), db: Session = Depends(get_db), clerk_user: dict | None = Depends(get_current_user_optional)):
    user_id = require_user_id(clerk_user)
    title = str(payload.get("title") or "Untitled material")[:500]
    course = str(payload.get("course") or "")[:500]
    content = str(payload.get("content") or "")
    status = str(payload.get("status") or "complete")
    if len(material_id) > 255 or len(content) > 200_000 or status not in {"complete", "failed"}:
        raise HTTPException(status_code=422, detail="The study index is invalid or too large.")
    key = f"study_material_index:{user_id}:{material_id}"
    row = db.query(Setting).filter(Setting.key == key).first()
    value = json.dumps({"title": title, "course": course, "content": content, "status": status}, ensure_ascii=False)
    if row:
        row.value = value
        row.description = "RAG generated study material index"
    else:
        db.add(Setting(key=key, value=value, description="RAG generated study material index"))
    db.commit()
    return {"material_id": material_id, "title": title, "course": course, "content": content, "status": status}


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


@router.get("/exams", response_model=List[AcademicRecordListItem])
def get_exams(
    days: int = Query(30, ge=1, le=365),
    since: Optional[str] = Query(None),
    limit: int = Query(500, ge=1, le=1000),
    offset: int = Query(0, ge=0),
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
    ).order_by(Exam.date, Exam.id).offset(offset).limit(limit).all()
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


@router.get("/quizzes", response_model=List[AcademicRecordListItem])
def get_quizzes(
    since: Optional[str] = Query(None),
    limit: int = Query(500, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    clerk_user: dict | None = Depends(get_current_user_optional),
):
    raise HTTPException(status_code=404, detail="Quiz routes were retired. Use the exam endpoints instead.")


@router.get("/quizzes/{quiz_id}", response_model=AcademicRecordListItem)
def get_quiz(
    quiz_id: int,
    db: Session = Depends(get_db),
    clerk_user: dict | None = Depends(get_current_user_optional),
):
    raise HTTPException(status_code=404, detail="Quiz routes were retired. Use the exam endpoints instead.")


@router.post("/quizzes", include_in_schema=False)
def create_quiz_retired(_: dict | None = Depends(get_current_user_optional)):
    raise HTTPException(status_code=404, detail="Quiz routes were retired. Use the exam endpoints instead.")


@router.put("/quizzes/{quiz_id}", include_in_schema=False)
def update_quiz_retired(quiz_id: int, _: dict | None = Depends(get_current_user_optional)):
    raise HTTPException(status_code=404, detail="Quiz routes were retired. Use the exam endpoints instead.")


@router.delete("/quizzes/{quiz_id}", include_in_schema=False)
def delete_quiz_retired(quiz_id: int, _: dict | None = Depends(get_current_user_optional)):
    raise HTTPException(status_code=404, detail="Quiz routes were retired. Use the exam endpoints instead.")


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
