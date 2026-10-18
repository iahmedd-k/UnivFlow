from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional

from app.db.database import get_db
from app.db.repositories import AgentRunRepository, AgentEventRepository
from app.db.models import AgentRun, AgentEvent, AgentRunStatus, AgentRunTrigger
from app.auth.clerk_auth import get_current_user_optional
from app.auth.ownership import require_user_id, user_owner_ids

router = APIRouter(prefix="/agent", tags=["Agent"])


@router.get("/runs", response_model=List[dict])
def get_agent_runs(
    limit: int = 20,
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional),
):
    user_id = require_user_id(clerk_user)
    owners = user_owner_ids(user_id)
    runs = (
        db.query(AgentRun)
        .filter(AgentRun.user_id.in_(owners))
        .order_by(AgentRun.started_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": r.id,
            "trigger": r.trigger.value if r.trigger else None,
            "status": r.status.value if r.status else None,
            "started_at": r.started_at,
            "finished_at": r.finished_at,
            "duration_seconds": r.duration_seconds,
            "assignments_found": r.assignments_found,
            "changes_found": r.changes_found,
            "notifications_sent": r.notifications_sent,
            "errors": r.errors,
            "error_details": r.error_details,
        }
        for r in runs
    ]


@router.get("/runs/{run_id}", response_model=dict)
def get_agent_run(
    run_id: int,
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional),
):
    user_id = require_user_id(clerk_user)
    owners = user_owner_ids(user_id)
    run = db.query(AgentRun).filter(AgentRun.id == run_id, AgentRun.user_id.in_(owners)).first()
    if not run:
        raise HTTPException(status_code=404, detail="Agent run not found")
    return {
        "id": run.id,
        "trigger": run.trigger.value if run.trigger else None,
        "status": run.status.value if run.status else None,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "duration_seconds": run.duration_seconds,
        "assignments_found": run.assignments_found,
        "changes_found": run.changes_found,
        "notifications_sent": run.notifications_sent,
        "errors": run.errors,
        "error_details": run.error_details,
    }


@router.get("/runs/{run_id}/events", response_model=List[dict])
def get_agent_run_events(
    run_id: int,
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional),
):
    user_id = require_user_id(clerk_user)
    owners = user_owner_ids(user_id)
    run = db.query(AgentRun).filter(AgentRun.id == run_id, AgentRun.user_id.in_(owners)).first()
    if not run:
        raise HTTPException(status_code=404, detail="Agent run not found")

    events = (
        db.query(AgentEvent)
        .filter(AgentEvent.run_id == run_id, AgentEvent.user_id.in_(owners))
        .order_by(AgentEvent.created_at.asc())
        .all()
    )
    return [
        {
            "id": e.id,
            "run_id": e.run_id,
            "event_type": e.event_type,
            "source": e.source,
            "status": e.status,
            "message": e.message,
            "details": e.details,
            "created_at": e.created_at,
        }
        for e in events
    ]


@router.get("/stats", response_model=dict)
def get_agent_stats(
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional),
):
    user_id = require_user_id(clerk_user)
    owners = user_owner_ids(user_id)
    user_runs = db.query(AgentRun).filter(AgentRun.user_id.in_(owners))
    total_runs = user_runs.count()
    running = user_runs.filter(AgentRun.status == AgentRunStatus.RUNNING).count()
    completed = user_runs.filter(AgentRun.status == AgentRunStatus.COMPLETED).count()
    failed = user_runs.filter(AgentRun.status == AgentRunStatus.FAILED).count()

    recent_run = user_runs.order_by(AgentRun.started_at.desc()).first()

    return {
        "total_runs": total_runs,
        "running": running,
        "completed": completed,
        "failed": failed,
        "last_run": {
            "id": recent_run.id,
            "trigger": recent_run.trigger.value if recent_run.trigger else None,
            "status": recent_run.status.value if recent_run.status else None,
            "started_at": recent_run.started_at,
        } if recent_run else None,
    }
