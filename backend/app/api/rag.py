import logging
import re
import io
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from pydantic import BaseModel, Field
from typing import List, Optional
from sqlalchemy import or_, and_, func
from app.db.database import get_db
from app.core.config import settings
from app.auth.clerk_auth import get_current_user_optional
from app.services.ai_solution import _call_groq
from app.db.models import AssignmentMaterial, Assignment, Course, ChatConversation, ChatMessage, StudyPlan, StudyPlanSession
from app.rag.study_planning import (
    SPACED_REVIEW_OFFSETS,
    generate_study_plan,
    extract_topics_from_syllabus,
    _parse_date,
    _safe_json_loads,
    _safe_json_dumps,
    StudyPlanningError,
)

logger = logging.getLogger(__name__)

# Per selected document we load the FULL text (lazily, only when the user
# selects/attaches it). We never pre-chunk or pre-process all documents upfront.
MAX_DOC_CHARS = 30000

router = APIRouter(prefix="/rag", tags=["RAG"])

class ChatRequest(BaseModel):
    document_id: str | None = None
    document_ids: list[str] = Field(default_factory=list, max_length=100)
    course_id: int | None = Field(default=None, gt=0)
    query: str
    syllabus: str | None = None
    # Previous turns so the assistant can answer in conversation context.
    history: Optional[List[dict]] = Field(default_factory=list)
    # Optional existing conversation to continue (persisted).
    conversation_id: Optional[int] = None
    # Optional academic context (e.g., CGPA) that can be used in the answer
    academic_context: dict | None = None


class StudyPlanRequest(BaseModel):
    syllabus: str = Field(min_length=10, max_length=12000)
    document_ids: list[str] = Field(default_factory=list, max_length=100)
    exam_title: str | None = Field(default=None, max_length=300)
    exam_date: str | None = Field(default=None, max_length=30)
    start_date: str | None = Field(default=None, max_length=30)
    end_date: str | None = Field(default=None, max_length=30)
    hours_per_day: float = Field(default=3.0, ge=0.5, le=12.0)
    session_minutes: int = Field(default=60, ge=15, le=240)
    plan_mode: str = Field(default="spaced_repetition")  # "coverage" | "spaced_repetition"
    topics: Optional[list[dict]] = Field(default_factory=list)  # user-corrected topics


class StudyPlanSessionUpdate(BaseModel):
    status: str = Field(pattern="^(pending|done|partial|missed)$")
    notes: Optional[str] = None


def _classify_material(material_title: str, assignment_title: str, work_type: str, mime_type: str, material_type: str):
    wt = (work_type or "").upper()
    mt = (material_type or "").lower()
    t = f"{material_title or ''} {assignment_title or ''}".lower()
    m = (mime_type or "").lower()

    # 1. Direct presentation / slides / lecture / readings / notes / syllabus priority
    if (
        "presentation" in m or "powerpoint" in m
        or any(t.endswith(ext) for ext in [".ppt", ".pptx", ".key"])
        or any(k in t for k in ["slide", "lecture", "handout", "reading", "notes", "chapter", "unit", "syllabus", "textbook", "presentation"])
    ):
        return "material", "Slides & Handouts", "book"

    # 2. Announcements
    if wt in ("ANNOUNCEMENT", "POST") or mt == "announcement" or "announcement" in t:
        return "announcement", "Announcements & Notes", "bell"

    # 3. Labs & Assignments
    if (
        wt in ("ASSIGNMENT", "SHORT_ANSWER_QUESTION", "MULTIPLE_CHOICE_QUESTION")
    ) or any(k in t for k in ["lab ", "lab-", "lab#", "manual", "task", "assignment", "hw", "homework", "quiz", "midterm", "final", "exam"]):
        return "assignment", "Labs & Assignments", "flask"

    return "material", "Slides & Handouts", "book"


def _classify_file_type(mime_type: str, title: str, category: str):
    m = (mime_type or "").lower()
    t = (title or "").lower()
    if "pdf" in m or t.endswith(".pdf"):
        return "pdf"
    if "presentation" in m or any(t.endswith(ext) for ext in [".ppt", ".pptx", ".key"]):
        return "slide"
    if "document" in m or any(t.endswith(ext) for ext in [".doc", ".docx", ".odt"]):
        return "doc"
    if "sheet" in m or any(t.endswith(ext) for ext in [".xls", ".xlsx", ".csv"]):
        return "sheet"
    if m.startswith("text/") or any(t.endswith(ext) for ext in [".py", ".c", ".cpp", ".java", ".js", ".ts", ".html", ".css", ".json", ".sql", ".sh"]):
        return "code"
    if category == "announcement":
        return "announcement"
    return "text"


@router.get("/materials")
def get_classroom_materials(
    limit: int = 500,
    course_id: Optional[int] = None,
    category: Optional[str] = None,
    query: Optional[str] = None,
    current_user: Optional[dict] = Depends(get_current_user_optional),
    db=Depends(get_db)
):
    user_id = _user_id(current_user)
    q = (
        db.query(AssignmentMaterial, Assignment, Course)
        .join(Assignment, Assignment.id == AssignmentMaterial.assignment_id)
        .join(Course, Course.id == Assignment.course_id)
    )

    if user_id and user_id != "dev_student_user":
        q = q.filter(
            or_(Assignment.user_id == user_id, Assignment.user_id == "legacy"),
            or_(Course.user_id == user_id, Course.user_id == "legacy"),
            or_(AssignmentMaterial.user_id == user_id, AssignmentMaterial.user_id == "legacy"),
        )

    if course_id:
        q = q.filter(Course.id == course_id)

    if query and query.strip():
        term = f"%{query.strip()}%"
        q = q.filter(
            or_(
                AssignmentMaterial.title.ilike(term),
                Assignment.title.ilike(term),
                Course.name.ilike(term),
            )
        )

    rows = (
        q.order_by(AssignmentMaterial.created_at.desc(), AssignmentMaterial.id.desc())
        .limit(min(max(limit, 1), 1000))
        .all()
    )

    seen, result = set(), []
    for material, assignment, course in rows:
        unique_key = material.drive_file_id or f"mat_{material.id}"
        if unique_key in seen:
            continue
        seen.add(unique_key)

        cat_key, cat_label, cat_icon = _classify_material(
            material.title or "", assignment.title or "", assignment.work_type, material.mime_type or "", material.material_type or ""
        )
        file_t = _classify_file_type(material.mime_type or "", material.title or assignment.title or "", cat_key)

        if category and category != "all" and cat_key != category:
            continue

        result.append({
            "id": unique_key,
            "material_id": material.id,
            "assignment_id": assignment.id,
            "title": material.title or assignment.title or "Untitled document",
            "course_id": course.id,
            "course_name": course.name,
            "assignment": assignment.title,
            "work_type": assignment.work_type or "ASSIGNMENT",
            "category": cat_key,
            "category_label": cat_label,
            "category_icon": cat_icon,
            "file_type": file_t,
            "mime_type": material.mime_type or "",
            "url": material.url or assignment.url,
            "has_content": bool(material.content or assignment.description),
            "created_at": material.created_at.isoformat() if material.created_at else None,
        })

    # Also include assignments that don't have separate material records but have descriptions/instructions
    seen_assignment_ids = {m.assignment_id for m, _, _ in rows}
    q_asg = (
        db.query(Assignment, Course)
        .join(Course, Course.id == Assignment.course_id)
    )
    if seen_assignment_ids:
        q_asg = q_asg.filter(Assignment.id.notin_(seen_assignment_ids))
    if user_id and user_id != "dev_student_user":
        q_asg = q_asg.filter(
            or_(Assignment.user_id == user_id, Assignment.user_id == "legacy"),
            or_(Course.user_id == user_id, Course.user_id == "legacy"),
        )
    if course_id:
        q_asg = q_asg.filter(Course.id == course_id)
    if query and query.strip():
        term = f"%{query.strip()}%"
        q_asg = q_asg.filter(or_(Assignment.title.ilike(term), Course.name.ilike(term)))

    extra_assignments = q_asg.order_by(Assignment.created_at.desc(), Assignment.id.desc()).limit(150).all()
    for assignment, course in extra_assignments:
        unique_key = f"asg_{assignment.id}"
        if unique_key in seen:
            continue
        seen.add(unique_key)
        cat_key, cat_label, cat_icon = _classify_material(
            "", assignment.title, assignment.work_type, "", "assignment"
        )
        file_t = _classify_file_type("", assignment.title, cat_key)
        if category and category != "all" and cat_key != category:
            continue
        result.append({
            "id": unique_key,
            "material_id": None,
            "assignment_id": assignment.id,
            "title": assignment.title or "Course Document",
            "course_id": course.id,
            "course_name": course.name,
            "assignment": assignment.title,
            "work_type": assignment.work_type or "ASSIGNMENT",
            "category": cat_key,
            "category_label": cat_label,
            "category_icon": cat_icon,
            "file_type": file_t,
            "mime_type": "text/plain",
            "url": assignment.url,
            "has_content": bool(assignment.description),
            "created_at": assignment.created_at.isoformat() if assignment.created_at else None,
        })

    return result


@router.post("/sync-materials")
def sync_classroom_study_materials(
    current_user: Optional[dict] = Depends(get_current_user_optional),
    db=Depends(get_db)
):
    """Synchronize Google Classroom courses, coursework materials, and announcements on demand."""
    from app.services.classroom_sync import get_classroom_service
    user_id = _user_id(current_user)
    service = get_classroom_service(db, user_id=user_id)
    if not service:
        raise HTTPException(status_code=503, detail="Google Classroom is not connected. Complete OAuth first.")
    try:
        courses = service._get_all_courses()
        synced_courses = 0
        synced_assignments = 0
        synced_materials = 0
        for course in courses:
            service._sync_course(course, is_active=True)
            synced_courses += 1
            synced_assignments += service._sync_coursework(course["id"], since_date=datetime(1970, 1, 1, tzinfo=timezone.utc))
            m_count = service._sync_coursework_materials(course["id"])
            synced_materials += m_count
            service._sync_announcements(course)
        if getattr(service, "scope_missing_for_materials", False):
            return {
                "status": "reconnect_required",
                "scope_missing": True,
                "reconnect_url": "/api/v1/auth/google?redirect_to=/dashboard/courses",
                "courses_synced": synced_courses,
                "assignments_synced": synced_assignments,
                "materials_synced": synced_materials,
                "message": "Google Classroom needs to be reconnected to grant permission to sync course slides and handouts."
            }
        if getattr(service, "study_material_sync_errors", None):
            return {
                "status": "partial",
                "courses_synced": synced_courses,
                "assignments_synced": synced_assignments,
                "materials_synced": synced_materials,
                "error": "; ".join(service.study_material_sync_errors[:5]),
            }
        return {
            "status": "success",
            "courses_synced": synced_courses,
            "assignments_synced": synced_assignments,
            "materials_synced": synced_materials,
        }
    except Exception as e:
        logger.warning(f"Error during on-demand materials sync: {e}")
        return {"status": "partial", "error": str(e)}


def _extract_text_from_upload(filename: str, content_type: str, data: bytes) -> str:
    """Extract readable text from uploaded presentations, pdfs, word documents, or plain text."""
    text = ""
    lower_name = (filename or "").lower()
    ct = (content_type or "").lower()

    # 1. PPTX presentation
    if lower_name.endswith(".pptx") or "presentation" in ct:
        try:
            import zipfile
            import xml.etree.ElementTree as ET
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                slide_texts = []
                slide_files = [n for n in z.namelist() if n.startswith("ppt/slides/slide") and n.endswith(".xml")]
                slide_files.sort(key=lambda s: int(re.search(r'\d+', s.split('/')[-1]).group()) if re.search(r'\d+', s.split('/')[-1]) else 0)
                for sf in slide_files:
                    xml_content = z.read(sf)
                    tree = ET.fromstring(xml_content)
                    slide_num = re.search(r'\d+', sf.split('/')[-1]).group() if re.search(r'\d+', sf.split('/')[-1]) else ""
                    tokens = [elem.text for elem in tree.iter() if elem.tag.endswith("}t") and elem.text]
                    if tokens:
                        slide_texts.append(f"--- Slide {slide_num} ---\n" + "\n".join(tokens))
                text = "\n\n".join(slide_texts)
        except Exception as e:
            logger.warning(f"Error extracting text from pptx upload: {e}")

    # 2. PDF document
    elif lower_name.endswith(".pdf") or "pdf" in ct:
        try:
            from pypdf import PdfReader
            pdf = PdfReader(io.BytesIO(data))
            text = "\n".join(page.extract_text() or "" for page in pdf.pages)
        except Exception as e:
            logger.warning(f"Error extracting text from pdf upload: {e}")

    # 3. DOCX document
    elif lower_name.endswith(".docx") or "wordprocessingml" in ct:
        try:
            import docx
            doc = docx.Document(io.BytesIO(data))
            text = "\n".join(p.text for p in doc.paragraphs if p.text)
        except Exception as e:
            logger.warning(f"Error extracting text from docx upload: {e}")

    # 4. Text / Code / Markdown
    elif ct.startswith("text/") or any(lower_name.endswith(ext) for ext in [".txt", ".md", ".py", ".c", ".cpp", ".java", ".js", ".ts", ".html", ".css", ".json", ".csv", ".xml"]):
        try:
            text = data.decode("utf-8", errors="ignore")
        except Exception:
            text = str(data)

    return text.strip()


@router.post("/materials/upload")
async def upload_study_material(
    course_id: int = Form(...),
    file: UploadFile = File(...),
    current_user: Optional[dict] = Depends(get_current_user_optional),
    db=Depends(get_db)
):
    """Upload slides, lecture notes, handouts, or documents directly into a course for study assistance."""
    user_id = _user_id(current_user)
    course = db.query(Course).filter(
        Course.id == course_id,
        or_(
            Course.user_id == user_id,
            Course.user_id == "legacy",
            user_id == "dev_student_user",
        )
    ).first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    content_bytes = await file.read()
    if len(content_bytes) > 25 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large (max 25MB)")

    filename = file.filename or "Uploaded Document"
    content_type = file.content_type or "application/octet-stream"
    extracted_text = _extract_text_from_upload(filename, content_type, content_bytes)

    # Find or create a course materials container assignment
    container = db.query(Assignment).filter(
        Assignment.course_id == course.id,
        Assignment.work_type == "MATERIAL",
        Assignment.title == f"Course Uploads - {course.name}",
    ).first()

    if not container:
        container = Assignment(
            user_id=user_id,
            external_id=f"uploads_{course.id}",
            course_id=course.id,
            title=f"Course Uploads - {course.name}",
            work_type="MATERIAL",
            description="Uploaded lecture slides, notes, handouts, and study materials.",
            status="SUBMITTED",
        )
        db.add(container)
        db.flush()

    cat_key, cat_label, cat_icon = _classify_material(filename, container.title, "MATERIAL", content_type, "material")
    file_t = _classify_file_type(content_type, filename, cat_key)

    material = AssignmentMaterial(
        user_id=user_id,
        assignment_id=container.id,
        material_type="upload",
        title=filename,
        mime_type=content_type,
        content=extracted_text[:MAX_DOC_CHARS] if extracted_text else None,
    )
    db.add(material)
    db.commit()
    db.refresh(material)

    unique_key = f"mat_{material.id}"
    return {
        "status": "success",
        "material": {
            "id": unique_key,
            "material_id": material.id,
            "assignment_id": container.id,
            "title": material.title,
            "course_id": course.id,
            "course_name": course.name,
            "assignment": container.title,
            "work_type": "MATERIAL",
            "category": cat_key,
            "category_label": cat_label,
            "category_icon": cat_icon,
            "file_type": file_t,
            "mime_type": content_type,
            "url": None,
            "has_content": bool(extracted_text),
            "created_at": material.created_at.isoformat() if material.created_at else None,
        }
    }


def _read_materials(db, document_ids: list[str], max_chars: int = MAX_DOC_CHARS, user_id: str | None = None) -> list[dict]:
    if not document_ids:
        return []

    clean_ids = list(dict.fromkeys(document_ids))
    int_ids = []
    for x in clean_ids:
        if str(x).isdigit():
            int_ids.append(int(x))
        elif str(x).startswith("mat_") and str(x)[4:].isdigit():
            int_ids.append(int(str(x)[4:]))

    # Fetch cached rows from DB first to avoid unnecessary network calls
    rows_query = db.query(AssignmentMaterial).join(Assignment, Assignment.id == AssignmentMaterial.assignment_id).join(Course, Course.id == Assignment.course_id).filter(
        or_(
            AssignmentMaterial.drive_file_id.in_(clean_ids),
            AssignmentMaterial.id.in_(int_ids) if int_ids else False
        )
    )
    if user_id and user_id != "dev_student_user":
        rows_query = rows_query.filter(
            or_(AssignmentMaterial.user_id == user_id, AssignmentMaterial.user_id == "legacy"),
            or_(Assignment.user_id == user_id, Assignment.user_id == "legacy"),
            or_(Course.user_id == user_id, Course.user_id == "legacy"),
        )
    db_rows = rows_query.all()

    db_map = {}
    for r in db_rows:
        if r.drive_file_id:
            db_map[r.drive_file_id] = r
        db_map[str(r.id)] = r
        db_map[f"mat_{r.id}"] = r

    materials = []
    for document_id in clean_ids:
        content = ""
        title = "Course material"
        url = None
        mime = ""

        if document_id.startswith("asg_") and document_id[4:].isdigit():
            asg_id = int(document_id[4:])
            assignment_query = db.query(Assignment).join(Course, Course.id == Assignment.course_id).filter(Assignment.id == asg_id)
            if user_id and user_id != "dev_student_user":
                assignment_query = assignment_query.filter(
                    or_(Assignment.user_id == user_id, Assignment.user_id == "legacy"),
                    or_(Course.user_id == user_id, Course.user_id == "legacy"),
                )
            asg = assignment_query.first()
            if asg:
                title = asg.title or title
                url = asg.url or url
                content = asg.description or ""
                mime = "text/plain"

        mat_row = db_map.get(document_id)
        if mat_row:
            title = mat_row.title or title
            url = mat_row.url or url
            mime = mat_row.mime_type or ""
            if mat_row.content:
                content = mat_row.content
            elif mat_row.assignment and mat_row.assignment.description:
                content = mat_row.assignment.description

        if title or content:
            materials.append({
                "id": document_id,
                "title": title,
                "url": url,
                "mime_type": mime,
                "content": (content or "")[:max_chars]
            })

    return materials


def _retrieve_passages(materials: list[dict], query: str, limit: int = 6) -> list[str]:
    terms = {word.lower() for word in re.findall(r"[\w'-]{3,}", query)}
    ranked = []
    for material in materials:
        text = material.get("content", "")
        chunks = [text[start:start + 1600] for start in range(0, min(len(text), 16000), 1300)]
        for index, chunk in enumerate(chunks):
            words = {word.lower() for word in re.findall(r"[\w'-]{3,}", chunk)}
            score = len(terms & words)
            ranked.append((score, material["title"], index, chunk))
    ranked.sort(key=lambda row: (-row[0], row[1], row[2]))
    chosen = [row for row in ranked if row[0] > 0][:limit]
    if not chosen:
        chosen = ranked[:min(limit, 2)]
    return [f"Source: {title}\n{chunk}" for _, title, _, chunk in chosen]


# Study planner API retired; dashboard no longer exposes study plans.
async def create_study_plan(request: StudyPlanRequest, db=Depends(get_db), clerk_user: Optional[dict] = Depends(get_current_user_optional)):
    """Build a day-by-day study plan grounded in the syllabus and selected materials.

    Uses an evidence-based scheduler (spaced repetition / coverage mode) with
    topic weighting, daily capacity caps and burnout protection. The plan is
    persisted so the user can track progress session-by-session.
    """
    try:
        if not request.syllabus.strip():
            raise HTTPException(status_code=422, detail="Paste a syllabus or topic list to build a plan.")

        user_id = _user_id(clerk_user)

        # Parse dates
        start_date = _parse_date(request.start_date) or _now_utc().date()
        end_date = _parse_date(request.end_date) or (start_date + timedelta(days=14))
        exam_date = _parse_date(request.exam_date) or end_date

        if end_date < start_date:
            raise HTTPException(status_code=422, detail="End date must be on or after the start date.")
        if request.plan_mode not in ("coverage", "spaced_repetition"):
            raise HTTPException(status_code=422, detail="plan_mode must be 'coverage' or 'spaced_repetition'.")

        # Build document context from selected materials (lazy read, per selection)
        materials = _read_materials(db, request.document_ids, user_id=user_id)
        document_context = "\n\n".join(
            f"MATERIAL: {item['title']}\n{item['content'][:4000]}" for item in materials
        ) if materials else "No materials selected."

        # Use user-corrected topics if provided, otherwise extract from syllabus
        topics = request.topics if request.topics else extract_topics_from_syllabus(request.syllabus, request.exam_title)

        plan_data = generate_study_plan(
            syllabus=request.syllabus,
            exam_title=request.exam_title,
            exam_date=exam_date,
            start_date=start_date,
            end_date=end_date,
            hours_per_day=request.hours_per_day,
            session_minutes=request.session_minutes,
            plan_mode=request.plan_mode,
            topics=topics,
            document_context=document_context,
        )

        # Persist the plan
        plan = StudyPlan(
            user_id=user_id,
            title=request.exam_title or f"Study plan ({start_date.isoformat()} → {end_date.isoformat()})",
            exam_title=request.exam_title,
            exam_date=datetime.combine(exam_date, datetime.min.time(), tzinfo=timezone.utc) if exam_date else None,
            syllabus=request.syllabus,
            topics=_safe_json_dumps(plan_data["topics"]),
            preferences=_safe_json_dumps(plan_data["preferences"]),
            stats=_safe_json_dumps(plan_data["stats"]),
            summary=plan_data["summary"],
            status="active",
        )
        db.add(plan)
        db.flush()

        for s in plan_data["sessions"]:
            db.add(StudyPlanSession(
                plan_id=plan.id,
                session_date=s["session_date"],
                session_type=s["session_type"],
                topic=s["topic"],
                duration_minutes=s["duration_minutes"],
                order_index=s["order_index"],
                status="pending",
            ))
        db.commit()

        return {
            "id": plan.id,
            "title": plan.title,
            "exam_title": plan.exam_title,
            "exam_date": plan.exam_date,
            "topics": plan_data["topics"],
            "preferences": plan_data["preferences"],
            "stats": plan_data["stats"],
            "summary": plan_data["summary"],
            "sessions": [
                {
                    "id": sess.id,
                    "session_date": sess.session_date,
                    "session_type": sess.session_type,
                    "topic": sess.topic,
                    "duration_minutes": sess.duration_minutes,
                    "order_index": sess.order_index,
                    "status": sess.status,
                    "notes": sess.notes,
                }
                for sess in plan.sessions
            ],
            "materials": [{k: v for k, v in item.items() if k != "content"} for item in materials],
        }
    except StudyPlanningError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=502, detail=f"Could not generate the study plan: {e}") from e


def list_study_plans(
    limit: int = 50,
    db=Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional),
):
    """List the current user's study plans."""
    user_id = _user_id(clerk_user)
    rows = (
        db.query(StudyPlan)
        .filter(StudyPlan.user_id == user_id)
        .order_by(StudyPlan.updated_at.desc().nullslast(), StudyPlan.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": p.id,
            "title": p.title,
            "exam_title": p.exam_title,
            "exam_date": p.exam_date,
            "status": p.status,
            "stats": _safe_json_loads(p.stats, {}),
            "created_at": p.created_at,
            "updated_at": p.updated_at,
        }
        for p in rows
    ]


def get_study_plan(
    plan_id: int,
    db=Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional),
):
    """Return a study plan with its day-by-day sessions."""
    user_id = _user_id(clerk_user)
    plan = (
        db.query(StudyPlan)
        .filter(StudyPlan.id == plan_id, StudyPlan.user_id == user_id)
        .first()
    )
    if not plan:
        raise HTTPException(status_code=404, detail="Study plan not found")
    sessions = (
        db.query(StudyPlanSession)
        .filter(StudyPlanSession.plan_id == plan_id)
        .order_by(StudyPlanSession.session_date.asc(), StudyPlanSession.order_index.asc())
        .all()
    )
    return {
        "id": plan.id,
        "title": plan.title,
        "exam_title": plan.exam_title,
        "exam_date": plan.exam_date,
        "syllabus": plan.syllabus,
        "topics": _safe_json_loads(plan.topics, []),
        "preferences": _safe_json_loads(plan.preferences, {}),
        "stats": _safe_json_loads(plan.stats, {}),
        "summary": plan.summary,
        "status": plan.status,
        "created_at": plan.created_at,
        "updated_at": plan.updated_at,
        "sessions": [
            {
                "id": s.id,
                "session_date": s.session_date,
                "session_type": s.session_type,
                "topic": s.topic,
                "duration_minutes": s.duration_minutes,
                "order_index": s.order_index,
                "status": s.status,
                "notes": s.notes,
                "created_at": s.created_at,
            }
            for s in sessions
        ],
    }


def update_session_status(
    plan_id: int,
    session_id: int,
    payload: StudyPlanSessionUpdate,
    db=Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional),
):
    """Mark a study session as done / partial / missed."""
    user_id = _user_id(clerk_user)
    plan = (
        db.query(StudyPlan)
        .filter(StudyPlan.id == plan_id, StudyPlan.user_id == user_id)
        .first()
    )
    if not plan:
        raise HTTPException(status_code=404, detail="Study plan not found")
    session = (
        db.query(StudyPlanSession)
        .filter(StudyPlanSession.id == session_id, StudyPlanSession.plan_id == plan_id)
        .first()
    )
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    session.status = payload.status
    if payload.notes is not None:
        session.notes = payload.notes
    session.updated_at = func.now()
    db.commit()

    # Recompute completion stats
    all_sessions = (
        db.query(StudyPlanSession)
        .filter(StudyPlanSession.plan_id == plan_id)
        .all()
    )
    done = sum(1 for s in all_sessions if s.status == "done")
    partial = sum(1 for s in all_sessions if s.status == "partial")
    missed = sum(1 for s in all_sessions if s.status == "missed")
    total = len(all_sessions)
    stats = _safe_json_loads(plan.stats, {})
    stats.update({
        "done": done,
        "partial": partial,
        "missed": missed,
        "completion_pct": round((done + 0.5 * partial) / total * 100, 1) if total else 0.0,
    })
    plan.stats = _safe_json_dumps(stats)
    db.commit()

    return {
        "id": session.id,
        "status": session.status,
        "notes": session.notes,
        "stats": stats,
    }

@router.get("/conversations", response_model=List[dict])
def list_conversations(
    limit: int = 50,
    db=Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional),
):
    """List the current user's RAG study-assistant conversations."""
    user_id = _user_id(clerk_user)
    rows = (
        db.query(ChatConversation)
        .filter(ChatConversation.user_id == user_id, ChatConversation.source == "rag")
        .order_by(ChatConversation.updated_at.desc().nullslast(), ChatConversation.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": c.id,
            "title": c.title or "Study chat",
            "source": c.source,
            "assignment_id": c.assignment_id,
            "created_at": c.created_at,
            "updated_at": c.updated_at,
        }
        for c in rows
    ]


@router.get("/conversations/{conversation_id}/messages", response_model=List[dict])
def get_conversation_messages(
    conversation_id: int,
    db=Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional),
):
    """Return messages for one conversation (owner only)."""
    user_id = _user_id(clerk_user)
    conv = (
        db.query(ChatConversation)
        .filter(ChatConversation.id == conversation_id, ChatConversation.user_id == user_id)
        .first()
    )
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    messages = (
        db.query(ChatMessage)
        .filter(ChatMessage.conversation_id == conversation_id)
        .order_by(ChatMessage.created_at.asc())
        .all()
    )
    return [
        {"id": m.id, "role": m.role, "content": m.content, "created_at": m.created_at}
        for m in messages
    ]


def _user_id(clerk_user: Optional[dict]) -> str:
    user_id = str((clerk_user or {}).get("id") or "")
    if not user_id:
        user_id = "dev_student_user"
    return user_id


@router.post("/chat")
async def rag_chat(request: ChatRequest, db=Depends(get_db), clerk_user: Optional[dict] = Depends(get_current_user_optional)):
    """Answer a user's query from the documents they selected/attached.

    Documents are only read (and chunked at query time) when the user selects
    them - we never pre-chunk or pre-process all documents upfront. The LLM
    receives the FULL text of every selected document so it can answer with
    complete information, supplemented by the most relevant retrieved passages.
    The conversation is persisted so the user can see previous questions and
    answers.
    """
    try:
        if not request.query.strip():
            raise HTTPException(status_code=422, detail="Enter a question to start the chat.")
        user_id = _user_id(clerk_user)

        # Resolve or create the conversation.
        if request.conversation_id:
            conv = (
                db.query(ChatConversation)
                .filter(
                    ChatConversation.id == request.conversation_id,
                    ChatConversation.user_id == user_id,
                    ChatConversation.source == "rag",
                )
                .first()
            )
            if not conv:
                raise HTTPException(status_code=404, detail="Conversation not found")
        else:
            title = (request.query.strip()[:80] + ("…" if len(request.query.strip()) > 80 else "")) or "Study chat"
            conv = ChatConversation(user_id=user_id, title=title, source="rag")
            db.add(conv)
            db.flush()

        # Persist the user's turn.
        db.add(ChatMessage(conversation_id=conv.id, role="user", content=request.query.strip()))
        db.flush()

        document_ids = request.document_ids or ([request.document_id] if request.document_id else [])
        if not document_ids:
            try:
                material_query = (
                    db.query(AssignmentMaterial)
                    .join(Assignment, Assignment.id == AssignmentMaterial.assignment_id)
                    .join(Course, Course.id == Assignment.course_id)
                    .filter(or_(AssignmentMaterial.content.isnot(None), Assignment.description.isnot(None)))
                )
                if user_id != "dev_student_user":
                    material_query = material_query.filter(
                        or_(AssignmentMaterial.user_id == user_id, AssignmentMaterial.user_id == "legacy"),
                        or_(Assignment.user_id == user_id, Assignment.user_id == "legacy"),
                        or_(Course.user_id == user_id, Course.user_id == "legacy"),
                    )
                if request.course_id:
                    material_query = material_query.filter(Course.id == request.course_id)
                user_mats = material_query.limit(1000).all()
                if user_mats:
                    query_terms = {w.lower() for w in re.findall(r"[\w'-]{3,}", request.query)}
                    scored = []
                    for m in user_mats:
                        title_words = {w.lower() for w in re.findall(r"[\w'-]{3,}", m.title or "")}
                        content_snip = (m.content or "")[:3000].lower()
                        score = len(query_terms & title_words) * 3 + sum(1 for t in query_terms if t in content_snip)
                        doc_id = m.drive_file_id or str(m.id)
                        scored.append((score, doc_id))
                    scored.sort(key=lambda x: -x[0])
                    matched = [doc_id for score, doc_id in scored if score > 0]
                    document_ids = matched[:5] if matched else [doc_id for _, doc_id in scored[:5]]
            except Exception as e:
                logger.warning(f"RAG auto-retrieval fallback error: {e}")

        # Only read / chunk the documents the user selected or auto-retrieved candidates.
        materials = _read_materials(db, document_ids, user_id=user_id)
        # Build context: conversation history first, then full text of each
        # selected document, then top retrieved passages for precise grounding.
        context_parts = []
        if request.history:
            history_lines = "\n".join(
                f"{(h.get('role') or 'user').upper()}: {h.get('text', '')}"
                for h in (request.history or [])[-10:]
            )
            context_parts.append(f"CONVERSATION HISTORY:\n{history_lines}")
        if request.academic_context:
            context_parts.append(f"User academic context: {request.academic_context}")
        if request.syllabus:
            context_parts.append(f"Exam syllabus: {request.syllabus[:12000]}")
        if not any((item.get("content") or "").strip() for item in materials):
            context_parts.append("No extracted text was found in the selected saved course sources. Do not imply that a source supports an answer; say when the saved materials do not contain usable text and label any general explanation clearly.")
        max_total_chars = 36000
        per_doc_limit = max(1500, max_total_chars // max(len(materials), 1))
        for item in materials:
            snippet = (item.get('content') or '').strip()
            context_parts.append(
                f"SOURCE DOCUMENT: {item['title']} ({item['id']})\n"
                f"CONTENT:\n{snippet[:per_doc_limit] if snippet else '[Metadata only / no text body extracted]'}"
            )
        context_parts.extend(_retrieve_passages(materials, request.query, limit=8))
        system_prompt = (
            "You are an expert academic tutor and university study assistant. "
            "Your goal is to help the student excel in their courses, master challenging concepts, "
            "solve academic problems, and prepare high-yield study materials (such as revision summaries, "
            "cheat sheets, exam prep guides, formula lists, code explanations, and practice questions).\n\n"
            "Key instructions:\n"
            "1. When source documents or syllabus content are provided in the context, ground your answers directly "
            "in those materials and cite specific topics, formulas, or methods from them.\n"
            "2. When asked to prepare study materials, deliver rigorous, well-organized, and thorough content "
            "with markdown headings, clear bullet points, mathematical notations ($...$), and code snippets.\n"
            "3. Answer questions directly, step-by-step, and in depth. Never refuse or give vague non-answers.\n"
            "4. If specific course materials do not cover a requested topic, clearly say so, then give a useful "
            "general academic explanation and label it as general knowledge rather than course-source content. "
            "Never claim a source supports information when its saved text is missing or irrelevant."
        )
        user_prompt = f"Query: {request.query}\n\nContext:\n" + "\n\n".join(context_parts)
        # Call Groq LLM (use chat model defined in settings)
        answer = _call_groq(
            prompt=user_prompt,
            system_prompt=system_prompt,
            model=settings.groq_chat_model
        )

        # Persist the assistant's turn.
        db.add(ChatMessage(conversation_id=conv.id, role="assistant", content=answer))
        conv.updated_at = func.now()
        db.commit()

        messages = (
            db.query(ChatMessage)
            .filter(ChatMessage.conversation_id == conv.id)
            .order_by(ChatMessage.created_at.asc())
            .all()
        )
        return {
            "answer": answer,
            "conversation_id": conv.id,
            "messages": [
                {"id": m.id, "role": m.role, "content": m.content, "created_at": m.created_at}
                for m in messages
            ],
            "materials": [{k: v for k, v in item.items() if k != "content"} for item in materials]
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
