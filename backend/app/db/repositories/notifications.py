from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import Optional, List
from datetime import datetime, timezone

from app.db.models import Notification, NotificationPreference, NotificationTemplate, NotificationStatus, DailyReport


class NotificationRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, notification_id: int) -> Optional[Notification]:
        return self.db.query(Notification).filter(Notification.id == notification_id).first()

    def get_by_idempotency_key(self, idempotency_key: str) -> Optional[Notification]:
        return self.db.query(Notification).filter(Notification.idempotency_key == idempotency_key).first()

    def get_by_user(self, user_id: str, limit: int = 50, status: NotificationStatus = None) -> List[Notification]:
        query = self.db.query(Notification).filter(Notification.user_id == user_id)
        if status:
            query = query.filter(Notification.status == status)
        return query.order_by(Notification.created_at.desc()).limit(limit).all()

    def get_pending(self, limit: int = 100) -> List[Notification]:
        now = datetime.now(timezone.utc)
        return self.db.query(Notification).filter(
            Notification.status == NotificationStatus.PENDING,
            Notification.scheduled_for.is_(None) | (Notification.scheduled_for <= now),
        ).order_by(Notification.created_at).limit(limit).all()

    def get_failed_retryable(self, limit: int = 100) -> List[Notification]:
        return self.db.query(Notification).filter(
            Notification.status == NotificationStatus.FAILED,
            Notification.retry_count < Notification.max_retries,
        ).order_by(Notification.created_at).limit(limit).all()

    def create(self, notification: Notification) -> Notification:
        self.db.add(notification)
        self.db.commit()
        self.db.refresh(notification)
        return notification

    def update(self, notification: Notification) -> Notification:
        self.db.commit()
        self.db.refresh(notification)
        return notification


class NotificationPreferenceRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_user_preferences(self, user_id: str) -> List[NotificationPreference]:
        return self.db.query(NotificationPreference).filter(
            NotificationPreference.user_id == user_id
        ).all()

    def get_preference(self, user_id: str, notification_type: str, channel: str) -> Optional[NotificationPreference]:
        return self.db.query(NotificationPreference).filter(
            NotificationPreference.user_id == user_id,
            NotificationPreference.notification_type == notification_type,
            NotificationPreference.channel == channel,
        ).first()

    def upsert_preference(
        self,
        user_id: str,
        notification_type: str,
        channel: str,
        enabled: bool = True,
        quiet_hours_start: str = None,
        quiet_hours_end: str = None,
        timezone: str = "UTC",
        frequency: str = "immediate",
    ) -> NotificationPreference:
        pref = self.get_preference(user_id, notification_type, channel)
        if pref:
            pref.enabled = enabled
            pref.quiet_hours_start = quiet_hours_start
            pref.quiet_hours_end = quiet_hours_end
            pref.timezone = timezone
            pref.frequency = frequency
            pref.updated_at = datetime.now(timezone.utc)
        else:
            pref = NotificationPreference(
                user_id=user_id,
                notification_type=notification_type,
                channel=channel,
                enabled=enabled,
                quiet_hours_start=quiet_hours_start,
                quiet_hours_end=quiet_hours_end,
                timezone=timezone,
                frequency=frequency,
            )
            self.db.add(pref)
        self.db.commit()
        self.db.refresh(pref)
        return pref

    def delete_preference(self, user_id: str, notification_type: str, channel: str) -> bool:
        pref = self.get_preference(user_id, notification_type, channel)
        if pref:
            self.db.delete(pref)
            self.db.commit()
            return True
        return False


class DailyReportRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_user_and_date(self, user_id: str, report_date: datetime) -> Optional[DailyReport]:
        return self.db.query(DailyReport).filter(
            DailyReport.user_id == user_id,
            func.date(DailyReport.report_date) == func.date(report_date)
        ).first()

    def create_or_update(self, report_data: dict) -> DailyReport:
        report = self.get_by_user_and_date(report_data["user_id"], report_data["report_date"])
        if report:
            for key, value in report_data.items():
                setattr(report, key, value)
        else:
            report = DailyReport(**report_data)
            self.db.add(report)
        self.db.commit()
        self.db.refresh(report)
        return report

    def get_by_user(self, user_id: str, limit: int = 30) -> List[DailyReport]:
        return self.db.query(DailyReport).filter(DailyReport.user_id == user_id).order_by(DailyReport.report_date.desc()).limit(limit).all()


class NotificationTemplateRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_name(self, name: str, channel: str) -> Optional[NotificationTemplate]:
        return self.db.query(NotificationTemplate).filter(
            NotificationTemplate.name == name,
            NotificationTemplate.channel == channel,
            NotificationTemplate.is_active == True,
        ).first()

    def get_all_active(self, channel: str = None) -> List[NotificationTemplate]:
        query = self.db.query(NotificationTemplate).filter(NotificationTemplate.is_active == True)
        if channel:
            query = query.filter(NotificationTemplate.channel == channel)
        return query.all()

    def create(self, template: NotificationTemplate) -> NotificationTemplate:
        self.db.add(template)
        self.db.commit()
        self.db.refresh(template)
        return template

    def update(self, template: NotificationTemplate) -> NotificationTemplate:
        self.db.commit()
        self.db.refresh(template)
        return template

    def delete(self, name: str, channel: str) -> bool:
        template = self.get_by_name(name, channel)
        if template:
            template.is_active = False
            self.db.commit()
            return True
        return False