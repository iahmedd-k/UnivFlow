from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from app.db.database import get_db
from app.db.repositories import AgentRunRepository, AgentEventRepository
from app.db.models import AgentRun, AgentEvent, AgentRunStatus, AgentRunTrigger

router = APIRouter(prefix="/agent", tags=["Agent"])


def get_agent_runs(
    limit: int = 20,
    db: Session = Depends(get_db)
):
    repo = AgentRunRepository(db)
    runs = repo.get_recent(limit)
    return [
        {
            "id": r.id,
            "trigger": r.trigger.value,
            "status": r.status.value,
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


def get_agent_run(run_id: int, db: Session = Depends(get_db)):
    run = db.query(AgentRun).filter(AgentRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Agent run not found")
    return {
        "id": run.id,
        "trigger": run.trigger.value,
        "status": run.status.value,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "duration_seconds": run.duration_seconds,
        "assignments_found": run.assignments_found,
        "changes_found": run.changes_found,
        "notifications_sent": run.notifications_sent,
        "errors": run.errors,
        "error_details": run.error_details,
    }


def get_agent_run_events(run_id: int, db: Session = Depends(get_db)):
    run = db.query(AgentRun).filter(AgentRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Agent run not found")

    repo = AgentEventRepository(db)
    events = repo.get_by_run(run_id)
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


def get_agent_stats(db: Session = Depends(get_db)):
    total_runs = db.query(AgentRun).count()
    running = db.query(AgentRun).filter(AgentRun.status == AgentRunStatus.RUNNING).count()
    completed = db.query(AgentRun).filter(AgentRun.status == AgentRunStatus.COMPLETED).count()
    failed = db.query(AgentRun).filter(AgentRun.status == AgentRunStatus.FAILED).count()

    recent_run = db.query(AgentRun).order_by(AgentRun.started_at.desc()).first()

    return {
        "total_runs": total_runs,
        "running": running,
        "completed": completed,
        "failed": failed,
        "last_run": {
            "id": recent_run.id,
            "trigger": recent_run.trigger.value,
            "status": recent_run.status.value,
            "started_at": recent_run.started_at,
        } if recent_run else None,
    }
