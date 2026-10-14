"""Repository exports retained for backwards-compatible imports."""

from .credentials import GoogleCredentialRepository
from .agents import AgentRunRepository
from .agents import AgentEventRepository
from .coursework import CourseRepository
from .coursework import AssignmentRepository
from .coursework import AssignmentMaterialRepository
from .coursework import AssignmentTemplateRepository
from .coursework import AssignmentSolutionRepository
from .coursework import SubmissionRepository
from .academics import ClassScheduleRepository
from .academics import AttendanceRecordRepository
from .academics import ExamRepository
from .academics import QuizRepository
from .academics import AnnouncementRepository
from .academics import ChangeEventRepository
from .notifications import NotificationRepository
from .notifications import DailyReportRepository
from .settings import SettingRepository

__all__ = [
    "GoogleCredentialRepository",
    "AgentRunRepository",
    "AgentEventRepository",
    "CourseRepository",
    "AssignmentRepository",
    "AssignmentMaterialRepository",
    "AssignmentTemplateRepository",
    "AssignmentSolutionRepository",
    "SubmissionRepository",
    "ClassScheduleRepository",
    "AttendanceRecordRepository",
    "ExamRepository",
    "QuizRepository",
    "AnnouncementRepository",
    "ChangeEventRepository",
    "NotificationRepository",
    "DailyReportRepository",
    "SettingRepository",
]
