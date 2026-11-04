from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
from hashlib import sha256
import time
import threading
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.config import settings
from app.core.logging import logger
from app.db.database import SessionLocal
from app.db.models import GoogleCredential, Setting
from app.db.repositories.portal import PortalSyncJobRepository

scheduler = AsyncIOScheduler(timezone=settings.timezone)


def _has_private_access(db, user_id: str) -> bool:
    if not settings.is_production:
        return True
    from app.auth.access_gate import get_access_status
    return get_access_status({"id": user_id}, db)["granted"]


def _run_portal_auto_sync():
    """Automatically sync university portal and update attendance for configured users."""
    logger.info("[Scheduler] Executing automated university portal sync & attendance update...")
    db = SessionLocal()
    try:
        # Find all candidate users with active session status or saved session cookies
        portal_settings = db.query(Setting).filter(
            (Setting.key.like("portal:%:portal_session_status") & (Setting.value == "ACTIVE"))
            | (Setting.key.like("portal:%:portal_session_cookies"))
            | (Setting.key.like("portal:%:university_portal_url"))
        ).all()
        
        user_ids = set()
        for s in portal_settings:
            parts = s.key.split(":")
            if len(parts) >= 3 and parts[0] == "portal" and parts[1]:
                user_ids.add(parts[1])

        for user_id in sorted(user_ids):
            if not user_id:
                continue
            if settings.is_production and user_id != "dev_student_user" and not _has_private_access(db, user_id):
                continue

            try:
                repo = PortalSyncJobRepository(db)
                active_job = repo.get_active_job(user_id)
                if not active_job:
                    job_id = sha256(f"{user_id}:{time.time_ns()}".encode()).hexdigest()[:20]
                    repo.create(user_id, job_id, sync_type="auto")
                    db.commit()
                    # Run sync in background thread
                    threading.Thread(target=_run_portal_sync_job, args=(user_id, job_id), daemon=True).start()
                    logger.info(f"[Scheduler] Dispatched portal auto-sync job {job_id} for user {user_id}")
            except Exception as e:
                logger.warning(f"[Scheduler] Failed to dispatch portal auto-sync for user {user_id}: {e}")
                db.rollback()
    except Exception as e:
        logger.warning(f"[Scheduler] Portal auto sync job error: {e}")
    finally:
        db.close()


def _run_portal_sync_job(uid: str, job_id: str):
    """Run portal sync and attendance update for a specific user and job."""
    from app.api.endpoints.portal import _sync_portal_for_user
    
    db = SessionLocal()
    try:
        repo = PortalSyncJobRepository(db)
        repo.claim_job(job_id)  # Mark as running
        
        result = _sync_portal_for_user(uid)
        logger.info(f"[Scheduler] Portal sync finished for user {uid}: status={result.get('status')}")

        if result.get("status") in ("success", "partial"):
            repo.complete_job(job_id, result=result, error=None)
        else:
            repo.complete_job(job_id, error=result.get("error") or "Portal sync failed.")
    except Exception as error:
        logger.error(f"[Scheduler] Portal sync job exception for user {uid}: {error}")
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
        from app.services.classroom_sync import ClassroomSyncService, get_classroom_sync_lock
        user_ids = [
            user_id for (user_id,) in db.query(GoogleCredential.user_id).all()
            if user_id and user_id != "legacy" and _has_private_access(db, user_id)
        ]
        for user_id in user_ids:
            sync_lock = get_classroom_sync_lock(user_id)
            if not sync_lock.acquire(blocking=False):
                logger.info("[Scheduler] Skipping GCR sync for %s; another sync is running.", user_id)
                continue
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
            finally:
                sync_lock.release()
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
    """Deliver each account's enabled daily briefing at its local scheduled time."""
    db = SessionLocal()
    try:
        import json
        from app.services.alert_service import AlertService
        service = AlertService(db)
        for user_id in _alert_user_ids(db):
            preference = db.query(Setting).filter(Setting.key == f"automation_daily_briefing_{user_id}").first()
            try:
                saved = json.loads(preference.value) if preference and preference.value else {}
            except (TypeError, json.JSONDecodeError):
                saved = {}
            if not bool(saved.get("enabled", True)):
                continue
            timezone_name = str(saved.get("timezone", settings.timezone))
            try:
                user_zone = ZoneInfo(timezone_name)
            except ZoneInfoNotFoundError:
                user_zone = ZoneInfo(settings.timezone)
            run_time = str(saved.get("time", "07:30"))
            try:
                from datetime import time as datetime_time
                hour, minute = map(int, run_time.split(":"))
                scheduled_time = datetime_time(hour, minute)
            except (ValueError, TypeError):
                scheduled_time = datetime_time(7, 30)
            user_now = datetime.now(user_zone)
            if user_now.time().replace(tzinfo=None) < scheduled_time:
                continue
            digest = service.generate_daily_morning_digest(
                user_id=user_id,
                target_date=user_now.date(),
                send_immediately=True,
                timezone_name=str(saved.get("timezone", settings.timezone)),
            )
            if digest:
                logger.info(
                    "[Scheduler] Daily digest dispatched for %s: %s classes, %s advisories, %s tasks.",
                    user_id, digest.get("classes_count"), digest.get("urgent_warnings"), digest.get("upcoming_tasks"),
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
        alerts = [item for uid in _alert_user_ids(db) for item in service.generate_daily_attendance_warnings(user_id=uid, send_immediately=True)]
        if alerts:
            logger.info(f"[Scheduler] Generated and dispatched {len(alerts)} low-attendance warning(s).")
    except Exception as e:
        logger.warning(f"[Scheduler] Attendance warning check error: {e}")
    finally:
        db.close()


def _run_timetable_reminder_job():
    """Scan for class slots inside the single pre-class reminder window."""
    db = SessionLocal()
    try:
        from app.services.alert_service import AlertService
        service = AlertService(db)
        reminders = [item for uid in _alert_user_ids(db) for item in service.generate_upcoming_class_reminders(user_id=uid, send_immediately=True)]
        if reminders:
            logger.info(f"[Scheduler] Generated and dispatched {len(reminders)} upcoming class reminder(s).")
    except Exception as e:
        logger.warning(f"[Scheduler] Timetable reminder check error: {e}")
    finally:
        db.close()


def _run_exam_reminder_job():
    """Email exam reminders at the one-hour and thirty-minute milestones."""
    from datetime import timedelta
    from html import escape
    import json
    from app.db.models import Exam
    from app.services.alert_service import get_user_recipient_email
    from app.services.email import send_email
    db = SessionLocal()
    try:
        now = datetime.now(ZoneInfo(settings.timezone))
        exams = db.query(Exam).filter(Exam.date.isnot(None)).all()
        for exam in exams:
            try:
                if not exam.user_id or exam.user_id in ("legacy", "dev_student_user"):
                    continue
                if settings.is_production and not _has_private_access(db, exam.user_id):
                    continue
                raw_time = (exam.time or "").strip()
                raw_time_lower = raw_time.lower()
                for separator in ("–", "—", " to ", " - "):
                    if separator in raw_time_lower:
                        raw_time = raw_time[:raw_time_lower.index(separator)].strip()
                        break
                exam_time = None
                for fmt in ("%H:%M", "%I:%M %p", "%I:%M%p", "%I %p", "%I%p", "%H%M"):
                    try:
                        exam_time = datetime.strptime(raw_time, fmt).time()
                        break
                    except ValueError:
                        continue
                if not exam_time:
                    continue
                exam_date = exam.date.date() if isinstance(exam.date, datetime) else exam.date
                scheduled = datetime.combine(exam_date, exam_time, tzinfo=ZoneInfo(settings.timezone))
                remaining = scheduled - now
                milestone = "60" if timedelta(minutes=55) <= remaining <= timedelta(minutes=65) else None
                if not milestone:
                    continue
                sent_key = f"exam_reminder_sent:{exam.user_id}:{exam.id}:{milestone}"
                if db.query(Setting).filter(Setting.key == sent_key).first():
                    continue
                recipient = get_user_recipient_email(db, exam.user_id)
                if not recipient:
                    continue
                when = scheduled.strftime("%A, %B %d at %I:%M %p %Z")
                exam_title_html = escape(exam.title or "Exam")
                room_text = exam.room or "See your roll number slip"
                room_html = escape(room_text)
                ok = send_email(recipient, f"Exam reminder: {exam.title or 'Exam'} in {milestone} minutes", f"<p>Your <strong>{exam_title_html}</strong> exam starts in {milestone} minutes.</p><p>Time: {when}<br>Room: {room_html}</p>", f"Your {exam.title or 'Exam'} exam starts in {milestone} minutes. Time: {when}. Room: {room_text}", categories=["exam-reminder", f"exam-reminder-{milestone}"])
                if ok:
                    db.add(Setting(key=sent_key, value=json.dumps({"sent_at": now.isoformat()}), description="Sent exam reminder milestone"))
                    db.commit()
            except Exception:
                db.rollback()
                logger.exception("Exam reminder failed for exam %s", getattr(exam, "id", "unknown"))
    except Exception:
        db.rollback()
        logger.exception("Exam reminder scan failed")
    finally:
        db.close()


def _run_assignment_deadline_job():
    """Scan synced Google Classroom coursework for upcoming deadlines (strictly once per day per item)."""
    db = SessionLocal()
    try:
        from app.services.alert_service import AlertService
        service = AlertService(db)
        deadline_alerts = [item for uid in _alert_user_ids(db) for item in service.generate_upcoming_assignment_reminders(user_id=uid, lookahead_hours=24, send_immediately=True)]
        if deadline_alerts:
            logger.info(f"[Scheduler] Generated and dispatched {len(deadline_alerts)} assignment deadline alert(s).")
    except Exception as e:
        logger.warning(f"[Scheduler] Assignment deadline check error: {e}")
    finally:
        db.close()


def _run_course_auto_turn_in_job():
    """Check explicitly enabled, course-scoped auto-submit preferences every five minutes."""
    db = SessionLocal()
    try:
        import json
        from app.api.endpoints.classroom import check_and_execute_course_auto_turn_in
        from app.auth.access_gate import get_access_status

        rows = db.query(Setting).filter(Setting.key.like("auto_turnin_course_%")).all()
        for row in rows:
            try:
                preferences = json.loads(row.value or "{}")
                if not preferences.get("enabled"):
                    continue
                setting_suffix = row.key.removeprefix("auto_turnin_course_")
                user_id, course_id = setting_suffix.rsplit("_", 1)
                if not user_id or not course_id.isdigit():
                    continue
                if settings.is_production and not get_access_status({"id": user_id}, db)["granted"]:
                    continue
                check_and_execute_course_auto_turn_in(db, int(course_id), user_id)
            except Exception:
                logger.exception("[Scheduler] Course auto turn-in check failed for setting %s", row.key)
                db.rollback()
    except Exception:
        db.rollback()
        logger.exception("[Scheduler] Course auto turn-in scan failed")
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
        for user_id in _alert_user_ids(db):
            result = service.generate_daily_class_list_email(user_id=user_id, send_immediately=True)
            if result:
                logger.info("[Scheduler] Daily class list dispatched for %s (%s classes).", user_id, result.get("classes_count"))
    except Exception as e:
        logger.warning(f"[Scheduler] Daily class list email error: {e}")
    finally:
        db.close()


def _alert_user_ids(db):
    """Enumerate exact account IDs with an explicitly configured alert email."""
    user_ids = set()
    for setting in db.query(Setting).filter(
        Setting.key.like("notification_email_%")
    ).all():
        key = setting.key
        val = (setting.value or "").strip()
        if not val or "@" not in val:
            continue
        user_id = key[len("notification_email_"):]
        if user_id and user_id not in ("default", "legacy", "dev_student_user"):
            user_ids.add(user_id)
    return sorted(
        user_id for user_id in user_ids
        if user_id and _has_private_access(db, user_id)
    )


def _reap_zombie_sync_jobs():
    """Detect and reset background sync jobs that died due to server restarts or timeouts."""
    db = SessionLocal()
    try:
        import json
        from datetime import datetime, timezone, timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=15)

        # 1. Clean zombie classroom sync statuses
        classroom_statuses = db.query(Setting).filter(Setting.key.like("classroom:%:sync_status")).all()
        for s in classroom_statuses:
            try:
                data = json.loads(s.value or "{}")
                if data.get("status") == "running":
                    started_str = data.get("started_at")
                    if started_str:
                        started_dt = datetime.fromisoformat(started_str.replace("Z", "+00:00"))
                        if started_dt < cutoff:
                            data["status"] = "timed_out"
                            data["error"] = "Sync job timed out or worker process restarted."
                            data["finished_at"] = datetime.now(timezone.utc).isoformat()
                            s.value = json.dumps(data)
                            logger.info(f"[Scheduler] Reaped zombie classroom sync for setting {s.key}")
            except Exception as e:
                logger.warning(f"[Scheduler] Error parsing sync status for {s.key}: {e}")

        # 2. Clean zombie portal sync jobs
        from app.db.models import PortalSyncJob
        try:
            zombie_portal_jobs = db.query(PortalSyncJob).filter(
                PortalSyncJob.status == "running",
                PortalSyncJob.started_at < cutoff
            ).all()
            for job in zombie_portal_jobs:
                job.status = "failed"
                job.error = "Portal sync timed out or worker process restarted."
                job.completed_at = datetime.now(timezone.utc)
                logger.info(f"[Scheduler] Reaped zombie portal job {job.job_id}")
        except Exception:
            pass

        db.commit()
    except Exception as e:
        logger.warning(f"[Scheduler] Zombie reaper error: {e}")
        db.rollback()
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

        # 3. Per-account Daily Briefing: poll enabled user schedules every five minutes.
        scheduler.add_job(
            _run_daily_morning_digest_job,
            IntervalTrigger(minutes=5),
            id="daily_morning_digest",
            name="Per-account Daily Academic Briefing",
            replace_existing=True,
            misfire_grace_time=300,
            max_instances=1,
            coalesce=True,
        )

        # Poll every five minutes to reach the single class reminder window.
        scheduler.add_job(
            _run_timetable_reminder_job,
            IntervalTrigger(minutes=5),
            id="timetable_class_reminders",
            name="Timetable Class Reminder (Every 5m; one notice near class time)",
            replace_existing=True,
            misfire_grace_time=300,
            max_instances=1,
            coalesce=True,
        )

        scheduler.add_job(
            _run_exam_reminder_job,
            IntervalTrigger(minutes=5),
            id="exam_email_reminders",
            name="Roll Number Slip Exam Email Reminders",
            replace_existing=True,
            misfire_grace_time=300,
            max_instances=1,
            coalesce=True,
        )

        scheduler.add_job(
            _run_course_auto_turn_in_job,
            IntervalTrigger(minutes=1),
            id="course_auto_turn_in",
            name="Explicitly enabled course auto turn-in (Every minute)",
            replace_existing=True,
            misfire_grace_time=60,
            max_instances=1,
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

        # 11. Zombie Sync Job Reaper: Clean up hung/interrupted tasks every 10 minutes
        scheduler.add_job(
            _reap_zombie_sync_jobs,
            IntervalTrigger(minutes=10),
            id="reap_zombie_sync_jobs",
            name="Zombie Background Job Reaper (Every 10m)",
            replace_existing=True,
            misfire_grace_time=60,
            max_instances=1,
            coalesce=True,
        )

        # 13. Daily Portal & Attendance Sync at 5:00 AM: Dispatches portal sync and updates attendance every morning
        scheduler.add_job(
            _run_portal_auto_sync,
            CronTrigger(hour=5, minute=0, timezone=settings.timezone),
            id="daily_portal_sync_5am",
            name="Daily University Portal & Attendance Sync at 5:00 AM",
            replace_existing=True,
            misfire_grace_time=600,
            max_instances=1,
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
