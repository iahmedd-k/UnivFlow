from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
from hashlib import sha256
import time
import threading

from app.core.config import settings
from app.core.logging import logger
from app.db.database import SessionLocal
from app.db.models import GoogleCredential, Setting
from app.db.repositories.portal import PortalSyncJobRepository

scheduler = AsyncIOScheduler(timezone=settings.timezone)


def _run_portal_auto_sync():
    """Automatically sync portal for all users with active sessions."""
    db = SessionLocal()
    try:
        # Get all users with active portal sessions
        active_users = db.query(Setting).filter(
            Setting.key.like("portal:%:portal_session_status"),
            Setting.value == "ACTIVE"
        ).all()
        
        for setting in active_users:
            # Extract user_id from key: portal:{user_id}:portal_session_status
            key_parts = setting.key.split(":")
            if len(key_parts) >= 2:
                user_id = key_parts[1]
                if user_id and user_id != "dev_student_user":
                    try:
                        repo = PortalSyncJobRepository(db)
                        active_job = repo.get_active_job(user_id)
                        if not active_job:
                            job_id = sha256(f"{user_id}:{time.time_ns()}".encode()).hexdigest()[:20]
                            repo.create(user_id, job_id, sync_type="auto")
                            db.commit()
                            # Run sync in background thread
                            threading.Thread(target=_run_portal_sync_job, args=(user_id, job_id), daemon=True).start()
                            logger.info(f"[Scheduler] Started auto portal sync for user {user_id}")
                    except Exception as e:
                        logger.warning(f"[Scheduler] Failed to start auto portal sync for user {user_id}: {e}")
                        db.rollback()
    except Exception as e:
        logger.warning(f"[Scheduler] Portal auto sync job error: {e}")
    finally:
        db.close()


def _run_portal_sync_job(uid: str, job_id: str):
    """Run portal sync for a specific user and job."""
    from app.portal.router import _sync_portal_for_user
    
    db = SessionLocal()
    try:
        repo = PortalSyncJobRepository(db)
        repo.complete_job(job_id, error=None)  # Mark as running
        
        result = _sync_portal_for_user(uid)
        
        repo.complete_job(job_id, result=result, error=None)
    except Exception as error:
        repo = PortalSyncJobRepository(db)
        repo.complete_job(job_id, error=str(error))
    finally:
        db.close()


def _cleanup_expired_oauth_states():
    """Clean up expired OAuth CSRF state tokens from the database."""
    db = SessionLocal()
    try:
        import time
        import json
        cutoff = time.time() - 900  # 15 minutes TTL
        states = db.query(Setting).filter(Setting.key.like("oauth_csrf_state_%")).all()
        deleted = 0
        for state in states:
            try:
                data = json.loads(state.value)
                created_at = data.get("created_at", 0)
                if created_at < cutoff:
                    db.delete(state)
                    deleted += 1
            except (json.JSONDecodeError, TypeError):
                db.delete(state)
                deleted += 1
        if deleted:
            db.commit()
            logger.info(f"[Scheduler] Cleaned up {deleted} expired OAuth state tokens")
    except Exception as e:
        logger.warning(f"[Scheduler] OAuth state cleanup error: {e}")
    finally:
        db.close()


def _run_gcr_sync_job():
    """Sync each connected user's Google Classroom coursework and announcements."""
    logger.info("[Scheduler] Starting scheduled Google Classroom (GCR) sync...")
    db = SessionLocal()
    try:
        from app.services.classroom_sync import ClassroomSyncService
        user_ids = [
            user_id for (user_id,) in db.query(GoogleCredential.user_id).all()
            if user_id and user_id != "legacy"
        ]
        for user_id in user_ids:
            try:
                service = ClassroomSyncService(db, user_id=user_id)
                if not service.service:
                    logger.warning("[Scheduler] GCR sync could not load credentials for %s.", user_id)
                    continue
                result = service.sync_all()
                logger.info(
                    "[Scheduler] GCR sync for %s: %s assignments, %s announcements, %s courses.",
                    user_id,
                    result.get("assignments", 0),
                    result.get("announcements", 0),
                    result.get("courses", 0),
                )
            except Exception:
                db.rollback()
                logger.exception("[Scheduler] GCR sync failed for %s.", user_id)
    except Exception as e:
        logger.warning(f"[Scheduler] GCR sync skipped or error: {e}")
    finally:
        db.close()


def _run_browser_automation_job():
    """Run a bounded number of durable opt-in Claude browser jobs."""
    db = SessionLocal()
    try:
        from app.services.browser_automation import process_browser_automation_jobs
        count = process_browser_automation_jobs(db, batch_size=2)
        if count:
            logger.info("[Scheduler] Claimed %s browser automation job(s).", count)
    except Exception:
        db.rollback()
        logger.exception("[Scheduler] Browser automation worker failed.")
    finally:
        db.close()


def _run_daily_morning_digest_job():
    """Deliver the daily morning schedule & attendance briefing strictly once per day."""
    db = SessionLocal()
    try:
        from app.services.alert_service import AlertService
        service = AlertService(db)
        digest = service.generate_daily_morning_digest(send_immediately=True)
        if digest:
            logger.info(
                f"[Scheduler] Daily morning digest dispatched: {digest.get('classes_count')} classes, "
                f"{digest.get('urgent_warnings')} advisories, {digest.get('upcoming_tasks')} tasks to {digest.get('recipient')}."
            )
    except Exception as e:
        logger.warning(f"[Scheduler] Daily morning digest job error: {e}")
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
    """Scan classes starting in 20 minutes or 5 minutes and dispatch immediate reminders."""
    db = SessionLocal()
    try:
        from app.services.alert_service import AlertService
        service = AlertService(db)
        reminders = service.generate_upcoming_class_reminders(send_immediately=True)
        if reminders:
            logger.info(f"[Scheduler] Generated and dispatched {len(reminders)} upcoming class reminder(s).")
    except Exception as e:
        logger.warning(f"[Scheduler] Timetable reminder check error: {e}")
    finally:
        db.close()


def _run_assignment_deadline_job():
    """Scan synced Google Classroom coursework for upcoming deadlines (strictly once per day per item)."""
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


def _run_process_pending_notifications():
    """Process pending notifications that are due for sending."""
    db = SessionLocal()
    try:
        from app.services.notification_service import NotificationService
        service = NotificationService(db)
        sent_count = service.process_pending_notifications(limit=50)
        if sent_count:
            logger.info(f"[Scheduler] Processed and sent {sent_count} pending notification(s).")
    except Exception as e:
        logger.warning(f"[Scheduler] Process pending notifications error: {e}")
    finally:
        db.close()


def _run_retry_failed_notifications():
    """Retry failed notifications that haven't exceeded max retries."""
    db = SessionLocal()
    try:
        from app.services.notification_service import NotificationService
        service = NotificationService(db)
        retried_count = service.retry_failed_notifications(limit=50)
        if retried_count:
            logger.info(f"[Scheduler] Retried {retried_count} failed notification(s).")
    except Exception as e:
        logger.warning(f"[Scheduler] Retry failed notifications error: {e}")
    finally:
        db.close()


def _run_daily_class_list_email():
    """Send daily morning email with list of all classes for the day."""
    db = SessionLocal()
    try:
        from app.services.alert_service import AlertService
        service = AlertService(db)
        result = service.generate_daily_class_list_email(send_immediately=True)
        if result:
            logger.info(f"[Scheduler] Daily class list email dispatched: {result.get('classes_count')} classes to {result.get('recipient')}.")
    except Exception as e:
        logger.warning(f"[Scheduler] Daily class list email error: {e}")
    finally:
        db.close()


def start_scheduler():
    """Initialize and start background automated sync and alert jobs"""
    try:
        # 1. Google Classroom: Every 30 minutes
        scheduler.add_job(
            _run_gcr_sync_job,
            IntervalTrigger(minutes=30),
            id="gcr_30min_sync",
            name="Google Classroom Auto-Sync (Every 30m)",
            replace_existing=True,
            misfire_grace_time=300,
            max_instances=1,
            coalesce=True,
        )

        scheduler.add_job(
            _run_browser_automation_job,
            IntervalTrigger(seconds=15),
            id="claude_browser_automation",
            name="Per-user Claude Browser Assignment Jobs",
            replace_existing=True,
            misfire_grace_time=60,
            max_instances=1,
            coalesce=True,
        )

        # 3. Daily Morning Digest: Every morning at 07:30 AM (strictly once per day)
        scheduler.add_job(
            _run_daily_morning_digest_job,
            CronTrigger(hour=7, minute=30, timezone=settings.timezone),
            id="daily_morning_digest",
            name="Daily Morning Schedule & Attendance Digest (07:30 AM)",
            replace_existing=True,
            misfire_grace_time=3600,
            coalesce=True,
        )

        # Catchup check every 60 minutes for daily digest (idempotency key prevents duplicate sends)
        scheduler.add_job(
            _run_daily_morning_digest_job,
            IntervalTrigger(hours=1),
            id="daily_morning_digest_catchup",
            name="Daily Morning Digest Catchup Check (Hourly)",
            replace_existing=True,
            misfire_grace_time=300,
            coalesce=True,
        )

        # 4. Day-of-Class Attendance Warnings: Check every 30 minutes
        scheduler.add_job(
            _run_attendance_warning_job,
            IntervalTrigger(minutes=30),
            id="attendance_low_warning_check",
            name="Low Attendance Day-of-Class Warnings (Every 30m)",
            replace_existing=True,
            misfire_grace_time=300,
            coalesce=True,
        )

        # 5. Timetable Class Reminders: Hourly at :40 past the hour (between 7 AM and 10 PM)
        # Checks once per hour (at 6:40, 7:40, ..., 21:40) to alert 20 minutes prior to the upcoming hour's class
        scheduler.add_job(
            _run_timetable_reminder_job,
            CronTrigger(hour="6-21", minute="40", timezone=settings.timezone),
            id="timetable_class_reminders",
            name="Timetable Hourly Class Reminders (6:40 AM - 9:40 PM)",
            replace_existing=True,
            misfire_grace_time=300,
            max_instances=1,
            coalesce=True,
        )

        # 6. Google Classroom Assignment Deadlines (Once per day per item): Check every 30 minutes
        scheduler.add_job(
            _run_assignment_deadline_job,
            IntervalTrigger(minutes=30),
            id="assignment_deadline_reminders",
            name="GCR Assignment Deadline Alerts (Every 30m)",
            replace_existing=True,
            misfire_grace_time=300,
            coalesce=True,
        )

        # 7. OAuth State Cleanup: Remove expired CSRF state tokens every 5 minutes
        scheduler.add_job(
            _cleanup_expired_oauth_states,
            IntervalTrigger(minutes=5),
            id="oauth_state_cleanup",
            name="OAuth CSRF State Cleanup (Every 5m)",
            replace_existing=True,
            misfire_grace_time=60,
            max_instances=1,
            coalesce=True,
        )

        # 8. Portal Auto Sync: Run every 30 minutes for users with active sessions
        scheduler.add_job(
            _run_portal_auto_sync,
            IntervalTrigger(minutes=30),
            id="portal_auto_sync_active_users",
            name="University Portal Auto Sync for Active Users (Every 30m)",
            replace_existing=True,
            misfire_grace_time=300,
            max_instances=1,
            coalesce=True,
        )

        # 9. Process Pending Notifications: Check every 5 minutes
        scheduler.add_job(
            _run_process_pending_notifications,
            IntervalTrigger(minutes=5),
            id="process_pending_notifications",
            name="Process Pending Notifications (Every 5m)",
            replace_existing=True,
            misfire_grace_time=60,
            max_instances=1,
            coalesce=True,
        )

        # 10. Retry Failed Notifications: Check every 15 minutes
        scheduler.add_job(
            _run_retry_failed_notifications,
            IntervalTrigger(minutes=15),
            id="retry_failed_notifications",
            name="Retry Failed Notifications (Every 15m)",
            replace_existing=True,
            misfire_grace_time=60,
            max_instances=1,
            coalesce=True,
        )

        # 11. Daily Class List Email: Every morning at 07:00 AM (strictly once per day)
        scheduler.add_job(
            _run_daily_class_list_email,
            CronTrigger(hour=7, minute=0, timezone=settings.timezone),
            id="daily_class_list_email",
            name="Daily Class List Email (07:00 AM)",
            replace_existing=True,
            misfire_grace_time=3600,
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
