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


def _run_attendance_warning_job():
    """Scan today's scheduled classes and alert students if attendance is critically low."""
    db = SessionLocal()
    try:
        from app.services.alert_service import AlertService
        service = AlertService(db)
        alerts = service.generate_daily_attendance_warnings(send_immediately=True)
        if alerts:
            logger.info(f"[Scheduler] Generated and dispatched {len(alerts)} low-attendance warning(s).")
    except Exception as e:
        logger.warning(f"[Scheduler] Attendance warning check error: {e}")
    finally:
        db.close()


def _run_timetable_reminder_job():
    """Scan classes starting in ~10 minutes and dispatch immediate reminders."""
    db = SessionLocal()
    try:
        from app.services.alert_service import AlertService
        service = AlertService(db)
        reminders = service.generate_upcoming_class_reminders(lookahead_minutes=10, send_immediately=True)
        if reminders:
            logger.info(f"[Scheduler] Generated and dispatched {len(reminders)} upcoming class reminder(s).")
    except Exception as e:
        logger.warning(f"[Scheduler] Timetable reminder check error: {e}")
    finally:
        db.close()


def _run_assignment_deadline_job():
    """Scan synced Google Classroom coursework for upcoming deadlines (24h and 3h)."""
    db = SessionLocal()
    try:
        from app.services.alert_service import AlertService
        service = AlertService(db)
        deadline_alerts = service.generate_upcoming_assignment_reminders(lookahead_hours=24, send_immediately=True)
        if deadline_alerts:
            logger.info(f"[Scheduler] Generated and dispatched {len(deadline_alerts)} assignment deadline alert(s).")
    except Exception as e:
        logger.warning(f"[Scheduler] Assignment deadline check error: {e}")
    finally:
        db.close()


def start_scheduler():
    """Initialize and start background automated sync and alert jobs"""
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

        # 3. Attendance Warnings: Check today's scheduled classes every 30 minutes
        scheduler.add_job(
            _run_attendance_warning_job,
            IntervalTrigger(minutes=30),
            id="attendance_low_warning_check",
            name="Low Attendance Day-of-Class Warnings (Every 30m)",
            replace_existing=True,
            misfire_grace_time=300,
            coalesce=True,
        )

        # 4. Timetable 10-Minute Prior Reminders: Check every 1 minute
        scheduler.add_job(
            _run_timetable_reminder_job,
            IntervalTrigger(minutes=1),
            id="timetable_10min_reminders",
            name="Timetable 10-Minute Class Reminders (Every 1m)",
            replace_existing=True,
            misfire_grace_time=60,
            coalesce=True,
        )

        # 5. Google Classroom Assignment Deadlines: Check every 30 minutes
        scheduler.add_job(
            _run_assignment_deadline_job,
            IntervalTrigger(minutes=30),
            id="assignment_deadline_reminders",
            name="GCR Assignment Deadline Alerts (Every 30m)",
            replace_existing=True,
            misfire_grace_time=300,
            coalesce=True,
        )

        scheduler.start()
        logger.info("[Scheduler] Automated background sync and alert scheduler started successfully.")
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
