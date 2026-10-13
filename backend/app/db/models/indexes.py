"""Named indexes declared across the ORM models."""

from .common import Index
from .agents import AgentRun, AgentEvent
from .assignments import Assignment
from .assignments import BrowserAutomationJob
from .schedules import ClassSchedule, AttendanceRecord
from .academic_records import ChangeEvent
from .notifications import Notification

Index("ix_agent_runs_started_at", AgentRun.started_at)
Index("ix_agent_events_run_id", AgentEvent.run_id)
Index("ix_assignments_course_id", Assignment.course_id)
Index("ix_assignments_status", Assignment.status)
Index("ix_browser_jobs_status_queued_at", BrowserAutomationJob.status, BrowserAutomationJob.queued_at)
Index("ix_class_schedules_course_id", ClassSchedule.course_id)
Index("ix_class_schedules_date", ClassSchedule.date)
Index("ix_attendance_records_course_id", AttendanceRecord.course_id)
Index("ix_change_events_date", ChangeEvent.date)
Index("ix_notifications_idempotency", Notification.idempotency_key)
Index("ix_notifications_status", Notification.status)
