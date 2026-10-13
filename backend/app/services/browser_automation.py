from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.core.logging import logger
from app.db.models import BrowserAutomationJob, Setting


MAX_ATTEMPTS = 3
STALE_JOB_MINUTES = 30
RETRY_DELAYS_SECONDS = (60, 300)


def _recover_stale_jobs(db: Session, now: datetime) -> None:
    stale = db.query(BrowserAutomationJob).filter(
        BrowserAutomationJob.status == "running",
        BrowserAutomationJob.started_at < now - timedelta(minutes=STALE_JOB_MINUTES),
    ).all()
    for job in stale:
        if job.attempts >= MAX_ATTEMPTS:
            job.status = "failed"
            job.finished_at = now
            job.error = "Worker stopped while this job was running; retry limit reached."
        else:
            job.status = "pending"
            job.queued_at = now
            job.error = "Recovered after a worker interruption."
    if stale:
        db.commit()


def _claim_job(db: Session, now: datetime) -> Optional[BrowserAutomationJob]:
    candidate = db.query(BrowserAutomationJob.id).filter(
        BrowserAutomationJob.status == "pending",
        BrowserAutomationJob.queued_at <= now,
        BrowserAutomationJob.attempts < MAX_ATTEMPTS,
    ).order_by(BrowserAutomationJob.queued_at, BrowserAutomationJob.id).first()
    if not candidate:
        return None
    candidate_id = candidate[0]
    claimed = db.query(BrowserAutomationJob).filter(
        BrowserAutomationJob.id == candidate_id,
        BrowserAutomationJob.status == "pending",
    ).update(
        {
            BrowserAutomationJob.status: "running",
            BrowserAutomationJob.attempts: BrowserAutomationJob.attempts + 1,
            BrowserAutomationJob.started_at: now,
            BrowserAutomationJob.finished_at: None,
            BrowserAutomationJob.error: None,
        },
        synchronize_session=False,
    )
    if not claimed:
        db.rollback()
        return None
    db.commit()
    return db.query(BrowserAutomationJob).filter(BrowserAutomationJob.id == candidate_id).first()


def process_browser_automation_jobs(db: Session, batch_size: int = 2) -> int:
    """Claim and process a bounded batch of durable, opt-in browser jobs."""
    now = datetime.now(timezone.utc)
    _recover_stale_jobs(db, now)
    processed = 0

    for _ in range(batch_size):
        job = _claim_job(db, datetime.now(timezone.utc))
        if not job:
            break
        processed += 1
        user_id = job.user_id

        enabled = db.query(Setting).filter(
            Setting.key == f"classroom:{user_id}:auto_solve_enabled"
        ).first()
        if not enabled or enabled.value != "true":
            job.status = "cancelled"
            job.finished_at = datetime.now(timezone.utc)
            job.error = "Automatic solving was disabled before this job started."
            db.commit()
            continue

        try:
            from app.services.browser_sessions import BrowserSessionClient

            browser_status = BrowserSessionClient().status(user_id)
            if not browser_status.get("active"):
                job.status = "needs_login"
                job.error = "Start and sign into your private Claude browser, then resume waiting assignments."
                job.finished_at = datetime.now(timezone.utc)
                db.commit()
                continue

            from app.services.claude_browser_solver import solve_assignment_via_claude_browser

            result = solve_assignment_via_claude_browser(
                db=db,
                assignment_id=job.assignment_id,
                user_id=user_id,
            )
            if result.get("status") == "completed":
                job.status = "completed"
                job.error = None
                job.finished_at = datetime.now(timezone.utc)
            elif result.get("status") == "needs_login":
                job.status = "needs_login"
                job.error = result.get("error") or "Claude sign-in is required."
                job.finished_at = datetime.now(timezone.utc)
            else:
                _record_retry(job, result.get("error") or "Browser solver returned an unsuccessful result.")
            db.commit()
        except Exception as error:
            logger.exception("Automatic browser solve failed for job %s.", job.id)
            _record_retry(job, str(error))
            db.commit()

    return processed


def _record_retry(job: BrowserAutomationJob, error: str) -> None:
    now = datetime.now(timezone.utc)
    if job.attempts < MAX_ATTEMPTS:
        delay = RETRY_DELAYS_SECONDS[min(job.attempts - 1, len(RETRY_DELAYS_SECONDS) - 1)]
        job.status = "pending"
        job.queued_at = now + timedelta(seconds=delay)
        job.error = error[:4000]
        job.finished_at = None
    else:
        job.status = "failed"
        job.error = error[:4000]
        job.finished_at = now
