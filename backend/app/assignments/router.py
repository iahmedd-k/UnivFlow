from typing import List, Optional
from uuid import UUID
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import Assignment, AssignmentMaterial, Course, Setting, Submission, SubmissionState, AssignmentStatus
from app.assignments.schemas.assignment import (
    AssignmentRecord, ExtractedRequirements, SolutionPackage,
    GoogleDocInfo, SubmissionReceipt, ApproveRequest, ChangesRequest,
    AutoApprovalConfig, AutoApprovalConfigRequest, AssignmentReviewResponse,
    ApprovalMode, DocumentFetchRequest
)
from app.assignments.services.assignment_service import AssignmentService
from app.auth.clerk_auth import get_current_user_optional
from app.core.config import settings

router = APIRouter(prefix="/assignments", tags=["assignments"])

# Dependency injection
assignment_service: AssignmentService = None


def _authenticated_user_id(user: Optional[dict]) -> str:
    user_id = str((user or {}).get("id") or "")
    if user_id:
        return user_id
    if settings.environment == "development":
        return "dev_student_user"
    raise HTTPException(status_code=401, detail="Sign in to access assignments.")


def get_assignment_service(db: Session = Depends(get_db)) -> AssignmentService:
    global assignment_service
    if assignment_service is not None:
        return assignment_service
    try:
        from app.assignments.services.document_parser import DocumentParserFactory
        from app.assignments.services.requirements_extractor import RequirementsExtractor
        from app.assignments.services.solution_generator import SolutionGenerator
        from app.google_docs.template_engine import GoogleDocsTemplateEngine
        from app.assignments.services.submission_service import SubmissionService
        from app.services.google_docs import get_google_docs_service

        docs_svc = get_google_docs_service(db)
        return AssignmentService(
            document_parser=DocumentParserFactory(),
            requirements_extractor=RequirementsExtractor(),
            solution_generator=SolutionGenerator(),
            template_engine=GoogleDocsTemplateEngine(docs_svc) if docs_svc else None,
            submission_service=SubmissionService(),
            db_session=db
        )
    except Exception:
        return assignment_service


# ============================================================
# CORE ASSIGNMENT ENDPOINTS
# ============================================================

@router.get("", response_model=List[dict])
@router.get("/", response_model=List[dict])
def list_assignments(
    status: Optional[str] = Query(None),
    since: Optional[str] = Query(None),
    course_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional),
):
    """
    Fast DB-first assignments endpoint with course metadata and attached materials joined.
    Returns in < 30ms without blocking on external Google API calls.
    """
    # Resolve semester start date filter (current semester boundary)
    since_dt = None
    if since:
        try:
            val = since.strip().replace('"', '')
            if len(val) == 10:
                since_dt = datetime.fromisoformat(f"{val}T00:00:00+00:00")
            else:
                since_dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
        except Exception:
            pass
    user_id = _authenticated_user_id(clerk_user)
    if not since_dt:
        sem_setting = db.query(Setting).filter(
            Setting.key == f"classroom:{user_id}:semester_start_date"
        ).first()
        if sem_setting and sem_setting.value:
            try:
                val = sem_setting.value.strip().replace('"', '')
                if len(val) == 10:
                    since_dt = datetime.fromisoformat(f"{val}T00:00:00+00:00")
                else:
                    since_dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
            except Exception:
                pass
    if not since_dt:
        now = datetime.now(timezone.utc)
        year = now.year
        if now.month >= 8:
            since_dt = datetime(year, 9, 1, 0, 0, 0, tzinfo=timezone.utc)
        else:
            since_dt = datetime(year, 2, 1, 0, 0, 0, tzinfo=timezone.utc)

    query = (
        db.query(Assignment, Course, Submission)
        .outerjoin(Course, Assignment.course_id == Course.id)
        .outerjoin(Submission, Submission.assignment_id == Assignment.id)
        .filter(
            Assignment.user_id == user_id,
            Course.user_id == user_id,
        )
        .filter(
            (Assignment.due_at >= since_dt) | 
            (Assignment.due_at.is_(None) & (Assignment.created_at >= since_dt))
        )
    )
    
    if course_id:
        query = query.filter(Assignment.course_id == course_id)

    if status and status != "all":
        status_lower = status.lower()
        if status_lower == "quizzes":
            query = query.filter(Assignment.is_quiz == True)
        elif status_lower == "assignments":
            query = query.filter(Assignment.is_quiz == False)
        elif status_lower == "submitted":
            query = query.filter(
                (Assignment.submission_state.in_([SubmissionState.TURNED_IN, SubmissionState.RETURNED])) |
                (Assignment.status.in_([AssignmentStatus.SUBMITTED, AssignmentStatus.APPROVED])) |
                (Submission.submission_state.in_([SubmissionState.TURNED_IN, SubmissionState.RETURNED]))
            )
        elif status_lower == "missing":
            now = datetime.now(timezone.utc)
            query = query.filter(
                (Assignment.due_at < now) & 
                ((Assignment.submission_state != SubmissionState.TURNED_IN) | Assignment.submission_state.is_(None)) &
                ((Assignment.status.notin_([AssignmentStatus.SUBMITTED, AssignmentStatus.APPROVED])) | Assignment.status.is_(None)) &
                ((Submission.submission_state != SubmissionState.TURNED_IN) | Submission.submission_state.is_(None))
            )
        elif status_lower == "open":
            now = datetime.now(timezone.utc)
            query = query.filter(
                (Assignment.due_at >= now) | (Assignment.due_at.is_(None))
            )

    results = query.order_by(Assignment.due_at.asc().nullslast()).all()
    if not results:
        return []

    # Batch load all materials for these assignments in 1 query
    assignment_ids = [a.id for a, c, s in results]
    materials_by_assignment = {}
    if assignment_ids:
        mats = db.query(AssignmentMaterial).filter(AssignmentMaterial.assignment_id.in_(assignment_ids)).all()
        for m in mats:
            materials_by_assignment.setdefault(m.assignment_id, []).append({
                "id": m.id,
                "material_type": m.material_type,
                "title": m.title or "Attachment",
                "url": m.url,
                "drive_file_id": m.drive_file_id,
                "mime_type": m.mime_type,
            })

    output = []
    for a, c, submission in results:
        output.append({
            "id": a.id,
            "external_id": a.external_id,
            "course_id": a.course_id,
            "course_name": c.name if c else "General Course",
            "course_code": (c.name.split()[0] if c and c.name else ""),
            "title": a.title,
            "work_type": a.work_type,
            "is_quiz": a.is_quiz,
            "description": a.description,
            "materials": materials_by_assignment.get(a.id, []),
            "due_at": a.due_at.isoformat() if a.due_at else (a.due_date.isoformat() if a.due_date else None),
            "due_date": a.due_date.isoformat() if a.due_date else None,
            "url": a.url,
            "state": a.state.value if a.state else None,
            "submission_state": a.submission_state.value if a.submission_state else None,
            "status": a.status.value if a.status else (submission.submission_state.value if submission and submission.submission_state else "pending"),
            "google_doc_id": submission.google_doc_id if submission else None,
        })
    return output


@router.get("/{assignment_id}")
def get_assignment_by_id(
    assignment_id: int,
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional),
):
    """Retrieve single assignment with course and materials."""
    user_id = _authenticated_user_id(clerk_user)
    result = (
        db.query(Assignment, Course, Submission)
        .outerjoin(Course, Assignment.course_id == Course.id)
        .outerjoin(Submission, Submission.assignment_id == Assignment.id)
        .filter(Assignment.id == assignment_id, Assignment.user_id == user_id)
        .first()
    )
    if not result:
        raise HTTPException(status_code=404, detail="Assignment not found")
    
    a, c, submission = result
    mats = db.query(AssignmentMaterial).filter(AssignmentMaterial.assignment_id == a.id).all()
    materials = [{
        "id": m.id,
        "material_type": m.material_type,
        "title": m.title or "Attachment",
        "url": m.url,
        "drive_file_id": m.drive_file_id,
        "mime_type": m.mime_type,
    } for m in mats]

    return {
        "id": a.id,
        "external_id": a.external_id,
        "course_id": a.course_id,
        "course_name": c.name if c else "General Course",
        "course_code": (c.name.split()[0] if c and c.name else ""),
        "title": a.title,
        "work_type": a.work_type,
        "is_quiz": a.is_quiz,
        "description": a.description,
        "materials": materials,
        "due_at": a.due_at.isoformat() if a.due_at else (a.due_date.isoformat() if a.due_date else None),
        "due_date": a.due_date.isoformat() if a.due_date else None,
        "url": a.url,
        "state": a.state.value if a.state else None,
        "submission_state": a.submission_state.value if a.submission_state else None,
        "status": a.status.value if a.status else (submission.submission_state.value if submission and submission.submission_state else "pending"),
        "google_doc_id": submission.google_doc_id if submission else None,
    }


@router.post("/ingest", response_model=AssignmentRecord)
async def ingest_assignment(
    request: dict,
    background_tasks: BackgroundTasks,
    service: AssignmentService = Depends(get_assignment_service)
):
    """
    Ingest new assignment from portal detection.
    
    Expected request:
    {
        "user_id": "uuid",
        "portal_id": "uuid", 
        "external_id": "portal_assignment_id",
        "title": "Assignment Title",
        "course_code": "CS101",
        "course_name": "Introduction to CS",
        "due_date": "2026-01-30T23:59:00Z",
        "description": "...",
        "source_document_urls": ["https://..."],
        "source_google_doc_ids": ["doc_id_1"],
        "instructor": "Prof. Smith",
        "semester": "Spring 2026",
        "section": "001"
    }
    """
    try:
        assignment = await service.ingest_assignment(**request)
        return assignment
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _find_assignment(db: Session, assignment_id: str | int, user_id: str) -> Optional[Assignment]:
    try:
        aid = int(assignment_id)
        res = db.query(Assignment).filter(
            Assignment.id == aid,
            Assignment.user_id == user_id,
        ).first()
        if res:
            return res
    except (ValueError, TypeError):
        pass
    return db.query(Assignment).filter(
        Assignment.external_id == str(assignment_id),
        Assignment.user_id == user_id,
    ).first()


TUTOR_SYSTEM_PROMPT = """
You are a patient academic tutor helping a student understand an assignment they have already been given. You are not completing the assignment for them.

You will receive:
- The assignment title, course, and instructions/description
- The rubric criteria, if available
- The running chat history with the student

Your job:
1. Break the assignment into the sub-requirements it's actually asking for, in plain language.
2. When the student asks "what does X mean" or "how do I approach Y", explain the underlying concept, method, or pattern — using a DIFFERENT example than their assignment so they still have to do the transfer themselves.
3. When the student shares their own draft/code/argument, react to THAT text: point out gaps, logic errors, unclear reasoning, or rubric items it doesn't yet satisfy. Ask questions that lead them to the fix rather than stating the fixed version.
4. If the student directly asks you to "just write it," "give me the answer," or "generate the essay/code/solution," decline and redirect: offer to explain the relevant concept or review their attempt instead.

Hard constraints:
- Never output a complete essay, proof, program, or answer set that matches the assignment's own deliverable, even partially.
- Never generate content formatted so it could be pasted directly into a submission.
- Tone: encouraging, concrete, Socratic where useful. Short answers over lectures. Always tie explanations back to what the rubric is actually asking for.
""".strip()

REVIEW_SYSTEM_PROMPT = """
You are a pre-submission reviewer. The student has uploaded or pasted a draft they wrote themselves and wants a check before turning it in.

You will receive:
- The assignment's stated requirements and rubric criteria
- The submission format / deliverable type expected
- The student's own draft text or file contents

Your job — produce a structured review with:
1. requirement_coverage: for each rubric/requirement item, "met" / "partial" / "missing", with a one-line reason pointing at the specific part of their draft (or its absence).
2. issues: a list of concrete problems — grammar, unclear citations, formatting that doesn't match submission_format, logic gaps, missing sections — each with a short description of WHERE and WHY it's an issue, not a rewritten replacement.
3. citation_check: flag any claim, quote, or figure that looks unattributed or inconsistently formatted, without inventing what the citation should say.
4. summary: one paragraph, plain language, on whether this looks ready to submit or needs another pass.

Hard constraints:
- Do not rewrite sentences, paragraphs, code blocks, or proofs for the student. Describe the problem; let them fix it.
- Do not produce a "corrected version" of the file, in full or in part.

Output valid JSON matching:
{
  "requirement_coverage": [{ "requirement": "...", "status": "met"|"partial"|"missing", "reason": "..." }],
  "issues": [{ "type": "...", "location": "...", "description": "..." }],
  "citation_check": [{ "excerpt": "...", "concern": "..." }],
  "summary": "..."
}
""".strip()


@router.get("/{assignment_id}/breakdown", response_model=dict)
def get_assignment_breakdown(
    assignment_id: str,
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional),
):
    """Get structured requirements breakdown for the assignment tutor panel"""
    import json
    import re
    from app.services.ai_solution import _call_groq

    user_id = _authenticated_user_id(clerk_user)
    assignment = _find_assignment(db, assignment_id, user_id)
    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")

    # Check if we have cached breakdown in Setting table
    cache_key = f"assignment_breakdown_{assignment.id}"
    cached = db.query(Setting).filter(Setting.key == cache_key).first()
    if cached and cached.value:
        try:
            return json.loads(cached.value)
        except Exception:
            pass

    # Extract requirements via Groq
    prompt = f"""Assignment Title: {assignment.title}
Instructions: {assignment.description or 'No explicit instructions.'}

Extract 3 to 6 distinct sub-requirements or tasks the student must complete.
Return JSON ONLY:
{{
  "requirements": [
    {{ "id": "req-1", "description": "Clear action-oriented requirement description", "priority": "high"|"medium"|"low" }}
  ]
}}"""
    try:
        raw = _call_groq(prompt=prompt, system_prompt="You are an academic curriculum parser. Extract clean requirements in JSON format only.", max_tokens=1000)
        json_match = re.search(r"\{[\s\S]*\}", raw)
        if json_match:
            data = json.loads(json_match.group(0))
            if "requirements" in data and isinstance(data["requirements"], list):
                setting = Setting(key=cache_key, value=json.dumps(data), description="Assignment requirements breakdown")
                db.merge(setting)
                db.commit()
                return data
    except Exception as e:
        logger.warning(f"Could not generate AI breakdown for {assignment_id}: {e}")

    # Fallback heuristic breakdown
    lines = [line.strip("- *• \t") for line in (assignment.description or "").splitlines() if len(line.strip()) > 10]
    fallback_reqs = [{"id": f"req-{i+1}", "description": line, "priority": "medium"} for i, line in enumerate(lines[:5])] or [
        {"id": "req-1", "description": f"Complete all requirements for {assignment.title}", "priority": "high"}
    ]
    return {"requirements": fallback_reqs}


class TutorChatRequest(BaseModel):
    message: str
    history: Optional[List[dict]] = None


@router.post("/{assignment_id}/tutor", response_model=dict)
def ask_assignment_tutor(
    assignment_id: str,
    payload: TutorChatRequest,
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional),
):
    """AI Tutor chat answering student questions and providing Socratic guidance"""
    from app.services.ai_solution import _call_groq

    user_id = _authenticated_user_id(clerk_user)
    assignment = _find_assignment(db, assignment_id, user_id)
    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")

    course = db.query(Course).filter(
        Course.id == assignment.course_id,
        Course.user_id == user_id,
    ).first()
    materials = db.query(AssignmentMaterial).filter(AssignmentMaterial.assignment_id == assignment.id).all()
    mat_summary = "\n".join(f"- {m.title} ({m.material_type})" for m in materials) or "None"

    context_prompt = f"""ASSIGNMENT CONTEXT:
Course: {course.name if course else 'General'}
Title: {assignment.title}
Instructions: {assignment.description or 'No explicit instructions provided.'}
Materials Attached: {mat_summary}

STUDENT MESSAGE: {payload.message}
"""
    if payload.history:
        recent_history = "\n".join(f"{h.get('role', 'user').upper()}: {h.get('text', '')}" for h in payload.history[-6:])
        context_prompt = f"CHAT HISTORY:\n{recent_history}\n\n" + context_prompt

    try:
        reply = _call_groq(
            prompt=context_prompt,
            system_prompt=TUTOR_SYSTEM_PROMPT,
            temperature=0.4,
            max_tokens=2000
        )
        return {"text": reply}
    except Exception as e:
        logger.error(f"Tutor chat error for {assignment_id}: {e}")
        raise HTTPException(status_code=502, detail=f"Tutor service error: {str(e)}")


class DraftReviewRequest(BaseModel):
    text: Optional[str] = ""


@router.post("/{assignment_id}/review", response_model=dict)
@router.post("/{assignment_id}/review-draft", response_model=dict)
async def review_assignment_draft(
    assignment_id: str,
    payload: Optional[DraftReviewRequest] = None,
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional),
):
    """Pre-submission rubric and requirement checker for student drafts"""
    import json
    import re
    from app.services.ai_solution import _call_groq

    assignment = _find_assignment(db, assignment_id, _authenticated_user_id(clerk_user))
    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")

    draft_text = (payload.text if payload and payload.text else "").strip()
    if not draft_text:
        raise HTTPException(status_code=422, detail="Provide draft text to review.")

    prompt = f"""ASSIGNMENT REQUIREMENTS:
Title: {assignment.title}
Instructions: {assignment.description or 'Standard academic assignment.'}

STUDENT DRAFT TO REVIEW:
{draft_text[:18000]}
"""
    try:
        raw = _call_groq(
            prompt=prompt,
            system_prompt=REVIEW_SYSTEM_PROMPT,
            temperature=0.2,
            max_tokens=2500
        )
        json_match = re.search(r"\{[\s\S]*\}", raw)
        if json_match:
            return json.loads(json_match.group(0))
        return {
            "requirement_coverage": [{"requirement": "Overall Submission", "status": "met", "reason": "Draft submitted"}],
            "issues": [],
            "citation_check": [],
            "summary": raw
        }
    except Exception as e:
        logger.error(f"Review error for {assignment_id}: {e}")
        raise HTTPException(status_code=502, detail=f"Review service error: {str(e)}")


class ScheduleTurnInRequest(BaseModel):
    enabled: bool = True
    minutes_before_due: int = 60
    template_id: Optional[int] = None


@router.post("/{assignment_id}/schedule-turn-in", response_model=dict)
def schedule_assignment_turn_in(
    assignment_id: str,
    payload: ScheduleTurnInRequest,
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional),
):
    """Schedule turn-in only when a safe execution path is available."""
    user_id = _authenticated_user_id(clerk_user)
    assignment = _find_assignment(db, assignment_id, user_id)
    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")

    key = f"schedule_turnin_{user_id}_{assignment.id}"
    if not payload.enabled:
        setting = db.query(Setting).filter(Setting.key == key).first()
        if setting:
            db.delete(setting)
            db.commit()
        return {
            "status": "cancelled",
            "assignment_id": assignment.id,
            "message": "Turn-in schedule cancelled."
        }

    raise HTTPException(
        status_code=501,
        detail=(
            "Automated turn-in is unavailable; no schedule was saved. The current "
            "route has no authenticated-user dependency, and the assignment, submission "
            "approval, and Google credential records are not scoped to an authenticated "
            "user. It therefore cannot verify that the requesting user approved this "
            "work or validate/refresh that user's Google credential. The available "
            "AssignmentService uses a separate async assignment model and placeholder "
            "credential loading. A user-scoped, sync-compatible execution path and "
            "durable submission idempotency state are required before scheduling can "
            "be enabled."
        ),
    )


# ============================================================
# APPROVAL WORKFLOW ENDPOINTS
# ============================================================

@router.post("/{assignment_id}/approve", response_model=AssignmentRecord)
async def approve_assignment(
    assignment_id: UUID,
    request: ApproveRequest,
    service: AssignmentService = Depends(get_assignment_service)
):
    """
    Approve assignment for submission.
    
    Request:
    {
        "mode": "MANUAL|AUTO",
        "changes_requested": "Optional feedback if requesting changes",
        "auto_approve_future": true
    }
    """
    try:
        return await service.approve_assignment(assignment_id, request)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{assignment_id}/request-changes", response_model=AssignmentRecord)
async def request_changes(
    assignment_id: UUID,
    request: ChangesRequest,
    service: AssignmentService = Depends(get_assignment_service)
):
    """
    Request changes to generated solution.
    
    Request:
    {
        "feedback": "Please fix the algorithm complexity",
        "specific_requirements": ["req_1", "req_2"],
        "priority": "HIGH"
    }
    """
    try:
        return await service.request_changes(assignment_id, request)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{assignment_id}/submit", response_model=SubmissionReceipt)
async def manual_submit(
    assignment_id: UUID,
    service: AssignmentService = Depends(get_assignment_service)
):
    """Manually trigger submission after approval."""
    try:
        return await service.submit_assignment(assignment_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# GOOGLE DOC ENDPOINTS
# ============================================================

@router.get("/{assignment_id}/google-doc", response_model=GoogleDocInfo)
async def get_google_doc(
    assignment_id: UUID,
    service: AssignmentService = Depends(get_assignment_service)
):
    """Get Google Doc info for assignment."""
    assignment = await service._get_assignment(assignment_id)
    if not assignment or not assignment.google_doc:
        raise HTTPException(status_code=404, detail="Google Doc not found")
    return assignment.google_doc


@router.put("/{assignment_id}/google-doc", response_model=GoogleDocInfo)
async def update_google_doc(
    assignment_id: UUID,
    request: dict,
    service: AssignmentService = Depends(get_assignment_service)
):
    """Update Google Doc content (user edits before approval)."""
    assignment = await service._get_assignment(assignment_id)
    if not assignment or not assignment.google_doc:
        raise HTTPException(status_code=404, detail="Google Doc not found")
    
    # Update doc with user changes
    updated = await service.template_engine.update_document_content(
        assignment.google_doc.doc_id,
        request.get("replacement_map", {})
    )
    
    return assignment.google_doc


# ============================================================
# AUTO-APPROVAL CONFIG ENDPOINTS
# ============================================================

@router.get("/auto-approval/config", response_model=AutoApprovalConfig)
async def get_auto_approval_config(
    user_id: UUID = Query(...),
    service: AssignmentService = Depends(get_assignment_service)
):
    """Get user's auto-approval configuration."""
    config = await service.get_auto_approval_config(user_id)
    return config or AutoApprovalConfig()


@router.put("/auto-approval/config", response_model=AutoApprovalConfig)
async def update_auto_approval_config(
    user_id: UUID,
    config: AutoApprovalConfigRequest,
    service: AssignmentService = Depends(get_assignment_service)
):
    """Update user's auto-approval configuration."""
    return await service.update_auto_approval_config(user_id, config)


# ============================================================
# DOCUMENT PROCESSING ENDPOINTS
# ============================================================

@router.post("/parse-documents")
async def parse_documents(
    request: DocumentFetchRequest,
    service: AssignmentService = Depends(get_assignment_service)
):
    """Parse documents from URLs or Google Doc IDs."""
    results = []
    
    # Parse Google Docs
    for doc_id in request.google_doc_ids:
        try:
            parsed = await service.document_parser.parse_google_doc(doc_id)
            results.append({"doc_id": doc_id, "success": True, "content": parsed.content[:500]})
        except Exception as e:
            results.append({"doc_id": doc_id, "success": False, "error": str(e)})
    
    # Parse URLs
    for url in request.urls:
        try:
            # In production: fetch URL and parse
            results.append({"url": url, "success": True, "note": "URL parsing not implemented"})
        except Exception as e:
            results.append({"url": url, "success": False, "error": str(e)})
    
    return {"results": results}


def _get_semester_start_dt(db: Session, override: Optional[str] = None) -> Optional[datetime]:
    val = override
    if not val:
        setting = db.query(Setting).filter(Setting.key == "semester_start_date").first()
        if setting and setting.value:
            val = setting.value.strip().replace('"', '')
    if val:
        try:
            if len(val) == 10:
                dt = datetime.fromisoformat(f"{val}T00:00:00+00:00")
            else:
                dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            pass
    return None




@router.get("/{assignment_id}/submission-history", response_model=List[SubmissionReceipt])
async def get_submission_history(
    assignment_id: UUID,
    service: AssignmentService = Depends(get_assignment_service)
):
    """Get submission history for assignment."""
    assignment = await service._get_assignment(assignment_id)
    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")
    
    history = []
    if assignment.submission_receipt:
        history.append(assignment.submission_receipt)
    
    return history


# ============================================================
from fastapi import Header

@router.post("/webhook/portal/{portal_id}")
async def portal_webhook(
    portal_id: UUID,
    payload: dict,
    background_tasks: BackgroundTasks,
    x_webhook_secret: Optional[str] = Header(None, alias="X-Webhook-Secret"),
    service: AssignmentService = Depends(get_assignment_service),
    db: Session = Depends(get_db)
):
    """
    Receive webhook from LMS portal with security secret validation.
    """
    # Verify webhook secret if configured in environment
    expected_secret = getattr(settings, "portal_webhook_secret", None)
    if expected_secret and x_webhook_secret != expected_secret:
        raise HTTPException(status_code=401, detail="Invalid webhook signature or secret header")
    
    event_type = payload.get("event_type")
    if event_type in ["ASSIGNMENT_CREATED", "ASSIGNMENT_UPDATED", "ASSIGNMENT_PUBLISHED"]:
        assignment_data = payload.get("assignment", {})
        assignment_data["portal_id"] = str(portal_id)
        if service:
            background_tasks.add_task(service.ingest_assignment, **assignment_data)
    
    return {"status": "received"}


# ============================================================
# HEALTH & DEBUG
# ============================================================

@router.get("/health/check")
async def health_check():
    return {"status": "healthy", "service": "assignments"}
