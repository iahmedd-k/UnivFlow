from apscheduler.triggers.cron import CronTrigger
from app.services.scheduler import scheduler, start_scheduler, shutdown_scheduler, _run_portal_auto_sync


def test_scheduler_registers_daily_5am_portal_sync():
    """Verify that APScheduler registers the 5:00 AM daily portal sync job."""
    try:
        start_scheduler()
        job = scheduler.get_job("daily_portal_sync_5am")
        assert job is not None, "Job 'daily_portal_sync_5am' should be registered in scheduler"
        assert job.name == "Daily University Portal & Attendance Sync at 5:00 AM"
        assert isinstance(job.trigger, CronTrigger)
        
        # Verify CronTrigger fields: hour=5, minute=0
        fields = {f.name: str(f) for f in job.trigger.fields}
        assert fields["hour"] == "5"
        assert fields["minute"] == "0"
    finally:
        shutdown_scheduler()
