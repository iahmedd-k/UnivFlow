from .common import *
from .enums import *


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
