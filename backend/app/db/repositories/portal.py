from sqlalchemy import func
from sqlalchemy.orm import Session
from typing import Optional, List
from datetime import datetime, timezone
from app.db.models import PortalSyncJob


class PortalSyncJobRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, user_id: str, job_id: str, sync_type: str = "full", max_retries: int = 3) -> PortalSyncJob:
        job = PortalSyncJob(
            user_id=user_id,
            job_id=job_id,
            sync_type=sync_type,
            max_retries=max_retries,
            status="queued",
        )
        self.db.add(job)
        self.db.commit()
        self.db.refresh(job)
        return job

    def get_by_job_id(self, job_id: str) -> Optional[PortalSyncJob]:
        return self.db.query(PortalSyncJob).filter(PortalSyncJob.job_id == job_id).first()

    def get_by_user_id(self, user_id: str, limit: int = 50) -> List[PortalSyncJob]:
        return self.db.query(PortalSyncJob).filter(
            PortalSyncJob.user_id == user_id
        ).order_by(PortalSyncJob.created_at.desc()).limit(limit).all()

    def get_active_job(self, user_id: str) -> Optional[PortalSyncJob]:
        return self.db.query(PortalSyncJob).filter(
            PortalSyncJob.user_id == user_id,
            PortalSyncJob.status.in_(["queued", "running"])
        ).first()

    def get_pending_jobs(self, limit: int = 10) -> List[PortalSyncJob]:
        now = datetime.now(timezone.utc)
        return self.db.query(PortalSyncJob).filter(
            PortalSyncJob.status == "queued",
            PortalSyncJob.next_retry_at.is_(None) | (PortalSyncJob.next_retry_at <= now),
            PortalSyncJob.retry_count < PortalSyncJob.max_retries
        ).order_by(PortalSyncJob.created_at).limit(limit).all()

    def claim_job(self, job_id: str) -> Optional[PortalSyncJob]:
        now = datetime.now(timezone.utc)
        job = self.db.query(PortalSyncJob).filter(
            PortalSyncJob.job_id == job_id,
            PortalSyncJob.status == "queued",
        ).first()
        
        if not job:
            return None
        
        job.status = "running"
        job.started_at = now
        job.retry_count += 1
        self.db.commit()
        self.db.refresh(job)
        return job

    def complete_job(self, job_id: str, result: dict = None, error: str = None) -> Optional[PortalSyncJob]:
        now = datetime.now(timezone.utc)
        job = self.db.query(PortalSyncJob).filter(PortalSyncJob.job_id == job_id).first()
        
        if not job:
            return None
        
        if error:
            job.status = "failed"
            job.error = error
            # Schedule retry if attempts remaining
            if job.retry_count < job.max_retries:
                job.status = "queued"
                job.next_retry_at = now
        else:
            job.status = "completed"
            if result:
                import json
                job.result = json.dumps(result)
        
        job.finished_at = now
        self.db.commit()
        self.db.refresh(job)
        return job

    def cancel_job(self, job_id: str) -> bool:
        job = self.db.query(PortalSyncJob).filter(PortalSyncJob.job_id == job_id).first()
        if not job or job.status in ["completed", "failed"]:
            return False
        job.status = "cancelled"
        job.finished_at = datetime.now(timezone.utc)
        self.db.commit()
        return True

    def cleanup_old_jobs(self, days: int = 30) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        deleted = self.db.query(PortalSyncJob).filter(
            PortalSyncJob.created_at < cutoff,
            PortalSyncJob.status.in_(["completed", "failed", "cancelled"])
        ).delete(synchronize_session=False)
        self.db.commit()
        return deleted


from datetime import timedelta