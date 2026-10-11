import enum


class AgentRunStatus(str, enum.Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class AgentRunTrigger(str, enum.Enum):
    SCHEDULED = "scheduled"
    MANUAL = "manual"
    WEBHOOK = "webhook"


class AssignmentStatus(str, enum.Enum):
    DRAFT = "draft"
    PENDING = "pending"
    GENERATING = "generating"
    GENERATED = "generated"
    VALIDATION_FAILED = "validation_failed"
    READY_FOR_REVIEW = "ready_for_review"
    APPROVED = "approved"
    SUBMITTED = "submitted"
    FAILED = "failed"
    OVERDUE = "overdue"


class CourseworkState(str, enum.Enum):
    PUBLISHED = "PUBLISHED"
    DRAFT = "DRAFT"
    DELETED = "DELETED"


class SubmissionState(str, enum.Enum):
    NEW = "NEW"
    CREATED = "CREATED"
    TURNED_IN = "TURNED_IN"
    RETURNED = "RETURNED"
    RECLAIMED = "RECLAIMED"


class ChangeEventType(str, enum.Enum):
    TIMETABLE_CHANGE = "timetable_change"
    ANNOUNCEMENT = "announcement"
    EXAM_CHANGE = "exam_change"
    QUIZ_CHANGE = "quiz_change"
    CLASS_CANCELLED = "class_cancelled"
    CLASS_RESCHEDULED = "class_rescheduled"
    ROOM_CHANGE = "room_change"
    TEACHER_CHANGE = "teacher_change"


class NotificationStatus(str, enum.Enum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"


__all__ = [
    "AgentRunStatus",
    "AgentRunTrigger",
    "AssignmentStatus",
    "CourseworkState",
    "SubmissionState",
    "ChangeEventType",
    "NotificationStatus",
]
