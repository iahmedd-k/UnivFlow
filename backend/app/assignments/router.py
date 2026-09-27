from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query
from pydantic import BaseModel

from app.assignments.schemas.assignment import (
    AssignmentRecord, ExtractedRequirements, SolutionPackage,
    GoogleDocInfo, SubmissionReceipt, ApproveRequest, ChangesRequest,
    AutoApprovalConfig, AutoApprovalConfigRequest, AssignmentReviewResponse,
    AssignmentStatus, ApprovalMode, DocumentFetchRequest
)
from app.assignments.services.assignment_service import AssignmentService

router = APIRouter(prefix="/assignments", tags=["assignments"])

# Dependency injection
assignment_service: AssignmentService = None


def get_assignment_service() -> AssignmentService:
    return assignment_service


# ============================================================
# CORE ASSIGNMENT ENDPOINTS
# ============================================================

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


@router.get("/{assignment_id}", response_model=AssignmentRecord)
async def get_assignment(
    assignment_id: UUID,
    service: AssignmentService = Depends(get_assignment_service)
):
    """Get assignment by ID."""
    assignment = await service._get_assignment(assignment_id)
    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")
    return assignment


@router.get("/{assignment_id}/status", response_model=AssignmentStatus)
async def get_assignment_status(
    assignment_id: UUID,
    service: AssignmentService = Depends(get_assignment_service)
):
    """Get assignment processing status."""
    assignment = await service._get_assignment(assignment_id)
    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")
    return assignment.status


@router.get("/{assignment_id}/review", response_model=AssignmentReviewResponse)
async def get_review_data(
    assignment_id: UUID,
    service: AssignmentService = Depends(get_assignment_service)
):
    """Get all data needed for review page."""
    try:
        return await service.get_review_data(assignment_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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


# ============================================================
# LISTING & FILTERING
# ============================================================

@router.get("/", response_model=List[AssignmentRecord])
async def list_assignments(
    user_id: UUID = Query(...),
    status: Optional[AssignmentStatus] = None,
    course_code: Optional[str] = None,
    limit: int = Query(50, le=100),
    offset: int = Query(0, ge=0),
    service: AssignmentService = Depends(get_assignment_service)
):
    """List assignments for a user with filters."""
    # In production: query database with filters
    # This is a placeholder
    return []


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
# WEBHOOK ENDPOINTS (for portal notifications)
# ============================================================

@router.post("/webhook/portal/{portal_id}")
async def portal_webhook(
    portal_id: UUID,
    payload: dict,
    background_tasks: BackgroundTasks,
    service: AssignmentService = Depends(get_assignment_service)
):
    """
    Receive webhook from LMS portal.
    Expected payload varies by portal.
    """
    # Verify webhook signature
    # Parse payload
    # Trigger assignment ingestion
    
    event_type = payload.get("event_type")
    if event_type in ["ASSIGNMENT_CREATED", "ASSIGNMENT_UPDATED", "ASSIGNMENT_PUBLISHED"]:
        assignment_data = payload.get("assignment", {})
        assignment_data["portal_id"] = str(portal_id)
        background_tasks.add_task(service.ingest_assignment, **assignment_data)
    
    return {"status": "received"}


# ============================================================
# HEALTH & DEBUG
# ============================================================

@router.get("/health/check")
async def health_check():
    return {"status": "healthy", "service": "assignments"}