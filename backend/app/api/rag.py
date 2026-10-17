import logging
import re
import io
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import List, Optional
from sqlalchemy import or_, func
from app.db.database import get_db
from app.integrations.google_drive import get_drive_service
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
    document_ids: list[str] = Field(default_factory=list, max_length=12)
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
    document_ids: list[str] = Field(default_factory=list, max_length=12)
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


@router.get("/materials")
def get_classroom_materials(limit: int = 100, db=Depends(get_db)):
    rows = (db.query(AssignmentMaterial, Assignment, Course).join(Assignment, Assignment.id == AssignmentMaterial.assignment_id)
            .join(Course, Course.id == Assignment.course_id)
            .filter(
                or_(
                    # Google Drive materials (content fetched lazily from Drive on read)
                    and_(AssignmentMaterial.drive_file_id.isnot(None),
                         AssignmentMaterial.mime_type.in_(
                             ["application/vnd.google-apps.document", "application/pdf"]
                         ) | AssignmentMaterial.mime_type.like("text/%")),
                    # Local uploads (content already extracted and stored in DB)
                    and_(AssignmentMaterial.drive_file_id.is_(None),
                         AssignmentMaterial.content.isnot(None))
                )
            )
            .order_by(AssignmentMaterial.created_at.desc()).limit(min(max(limit, 1), 200)).all())
    seen, result = set(), []
    for material, assignment, course in rows:
        if material.drive_file_id in seen and material.drive_file_id is not None:
            continue
        if material.drive_file_id is not None:
            seen.add(material.drive_file_id)
        result.append({"id": material.drive_file_id or str(material.id), "title": material.title or assignment.title, "course_id": assignment.course_id, "course_name": course.name, "assignment": assignment.title, "mime_type": material.mime_type, "url": material.url})
    return result


def _read_materials(db, document_ids: list[str], max_chars: int = MAX_DOC_CHARS) -> list[dict]:
    if not document_ids:
        return []
    
    materials = []
    drive_service = None
    try:
        drive_service = get_drive_service(db)
    except Exception as e:
        # No Google credential connected: we cannot fetch Drive content.
        # Log once and continue so DB-stored content (local uploads) still works.
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

                # Cache extracted Drive content to DB so subsequent reads don't
                # need to re-fetch from the Drive API.
                if content:
                    try:
                        mat_row = db.query(AssignmentMaterial).filter(
                            AssignmentMaterial.drive_file_id == document_id
                        ).first()
                        if mat_row:
                            mat_row.content = content[:max_chars]
                            mat_row.title = mat_row.title or title
                            mat_row.url = mat_row.url or url
                            db.add(mat_row)
                            db.commit()
                    except Exception as cache_err:
                        db.rollback()
                        logger.warning(f"Could not cache Drive content for {document_id}: {cache_err}")
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
                content = mat_row.content or f"Material: {mat_row.title}\nLink: {mat_row.url}"

        if title or content:
            materials.append({"id": document_id, "title": title, "url": url, "content": content[:max_chars]})

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
        materials = _read_materials(db, request.document_ids)
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


@router.get("/study-plans", response_model=List[dict])
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


@router.get("/study-plans/{plan_id}", response_model=dict)
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


@router.post("/study-plans/{plan_id}/sessions/{session_id}/status", response_model=dict)
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
        # Only read / chunk the documents the user selected - never all documents.
        materials = _read_materials(db, document_ids)
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
        for item in materials:
            context_parts.append(
                f"SOURCE DOCUMENT: {item['title']} ({item['id']})\n"
                f"FULL CONTENT:\n{item['content']}"
            )
        context_parts.extend(_retrieve_passages(materials, request.query, limit=8))
        system_prompt = (
            "You are a helpful academic assistant. Answer from the supplied syllabus and course materials. "
            "You have the FULL text of each selected source document available above - use it to answer "
            "completely and accurately. Say when the materials do not contain enough evidence, and do not "
            "invent sources or citations."
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
