from .common import *
from .enums import *


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(255), nullable=False, default="legacy", index=True)
    notification_type = Column(String(100), nullable=False)
    channel = Column(String(32), nullable=False, default="email")  # email, sms, whatsapp, push
    recipient = Column(String(255), nullable=False)
    subject = Column(String(500))
    payload = Column(Text)
    status = Column(SQLEnum(NotificationStatus), default=NotificationStatus.PENDING)
    external_id = Column(String(255))
    idempotency_key = Column(String(255), unique=True, index=True)
    sent_at = Column(DateTime(timezone=True), nullable=True)
    delivered_at = Column(DateTime(timezone=True), nullable=True)
    error = Column(Text)
    retry_count = Column(Integer, default=0)
    max_retries = Column(Integer, default=3)
    scheduled_for = Column(DateTime(timezone=True), nullable=True)
    template_id = Column(String(100), nullable=True)
    template_data = Column(Text, nullable=True)  # JSON
    provider = Column(String(50), nullable=True)  # sendgrid, twilio, fcm, etc.
    provider_message_id = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class NotificationPreference(Base):
    """User notification preferences per type and channel"""
    __tablename__ = "notification_preferences"
    __table_args__ = (UniqueConstraint("user_id", "notification_type", "channel", name="uq_notif_pref_user_type_channel"),)

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(255), nullable=False, index=True)
    notification_type = Column(String(100), nullable=False)  # e.g., "attendance_warning", "assignment_due", "class_reminder"
    channel = Column(String(32), nullable=False)  # email, sms, whatsapp, push
    enabled = Column(Boolean, default=True)
    quiet_hours_start = Column(String(5), nullable=True)  # HH:MM format
    quiet_hours_end = Column(String(5), nullable=True)    # HH:MM format
    timezone = Column(String(50), default="UTC")
    frequency = Column(String(32), default="immediate")  # immediate, hourly, daily, weekly
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class NotificationTemplate(Base):
    """Reusable notification templates"""
    __tablename__ = "notification_templates"
    __table_args__ = (UniqueConstraint("name", "channel", name="uq_template_name_channel"),)

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, index=True)
    channel = Column(String(32), nullable=False)  # email, sms, whatsapp, push
    subject_template = Column(String(500), nullable=True)  # Jinja2 template
    body_template = Column(Text, nullable=False)  # Jinja2 template
    variables = Column(Text, nullable=True)  # JSON schema of expected variables
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class DailyReport(Base):
    __tablename__ = "daily_reports"
    __table_args__ = (UniqueConstraint("user_id", "report_date", name="uq_daily_reports_user_report_date"),)

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(255), nullable=False, default="legacy", index=True)
    report_date = Column(DateTime(timezone=True), nullable=False, index=True)
    google_document_id = Column(String(255))
    google_drive_file_id = Column(String(255))
    content = Column(Text)
    status = Column(String(50), default="generated")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
