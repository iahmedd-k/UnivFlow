from sqlalchemy import func
from sqlalchemy.orm import Session
from typing import Optional, List
from datetime import datetime
from app.db.models import (
    GoogleCredential, AgentRun, AgentEvent, Course, Assignment,
    AssignmentMaterial, AssignmentTemplate, AssignmentSolution, Submission, ClassSchedule,
    AttendanceRecord, Exam, Quiz, Announcement, ChangeEvent,
    Notification, DailyReport, Setting
)

class ChangeEventRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, change_data: dict) -> ChangeEvent:
        change = ChangeEvent(**change_data)
        self.db.add(change)
        self.db.commit()
        self.db.refresh(change)
        return change

    def get_unnotified(self) -> List[ChangeEvent]:
        return self.db.query(ChangeEvent).filter(ChangeEvent.notified == False).all()

    def mark_notified(self, change_id: int):
        change = self.db.query(ChangeEvent).filter(ChangeEvent.id == change_id).first()
        if change:
            change.notified = True
            self.db.commit()


class NotificationRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, notification_data: dict) -> Notification:
        notification = Notification(**notification_data)
        self.db.add(notification)
        self.db.commit()
        self.db.refresh(notification)
        return notification

    def get_by_idempotency_key(self, key: str) -> Optional[Notification]:
        return self.db.query(Notification).filter(Notification.idempotency_key == key).first()

    def update_status(self, notification_id: int, status: str, error: str = None, external_id: str = None):
        notification = self.db.query(Notification).filter(Notification.id == notification_id).first()
        if notification:
            notification.status = status
            if error:
                notification.error = error
            if external_id:
                notification.external_id = external_id
            if status == "sent":
                notification.sent_at = datetime.now()
            self.db.commit()

    def get_pending(self) -> List[Notification]:
        return self.db.query(Notification).filter(Notification.status == "pending").all()


class DailyReportRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_date(self, report_date: datetime) -> Optional[DailyReport]:
        return self.db.query(DailyReport).filter(DailyReport.report_date == report_date).first()

    def create(self, report_data: dict) -> DailyReport:
        report = DailyReport(**report_data)
        self.db.add(report)
        self.db.commit()
        self.db.refresh(report)
        return report

    def get_recent(self, limit: int = 30) -> List[DailyReport]:
        return self.db.query(DailyReport).order_by(DailyReport.report_date.desc()).limit(limit).all()
