from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
import re
import io
from sqlalchemy import or_
from app.db.database import get_db
from app.integrations.google_drive import get_drive_service
from app.core.config import settings
from app.services.ai_solution import _call_groq
from app.db.models import AssignmentMaterial, Assignment, Course

router = APIRouter(prefix="/rag", tags=["RAG"])

class ChatRequest(BaseModel):
    document_id: str | None = None
    document_ids: list[str] = Field(default_factory=list, max_length=12)
    query: str
    syllabus: str | None = None
    # Optional academic context (e.g., CGPA) that can be used in the answer
    academic_context: dict | None = None


class StudyPlanRequest(BaseModel):
    syllabus: str = Field(min_length=10, max_length=12000)
    document_ids: list[str] = Field(default_factory=list, max_length=12)
    exam_title: str | None = Field(default=None, max_length=300)


@router.get("/materials")
def get_classroom_materials(limit: int = 100, db=Depends(get_db)):
    rows = (db.query(AssignmentMaterial, Assignment, Course).join(Assignment, Assignment.id == AssignmentMaterial.assignment_id)
            .join(Course, Course.id == Assignment.course_id)
            .filter(AssignmentMaterial.drive_file_id.isnot(None))
            .filter(or_(AssignmentMaterial.mime_type == "application/vnd.google-apps.document", AssignmentMaterial.mime_type == "application/pdf", AssignmentMaterial.mime_type.like("text/%"), AssignmentMaterial.mime_type.is_(None)))
            .order_by(AssignmentMaterial.created_at.desc()).limit(min(max(limit, 1), 200)).all())
    seen, result = set(), []
    for material, assignment, course in rows:
        if material.drive_file_id in seen:
            continue
        seen.add(material.drive_file_id)
        result.append({"id": material.drive_file_id, "title": material.title or assignment.title, "course_id": assignment.course_id, "course_name": course.name, "assignment": assignment.title, "mime_type": material.mime_type, "url": material.url})
    return result


def _read_materials(db, document_ids: list[str]) -> list[dict]:
    if not document_ids:
        return []
    
    materials = []
    drive_service = None
    try:
        drive_service = get_drive_service(db)
    except Exception as e:
        logger.warning(f"Could not load Google Drive service for RAG: {e}")

    for document_id in dict.fromkeys(document_ids):
        content = ""
        title = "Course material"
        url = None

        if drive_service:
            try:
                meta = drive_service.files().get(fileId=document_id, fields="id,name,mimeType,webViewLink").execute()
                title = meta.get("name", "Course material")
                url = meta.get("webViewLink")
                mime = meta.get("mimeType", "")
                if mime == "application/vnd.google-apps.document":
                    data = drive_service.files().export_media(fileId=document_id, mimeType="text/plain").execute()
                    content = data.decode("utf-8", errors="ignore") if isinstance(data, bytes) else str(data)
                elif mime == "application/pdf":
                    data = drive_service.files().get_media(fileId=document_id).execute()
                    from pypdf import PdfReader
                    pdf = PdfReader(io.BytesIO(data if isinstance(data, bytes) else bytes(data)))
                    content = "\n".join(page.extract_text() or "" for page in pdf.pages)
                elif mime.startswith("text/"):
                    data = drive_service.files().get_media(fileId=document_id).execute()
                    content = data.decode("utf-8", errors="ignore") if isinstance(data, bytes) else str(data)
            except Exception as e:
                logger.warning(f"Drive API fetch failed for {document_id}: {e}")

        # If content wasn't fetched from Drive, fall back to DB AssignmentMaterial record
        if not content:
            mat_row = db.query(AssignmentMaterial).filter(
                (AssignmentMaterial.drive_file_id == document_id) | (AssignmentMaterial.id == (int(document_id) if document_id.isdigit() else -1))
            ).first()
            if mat_row:
                title = mat_row.title or title
                url = mat_row.url or url
                content = f"Material: {mat_row.title}\nLink: {mat_row.url}"

        if title or content:
            materials.append({"id": document_id, "title": title, "url": url, "content": content[:7000]})

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


@router.post("/study-plan")
async def create_study_plan(request: StudyPlanRequest, db=Depends(get_db)):
    """Build an exam study plan grounded in the pasted syllabus and selected Drive materials."""
    try:
        materials = _read_materials(db, request.document_ids)
        material_context = "\n\n".join(f"MATERIAL: {item['title']}\n{item['content']}" for item in materials)
        prompt = (
            f"Exam: {request.exam_title or 'Upcoming exam'}\n\nSYLLABUS:\n{request.syllabus}\n\n"
            f"GOOGLE CLASSROOM / DRIVE MATERIALS:\n{material_context[:24000] or 'No readable selected materials.'}\n\n"
            "Create a practical study plan. Identify syllabus topics, connect each to relevant material, "
            "sequence sessions, include active-recall practice and a final review. Clearly mark topics "
            "not supported by the provided materials. Return readable Markdown with a brief coverage summary."
        )
        plan = _call_groq(prompt=prompt, system_prompt="You are an academic study planner. Ground claims in supplied material and do not invent course content.", model=settings.groq_chat_model, max_tokens=3000)
        return {"plan": plan, "materials": [{k: v for k, v in item.items() if k != "content"} for item in materials]}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Could not generate the study plan: {e}") from e

@router.post("/chat")
async def rag_chat(request: ChatRequest, db=Depends(get_db)):
    """Retrieve a Google Drive document and answer the user's query.
    This implementation performs a simple full‑text retrieval (no vector store) and
    leverages the Groq LLM via the existing `_call_groq` helper.
    """
    try:
        if not request.query.strip():
            raise HTTPException(status_code=422, detail="Enter a question to start the chat.")
        drive_service = get_drive_service(db)
        document_ids = request.document_ids or ([request.document_id] if request.document_id else [])
        materials = _read_materials(db, document_ids)
        # Build a prompt for the LLM
        context_parts = []
        if request.academic_context:
            context_parts.append(f"User academic context: {request.academic_context}")
        if request.syllabus:
            context_parts.append(f"Exam syllabus: {request.syllabus[:12000]}")
        context_parts.extend(_retrieve_passages(materials, request.query))
        system_prompt = "You are a helpful academic assistant. Answer from the supplied syllabus and course materials. Say when they do not contain enough evidence."
        user_prompt = f"Query: {request.query}\n\nContext:\n" + "\n".join(context_parts)
        # Call Groq LLM (use chat model defined in settings)
        answer = _call_groq(
            prompt=user_prompt,
            system_prompt=system_prompt,
            model=settings.groq_chat_model
        )
        return {
            "answer": answer,
            "materials": [{k: v for k, v in item.items() if k != "content"} for item in materials]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
