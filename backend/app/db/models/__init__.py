import enum
from sqlalchemy import Column, Integer, String, DateTime, Boolean, Text, ForeignKey, Enum as SQLEnum, UniqueConstraint, Index, Float
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.database import Base


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


class GoogleCredential(Base):
    __tablename__ = "google_credentials"

    id = Column(Integer, primary_key=True, index=True)
    access_token = Column(Text, nullable=False)
    refresh_token = Column(Text)
    token_uri = Column(String(500))
    client_id = Column(String(500))
    client_secret = Column(String(500))
    scopes = Column(Text)
    expiry = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id = Column(Integer, primary_key=True, index=True)
    trigger = Column(SQLEnum(AgentRunTrigger), nullable=False)
    status = Column(SQLEnum(AgentRunStatus), default=AgentRunStatus.RUNNING)
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    finished_at = Column(DateTime(timezone=True), nullable=True)
    duration_seconds = Column(Integer, nullable=True)
    assignments_found = Column(Integer, default=0)
    changes_found = Column(Integer, default=0)
    notifications_sent = Column(Integer, default=0)
    errors = Column(Text, nullable=True)
    error_details = Column(Text, nullable=True)

    events = relationship("AgentEvent", back_populates="run")


class AgentEvent(Base):
    __tablename__ = "agent_events"

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(Integer, ForeignKey("agent_runs.id"), nullable=False)
    event_type = Column(String(100), nullable=False)
    source = Column(String(50), nullable=False)
    status = Column(String(50), nullable=False)
    message = Column(Text)
    details = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    run = relationship("AgentRun", back_populates="events")


class Course(Base):
    __tablename__ = "courses"

    id = Column(Integer, primary_key=True, index=True)
    external_id = Column(String(255), unique=True, nullable=False, index=True)
    name = Column(String(500), nullable=False)
    section = Column(String(100))
    description = Column(Text)
    room = Column(String(100))
    teacher_name = Column(String(255))
    course_state = Column(String(50))
    alternate_link = Column(String(500))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    assignments = relationship("Assignment", back_populates="course")
    schedules = relationship("ClassSchedule", back_populates="course")
    attendance_records = relationship("AttendanceRecord", back_populates="course")


class Assignment(Base):
    __tablename__ = "assignments"

    id = Column(Integer, primary_key=True, index=True)
    external_id = Column(String(255), unique=True, nullable=False, index=True)
    course_id = Column(Integer, ForeignKey("courses.id"), nullable=False)
    title = Column(String(500), nullable=False)
    work_type = Column(String(50), nullable=True)
    is_quiz = Column(Boolean, default=False, nullable=False)
    description = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    due_at = Column(DateTime(timezone=True), nullable=True)
    due_date = Column(DateTime(timezone=True), nullable=True)
    url = Column(String(500))
    state = Column(SQLEnum(CourseworkState), default=CourseworkState.PUBLISHED)
    submission_state = Column(SQLEnum(SubmissionState), nullable=True)
    status = Column(SQLEnum(AssignmentStatus), default=AssignmentStatus.DRAFT)
    last_synced_at = Column(DateTime(timezone=True), server_default=func.now())

    course = relationship("Course", back_populates="assignments")
    materials = relationship("AssignmentMaterial", back_populates="assignment")
    solution = relationship("AssignmentSolution", back_populates="assignment", uselist=False)
    submission = relationship("Submission", back_populates="assignment", uselist=False)


class AssignmentMaterial(Base):
    __tablename__ = "assignment_materials"

    id = Column(Integer, primary_key=True, index=True)
    assignment_id = Column(Integer, ForeignKey("assignments.id"), nullable=False)
    material_type = Column(String(50), nullable=False)
    title = Column(String(500))
    url = Column(String(500))
    drive_file_id = Column(String(255))
    mime_type = Column(String(100))
    content = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    assignment = relationship("Assignment", back_populates="materials")


class AssignmentTemplate(Base):
    __tablename__ = "assignment_templates"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    google_doc_id = Column(String(255), nullable=False)
    google_drive_file_id = Column(String(255))
    mime_type = Column(String(100))
    is_default = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class AssignmentSolution(Base):
    __tablename__ = "assignment_solutions"

    id = Column(Integer, primary_key=True, index=True)
    assignment_id = Column(Integer, ForeignKey("assignments.id"), unique=True, nullable=False)
    draft_content = Column(Text)
    validated_content = Column(Text)
    validation_errors = Column(Text)
    retry_count = Column(Integer, default=0)
    ai_provider = Column(String(50))
    generated_at = Column(DateTime(timezone=True), server_default=func.now())
    validated_at = Column(DateTime(timezone=True), nullable=True)

    assignment = relationship("Assignment", back_populates="solution")


class Submission(Base):
    __tablename__ = "submissions"

    id = Column(Integer, primary_key=True, index=True)
    assignment_id = Column(Integer, ForeignKey("assignments.id"), unique=True, nullable=False)
    google_doc_id = Column(String(255))
    google_drive_file_id = Column(String(255))
    classroom_attachment_id = Column(String(255))
    attached_at = Column(DateTime(timezone=True), nullable=True)
    submitted_at = Column(DateTime(timezone=True), nullable=True)
    submission_state = Column(SQLEnum(SubmissionState), nullable=True)
    approved_by_user = Column(Boolean, default=False)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    assignment = relationship("Assignment", back_populates="submission")


class ClassSchedule(Base):
    __tablename__ = "class_schedules"

    id = Column(Integer, primary_key=True, index=True)
    external_id = Column(String(255), unique=True, nullable=False, index=True)
    course_id = Column(Integer, ForeignKey("courses.id"), nullable=False)
    subject = Column(String(255))
    date = Column(DateTime(timezone=True), nullable=False)
    start_time = Column(DateTime(timezone=True), nullable=False)
    end_time = Column(DateTime(timezone=True), nullable=False)
    teacher = Column(String(255))
    room = Column(String(100))
    status = Column(String(50), default="scheduled")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    course = relationship("Course", back_populates="schedules")


class TimetableEntry(Base):
    __tablename__ = "timetable_entries"

    id = Column(Integer, primary_key=True, index=True)
    external_id = Column(String(64), unique=True, nullable=False, index=True)
    subject = Column(String(255), nullable=False)
    weekday = Column(Integer, nullable=False)
    start_time = Column(String(10), nullable=False)
    end_time = Column(String(10), nullable=False)
    teacher = Column(String(255))
    room = Column(String(100))
    semester_name = Column(String(120))
    semester_start = Column(DateTime(timezone=True))
    semester_end = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class AttendanceRecord(Base):
    __tablename__ = "attendance_records"

    id = Column(Integer, primary_key=True, index=True)
    external_id = Column(String(255), unique=True, nullable=False, index=True)
    course_id = Column(Integer, ForeignKey("courses.id"), nullable=False)
    subject = Column(String(255))
    attended = Column(Integer, default=0)
    total = Column(Integer, default=0)
    percentage = Column(Float, default=0.0)
    last_updated = Column(DateTime(timezone=True), server_default=func.now())
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    course = relationship("Course", back_populates="attendance_records")


class Exam(Base):
    __tablename__ = "exams"

    id = Column(Integer, primary_key=True, index=True)
    external_id = Column(String(255), unique=True, nullable=False, index=True)
    course_id = Column(Integer, ForeignKey("courses.id"), nullable=True)
    title = Column(String(500))
    date = Column(DateTime(timezone=True))
    time = Column(String(50))
    room = Column(String(100))
    status = Column(String(50))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class Quiz(Base):
    __tablename__ = "quizzes"

    id = Column(Integer, primary_key=True, index=True)
    external_id = Column(String(255), unique=True, nullable=False, index=True)
    course_id = Column(Integer, ForeignKey("courses.id"), nullable=True)
    title = Column(String(500))
    date = Column(DateTime(timezone=True))
    time = Column(String(50))
    room = Column(String(100))
    status = Column(String(50))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class Announcement(Base):
    __tablename__ = "announcements"

    id = Column(Integer, primary_key=True, index=True)
    external_id = Column(String(255), unique=True, nullable=False, index=True)
    course_id = Column(Integer, nullable=True)
    title = Column(String(500))
    content = Column(Text)
    url = Column(String(1000))
    source = Column(String(50))
    fingerprint = Column(String(64), nullable=False, index=True)
    published_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class ChangeEvent(Base):
    __tablename__ = "change_events"

    id = Column(Integer, primary_key=True, index=True)
    event_type = Column(SQLEnum(ChangeEventType), nullable=False)
    external_id = Column(String(255), index=True)
    subject = Column(String(255))
    old_value = Column(Text)
    new_value = Column(Text)
    date = Column(DateTime(timezone=True))
    notified = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    notification_type = Column(String(100), nullable=False)
    recipient = Column(String(255), nullable=False)
    subject = Column(String(500))
    payload = Column(Text)
    status = Column(SQLEnum(NotificationStatus), default=NotificationStatus.PENDING)
    external_id = Column(String(255))
    idempotency_key = Column(String(255), unique=True, index=True)
    sent_at = Column(DateTime(timezone=True), nullable=True)
    error = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class DailyReport(Base):
    __tablename__ = "daily_reports"

    id = Column(Integer, primary_key=True, index=True)
    report_date = Column(DateTime(timezone=True), unique=True, nullable=False, index=True)
    google_document_id = Column(String(255))
    google_drive_file_id = Column(String(255))
    content = Column(Text)
    status = Column(String(50), default="generated")
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Setting(Base):
    __tablename__ = "settings"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(255), unique=True, nullable=False, index=True)
    value = Column(Text)
    description = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


Index("ix_agent_runs_started_at", AgentRun.started_at)
Index("ix_agent_events_run_id", AgentEvent.run_id)
Index("ix_assignments_course_id", Assignment.course_id)
Index("ix_assignments_status", Assignment.status)
Index("ix_class_schedules_course_id", ClassSchedule.course_id)
Index("ix_class_schedules_date", ClassSchedule.date)
Index("ix_attendance_records_course_id", AttendanceRecord.course_id)
Index("ix_change_events_date", ChangeEvent.date)
Index("ix_notifications_idempotency", Notification.idempotency_key)
Index("ix_notifications_status", Notification.status)
