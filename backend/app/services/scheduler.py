from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.core.config import settings
from app.core.logging import logger
from app.db.database import SessionLocal
from app.db.models import Setting

scheduler = AsyncIOScheduler(timezone=settings.timezone)


def _run_portal_sync_job():
    """Refresh every connected student profile without prompting for page captures."""
    db = SessionLocal()
    try:
        from app.portal.router import _sync_portal_for_user
        suffix = ":university_portal_url"
        keys = db.query(Setting.key).filter(Setting.key.like(f"portal:%{suffix}")).all()
        for (key,) in keys:
            user_id = key[len("portal:"):-len(suffix)]
            if not user_id:
                continue
            result = _sync_portal_for_user(user_id)
            logger.info(f"[Scheduler] University portal sync: {result.get('status')}")
    except Exception as e:
        logger.warning(f"[Scheduler] University Portal sync skipped or error: {e}")
    finally:
        db.close()


def _run_gcr_sync_job():
    """Sync Google Classroom coursework and announcements every 30 minutes"""
    logger.info("[Scheduler] Starting scheduled Google Classroom (GCR) sync...")
    db = SessionLocal()
    try:
        from app.services.classroom_sync import ClassroomSyncService
        service = ClassroomSyncService(db)
        if service.service:
            result = service.sync_all()
            logger.info(
                f"[Scheduler] GCR sync completed: {result.get('assignments', 0)} assignments, "
                f"{result.get('announcements', 0)} announcements, {result.get('courses', 0)} courses."
            )
    except Exception as e:
        logger.warning(f"[Scheduler] GCR sync skipped or error: {e}")
    finally:
        db.close()


def start_scheduler():
    """Initialize and start background automated sync jobs"""
    try:
        # 1. University Portal: refresh connected profiles every 15 minutes
        scheduler.add_job(
            _run_portal_sync_job,
            IntervalTrigger(minutes=15),
            id="portal_auto_sync",
            name="University Portal Auto Sync (Every 15m)",
            replace_existing=True,
            misfire_grace_time=300,
            max_instances=1,
            coalesce=True,
        )

        # 2. Google Classroom: Every 30 minutes
        scheduler.add_job(
            _run_gcr_sync_job,
            IntervalTrigger(minutes=30),
            id="gcr_30min_sync",
            name="Google Classroom Auto-Sync (Every 30m)",
            replace_existing=True,
            misfire_grace_time=300,
        )

        scheduler.start()
        logger.info("[Scheduler] Automated background sync scheduler started successfully.")
    except Exception as e:
        logger.error(f"[Scheduler] Failed to start scheduler: {e}")


def shutdown_scheduler():
    """Gracefully shutdown background scheduler"""
    try:
        if scheduler.running:
            scheduler.shutdown(wait=False)
            logger.info("[Scheduler] Background sync scheduler stopped.")
    except Exception as e:
        logger.warning(f"[Scheduler] Error stopping scheduler: {e}")
