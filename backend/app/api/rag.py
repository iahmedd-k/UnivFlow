import logging
import re
import io
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import List, Optional
from sqlalchemy import or_, and_, func
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
    document_ids: list[str] = Field(default_factory=list, max_length=100)
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


@router.get("/materials")
def get_classroom_materials(
    limit: int = 250,
    course_id: Optional[int] = None,
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
            or_(
                Assignment.user_id == user_id,
                Assignment.user_id == "legacy",
                Course.user_id == user_id,
                Course.user_id == "legacy",
            )
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
        .limit(min(max(limit, 1), 500))
        .all()
    )

    seen, result = set(), []
    for material, assignment, course in rows:
        unique_key = material.drive_file_id or f"mat_{material.id}"
        if unique_key in seen:
            continue
        seen.add(unique_key)
        result.append({
            "id": material.drive_file_id or str(material.id),
            "material_id": material.id,
            "title": material.title or assignment.title or "Untitled document",
            "course_id": course.id,
            "course_name": course.name,
            "assignment": assignment.title,
            "work_type": assignment.work_type or "ASSIGNMENT",
            "mime_type": material.mime_type or "",
            "url": material.url,
            "has_content": bool(material.content),
            "created_at": material.created_at.isoformat() if material.created_at else None,
        })
    return result


def _read_materials(db, document_ids: list[str], max_chars: int = MAX_DOC_CHARS) -> list[dict]:
    if not document_ids:
        return []

    clean_ids = list(dict.fromkeys(document_ids))
    int_ids = [int(x) for x in clean_ids if x.isdigit()]

    # Fetch cached rows from DB first to avoid unnecessary network calls
    db_rows = db.query(AssignmentMaterial).filter(
        or_(
            AssignmentMaterial.drive_file_id.in_(clean_ids),
            AssignmentMaterial.id.in_(int_ids) if int_ids else False
        )
    ).all()

    db_map = {}
    for r in db_rows:
        if r.drive_file_id:
            db_map[r.drive_file_id] = r
        db_map[str(r.id)] = r

    drive_service = None
    needs_drive = any(
        (doc_id in db_map and not db_map[doc_id].content) or (doc_id not in db_map)
        for doc_id in clean_ids
    )
    if needs_drive:
        try:
            drive_service = get_drive_service(db)
        except Exception as e:
            logger.warning(f"Could not load Google Drive service for RAG: {e}")

    materials = []
    for document_id in clean_ids:
        content = ""
        title = "Course material"
        url = None
        mime = ""

        mat_row = db_map.get(document_id)
        if mat_row:
            title = mat_row.title or title
            url = mat_row.url or url
            mime = mat_row.mime_type or ""
            if mat_row.content:
                content = mat_row.content

        if not content and drive_service and document_id:
            try:
                meta = drive_service.files().get(fileId=document_id, fields="id,name,mimeType,webViewLink").execute()
                title = meta.get("name") or title
                url = meta.get("webViewLink") or url
                mime = meta.get("mimeType", "")

                if mime == "application/vnd.google-apps.document":
                    data = drive_service.files().export_media(fileId=document_id, mimeType="text/plain").execute()
                    content = data.decode("utf-8", errors="ignore") if isinstance(data, bytes) else str(data)
                elif mime == "application/vnd.google-apps.presentation":
                    data = drive_service.files().export_media(fileId=document_id, mimeType="text/plain").execute()
                    content = data.decode("utf-8", errors="ignore") if isinstance(data, bytes) else str(data)
                elif mime == "application/vnd.google-apps.spreadsheet":
                    data = drive_service.files().export_media(fileId=document_id, mimeType="text/csv").execute()
                    content = data.decode("utf-8", errors="ignore") if isinstance(data, bytes) else str(data)
                elif mime == "application/pdf" or title.lower().endswith(".pdf"):
                    data = drive_service.files().get_media(fileId=document_id).execute()
                    from pypdf import PdfReader
                    pdf = PdfReader(io.BytesIO(data if isinstance(data, bytes) else bytes(data)))
                    content = "\n".join(page.extract_text() or "" for page in pdf.pages)
                elif mime.startswith("text/") or title.lower().endswith((".txt", ".md", ".py", ".c", ".cpp", ".java", ".h", ".cs", ".json", ".csv", ".html", ".css", ".js", ".ts")):
                    data = drive_service.files().get_media(fileId=document_id).execute()
                    content = data.decode("utf-8", errors="ignore") if isinstance(data, bytes) else str(data)

                if content and mat_row:
                    try:
                        mat_row.content = content[:max_chars]
                        mat_row.title = mat_row.title or title
                        mat_row.url = mat_row.url or url
                        db.add(mat_row)
                        db.commit()
                    except Exception as cache_err:
                        db.rollback()
                        logger.warning(f"Could not cache Drive content for {document_id}: {cache_err}")
            except Exception as e:
                logger.warning(f"Drive fetch failed for {document_id}: {e}")

        if not content and mat_row and mat_row.url:
            content = f"Material Title: {title}\nURL: {mat_row.url}"

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
        if not document_ids:
            try:
                user_mats = db.query(AssignmentMaterial).filter(
                    (AssignmentMaterial.user_id == user_id) | (AssignmentMaterial.user_id == "legacy")
                ).all()
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
            "4. If specific course materials do not cover a requested topic, use your authoritative academic "
            "knowledge to provide a complete, crystal-clear explanation, noting that the student can attach "
            "specific slides or notes for custom alignment."
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
