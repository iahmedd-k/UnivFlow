from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime

from app.db.database import get_db
from app.db.repositories import (
    AssignmentRepository,
    AssignmentMaterialRepository,
    AssignmentSolutionRepository,
    SubmissionRepository,
    CourseRepository
)
from app.db.models import (
    Assignment,
    AssignmentMaterial,
    AssignmentSolution,
    Submission,
    Course,
    AssignmentStatus,
    CourseworkState,
    SubmissionState
)

router = APIRouter(prefix="/assignments", tags=["Assignments"])


def assignment_to_dict(a: Assignment) -> dict:
    return {
        "id": a.id,
        "external_id": a.external_id,
        "course_id": a.course_id,
        "title": a.title,
        "description": a.description,
        "created_at": a.created_at,
        "updated_at": a.updated_at,
        "due_at": a.due_at,
        "due_date": a.due_date,
        "url": a.url,
        "state": a.state.value if a.state else None,
        "submission_state": a.submission_state.value if a.submission_state else None,
        "status": a.status.value if a.status else None,
        "last_synced_at": a.last_synced_at,
    }


@router.get("", response_model=List[dict])
def get_assignments(
    status: Optional[str] = Query(None),
    course_id: Optional[int] = Query(None),
    db: Session = Depends(get_db)
):
    repo = AssignmentRepository(db)
    if status:
        assignments = repo.get_by_status(status)
    elif course_id:
        assignments = db.query(Assignment).filter(Assignment.course_id == course_id).order_by(Assignment.due_at.asc().nullslast()).all()
    else:
        assignments = repo.get_all()
    return [assignment_to_dict(a) for a in assignments]


@router.get("/pending-review", response_model=List[dict])
def get_pending_review_assignments(db: Session = Depends(get_db)):
    repo = AssignmentRepository(db)
    assignments = repo.get_pending_review()
    return [assignment_to_dict(a) for a in assignments]


@router.get("/{assignment_id}", response_model=dict)
def get_assignment(assignment_id: int, db: Session = Depends(get_db)):
    repo = AssignmentRepository(db)
    assignment = repo.get_by_id(assignment_id)
    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")
    return assignment_to_dict(assignment)


@router.get("/{assignment_id}/materials", response_model=List[dict])
def get_assignment_materials(assignment_id: int, db: Session = Depends(get_db)):
    repo = AssignmentMaterialRepository(db)
    materials = repo.get_by_assignment(assignment_id)
    return [
        {
            "id": m.id,
            "assignment_id": m.assignment_id,
            "material_type": m.material_type,
            "title": m.title,
            "url": m.url,
            "drive_file_id": m.drive_file_id,
            "mime_type": m.mime_type,
            "content": m.content,
            "created_at": m.created_at,
        }
        for m in materials
    ]


@router.get("/{assignment_id}/solution", response_model=dict)
def get_assignment_solution(assignment_id: int, db: Session = Depends(get_db)):
    repo = AssignmentSolutionRepository(db)
    solution = repo.get_by_assignment(assignment_id)
    if not solution:
        raise HTTPException(status_code=404, detail="Solution not found")
    return {
        "id": solution.id,
        "assignment_id": solution.assignment_id,
        "draft_content": solution.draft_content,
        "validated_content": solution.validated_content,
        "validation_errors": solution.validation_errors,
        "retry_count": solution.retry_count,
        "ai_provider": solution.ai_provider,
        "generated_at": solution.generated_at,
        "validated_at": solution.validated_at,
    }


@router.get("/{assignment_id}/submission", response_model=dict)
def get_assignment_submission(assignment_id: int, db: Session = Depends(get_db)):
    repo = SubmissionRepository(db)
    submission = repo.get_by_assignment(assignment_id)
    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found")
    return {
        "id": submission.id,
        "assignment_id": submission.assignment_id,
        "google_doc_id": submission.google_doc_id,
        "google_drive_file_id": submission.google_drive_file_id,
        "classroom_attachment_id": submission.classroom_attachment_id,
        "attached_at": submission.attached_at,
        "submitted_at": submission.submitted_at,
        "submission_state": submission.submission_state.value if submission.submission_state else None,
        "approved_by_user": submission.approved_by_user,
        "approved_at": submission.approved_at,
        "created_at": submission.created_at,
    }


@router.post("/{assignment_id}/approve", response_model=dict)
def approve_assignment_submission(assignment_id: int, db: Session = Depends(get_db)):
    repo = SubmissionRepository(db)
    submission = repo.get_by_assignment(assignment_id)
    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found")
    submission.approved_by_user = True
    submission.approved_at = datetime.now()
    db.commit()
    db.refresh(submission)
    return {
        "id": submission.id,
        "assignment_id": submission.assignment_id,
        "approved_by_user": submission.approved_by_user,
        "approved_at": submission.approved_at,
    }