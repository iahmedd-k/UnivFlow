from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload, selectinload
from typing import List, Optional
from datetime import datetime, timezone

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
    SubmissionState,
    Setting
)

router = APIRouter(prefix="/assignments", tags=["Assignments"])


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


from collections import defaultdict

def assignment_to_dict(
    a: Assignment,
    course_name: Optional[str] = None,
    materials_list: Optional[List[dict]] = None
) -> dict:
    due_at = a.due_at or a.due_date
    comparable_due = due_at
    if comparable_due and comparable_due.tzinfo is None:
        comparable_due = comparable_due.replace(tzinfo=timezone.utc)
    submitted = a.submission_state in (SubmissionState.TURNED_IN, SubmissionState.RETURNED)
    is_missing = bool(comparable_due and comparable_due < datetime.now(timezone.utc) and not submitted)
    
    if materials_list is None:
        materials_list = [
            {"id": material.id, "title": material.title, "url": material.url, "type": material.material_type}
            for material in a.materials
        ] if a.materials else []

    if course_name is None:
        course_name = a.course.name if a.course else "Course"

    return {
        "id": a.id,
        "external_id": a.external_id,
        "course_id": a.course_id,
        "title": a.title,
        "course_name": course_name,
        "work_type": a.work_type or "ASSIGNMENT",
        "is_quiz": bool(a.is_quiz),
        "description": a.description,
        "created_at": a.created_at,
        "updated_at": a.updated_at,
        "due_at": a.due_at,
        "due_date": a.due_date,
        "url": a.url,
        "state": a.state.value if a.state else None,
        "submission_state": a.submission_state.value if a.submission_state else None,
        "is_missing": is_missing,
        "materials": materials_list,
        "status": a.status.value if a.status else None,
        "last_synced_at": a.last_synced_at,
    }


@router.get("", response_model=List[dict])
def get_assignments(
    status: Optional[str] = Query(None),
    course_id: Optional[int] = Query(None),
    work_type: Optional[str] = Query(None),
    missing_only: bool = Query(False),
    since: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    query = db.query(Assignment)
    if status:
        query = query.filter(Assignment.status == status)
    if course_id:
        query = query.filter(Assignment.course_id == course_id)
    if work_type:
        query = query.filter(Assignment.work_type == work_type.upper())

    since_dt = _get_semester_start_dt(db, since)
    if since_dt:
        query = query.filter(
            (Assignment.due_at >= since_dt) |
            (Assignment.due_date >= since_dt) |
            ((Assignment.due_at.is_(None)) & (
                (Assignment.created_at >= since_dt) | (Assignment.updated_at >= since_dt)
            ))
        )

    assignments = query.order_by(Assignment.due_at.asc().nullslast(), Assignment.id.asc()).all()
    if not assignments:
        return []

    # Batch fetch courses and materials in just 2 queries
    course_ids = {a.course_id for a in assignments if a.course_id is not None}
    courses_map = (
        {c.id: c.name for c in db.query(Course.id, Course.name).filter(Course.id.in_(course_ids)).all()}
        if course_ids else {}
    )

    assignment_ids = [a.id for a in assignments]
    materials_map = defaultdict(list)
    raw_materials = (
        db.query(AssignmentMaterial.id, AssignmentMaterial.assignment_id, AssignmentMaterial.title, AssignmentMaterial.url, AssignmentMaterial.material_type)
        .filter(AssignmentMaterial.assignment_id.in_(assignment_ids))
        .all()
    )
    for m in raw_materials:
        materials_map[m.assignment_id].append({
            "id": m.id,
            "title": m.title,
            "url": m.url,
            "type": m.material_type,
        })

    result = [
        assignment_to_dict(
            a,
            course_name=courses_map.get(a.course_id, "Course"),
            materials_list=materials_map.get(a.id, [])
        )
        for a in assignments
    ]
    return [assignment for assignment in result if assignment["is_missing"]] if missing_only else result


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
