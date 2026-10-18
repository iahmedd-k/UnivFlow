from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
from datetime import datetime, timezone
from jinja2 import Environment, BaseLoader
import json

from app.db.models import (
    Notification,
    NotificationPreference,
    NotificationTemplate,
    NotificationStatus,
)
from app.db.repositories.notifications import NotificationRepository, NotificationPreferenceRepository
from app.services.email import send_email, send_template_email
from app.core.config import settings
from app.core.logging import logger


class NotificationService:
    def __init__(self, db: Session):
        self.db = db
        self.notification_repo = NotificationRepository(db)
        self.preference_repo = NotificationPreferenceRepository(db)
        self.jinja_env = Environment(loader=BaseLoader())

    def get_user_preferences(self, user_id: str, notification_type: str = None) -> List[NotificationPreference]:
        """Get user's notification preferences, optionally filtered by type."""
        query = self.db.query(NotificationPreference).filter(
            NotificationPreference.user_id == user_id,
            NotificationPreference.enabled == True,
        )
        if notification_type:
            query = query.filter(NotificationPreference.notification_type == notification_type)
        return query.all()

    def is_notification_allowed(self, user_id: str, notification_type: str, channel: str) -> bool:
        """Check if user has enabled this notification type for this channel."""
        pref = self.db.query(NotificationPreference).filter(
            NotificationPreference.user_id == user_id,
            NotificationPreference.notification_type == notification_type,
            NotificationPreference.channel == channel,
        ).first()
        return pref is not None and pref.enabled

    def get_template(self, name: str, channel: str) -> Optional[NotificationTemplate]:
        """Get active notification template."""
        return self.db.query(NotificationTemplate).filter(
            NotificationTemplate.name == name,
            NotificationTemplate.channel == channel,
            NotificationTemplate.is_active == True,
        ).first()

    def render_template(self, template: NotificationTemplate, data: Dict[str, Any]) -> tuple[str, str]:
        """Render template with data, returns (subject, body)."""
        subject = template.subject_template
        body = template.body_template
        
        if subject:
            subject_tmpl = self.jinja_env.from_string(subject)
            subject = subject_tmpl.render(**data)
        else:
            subject = data.get("subject", "Uniflow Notification")
        
        body_tmpl = self.jinja_env.from_string(body)
        body = body_tmpl.render(**data)
        
        return subject, body

    def create_notification(
        self,
        user_id: str,
        notification_type: str,
        channel: str = "email",
        recipient: str = None,
        subject: str = None,
        body: str = None,
        template_name: str = None,
        template_data: Dict[str, Any] = None,
        external_id: str = None,
        idempotency_key: str = None,
        scheduled_for: datetime = None,
        max_retries: int = 3,
        provider: str = None,
    ) -> Notification:
        """Create a new notification with idempotency check."""
        # Idempotency check
        if idempotency_key:
            existing = self.notification_repo.get_by_idempotency_key(idempotency_key)
            if existing:
                logger.info(f"Notification with idempotency_key {idempotency_key} already exists: {existing.id}")
                return existing

        # Determine recipient if not provided
        if not recipient:
            from app.notifications.router import _get_user_notification_email
            recipient = _get_user_notification_email(self.db, user_id)
            if not recipient:
                raise ValueError(f"No notification recipient found for user {user_id}")

        # Use template if provided
        final_subject = subject
        final_body = body
        template_id = None
        
        if template_name:
            template = self.get_template(template_name, channel)
            if template:
                template_id = template.name
                if template_data is None:
                    template_data = {}
                if subject:
                    template_data["subject"] = subject
                if body:
                    template_data["body"] = body
                # Add default variables
                template_data.setdefault("user_id", user_id)
                template_data.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
                final_subject, final_body = self.render_template(template, template_data)
            else:
                logger.warning(f"Template {template_name} not found for channel {channel}")

        # Use subject from data if not set
        if not final_subject:
            final_subject = subject or (template_data or {}).get("subject") or "Uniflow Notification"

        notification = Notification(
            user_id=user_id,
            notification_type=notification_type,
            channel=channel,
            recipient=recipient,
            subject=final_subject,
            payload=final_body,
            status=NotificationStatus.PENDING,
            external_id=external_id,
            idempotency_key=idempotency_key,
            scheduled_for=scheduled_for,
            max_retries=max_retries,
            template_id=template_id,
            template_data=json.dumps(template_data) if template_data else None,
            provider=provider,
        )
        
        self.db.add(notification)
        self.db.commit()
        self.db.refresh(notification)
        
        logger.info(f"Created notification {notification.id} for user {user_id} via {channel}")
        return notification

    def send_notification(self, notification: Notification) -> bool:
        """Send notification via appropriate channel."""
        success = False
        error = None
        
        try:
            if notification.channel == "email":
                success = self._send_email(notification)
            elif notification.channel == "sms":
                success = self._send_sms(notification)
            elif notification.channel == "whatsapp":
                success = self._send_whatsapp(notification)
            elif notification.channel == "push":
                success = self._send_push(notification)
            else:
                error = f"Unsupported channel: {notification.channel}"
                success = False

        except Exception as e:
            error = str(e)
            success = False
            logger.error(f"Failed to send notification {notification.id}: {e}")

        # Update notification status
        if success:
            notification.status = NotificationStatus.SENT
            notification.sent_at = datetime.now(timezone.utc)
            notification.delivered_at = datetime.now(timezone.utc)
            notification.error = None
        else:
            notification.retry_count += 1
            notification.error = error
            if notification.retry_count >= notification.max_retries:
                notification.status = NotificationStatus.FAILED
            else:
                notification.status = NotificationStatus.PENDING
                # Schedule retry with exponential backoff
                from datetime import timedelta
                retry_delay = min(300 * (2 ** notification.retry_count), 3600)  # Max 1 hour
                notification.scheduled_for = datetime.now(timezone.utc) + timedelta(seconds=retry_delay)

        self.db.commit()
        return success

    def _send_email(self, notification: Notification) -> bool:
        """Send email notification."""
        html_content = notification.payload
        text_content = None
        
        # Convert HTML to text if needed
        if html_content and "<" in html_content:
            import re
            text_content = re.sub(r'<[^>]+>', '', html_content)
            text_content = re.sub(r'\s+', ' ', text_content).strip()

        return send_email(
            to_email=notification.recipient,
            subject=notification.subject or "Uniflow Notification",
            html_content=html_content,
            text_content=text_content,
            categories=[f"notification", notification.notification_type],
            custom_args={
                "notification_id": str(notification.id),
                "idempotency_key": notification.idempotency_key or "",
                "channel": "email",
            },
        )

    def _send_sms(self, notification: Notification) -> bool:
        """Send SMS notification via Twilio or similar provider."""
        # TODO: Implement Twilio SMS sending
        logger.warning(f"SMS sending not implemented for notification {notification.id}")
        return False

    def _send_whatsapp(self, notification: Notification) -> bool:
        """Send WhatsApp notification."""
        # TODO: Implement WhatsApp Business API
        logger.warning(f"WhatsApp sending not implemented for notification {notification.id}")
        return False

    def _send_push(self, notification: Notification) -> bool:
        """Send push notification via FCM."""
        # TODO: Implement FCM push notification
        logger.warning(f"Push notification not implemented for notification {notification.id}")
        return False

    def process_pending_notifications(self, limit: int = 50) -> int:
        """Process pending notifications that are due."""
        now = datetime.now(timezone.utc)
        pending = self.db.query(Notification).filter(
            Notification.status == NotificationStatus.PENDING,
            Notification.scheduled_for.is_(None) | (Notification.scheduled_for <= now),
        ).limit(limit).all()

        sent_count = 0
        for notification in pending:
            # Check user preferences
            if not self.is_notification_allowed(notification.user_id, notification.notification_type, notification.channel):
                logger.info(f"Skipping notification {notification.id} - disabled by user preference")
                notification.status = NotificationStatus.FAILED
                notification.error = "Disabled by user preference"
                self.db.commit()
                continue

            if self.send_notification(notification):
                sent_count += 1

        return sent_count

    def retry_failed_notifications(self, limit: int = 50) -> int:
        """Retry failed notifications that haven't exceeded max retries."""
        failed = self.db.query(Notification).filter(
            Notification.status == NotificationStatus.FAILED,
            Notification.retry_count < Notification.max_retries,
        ).limit(limit).all()

        retried_count = 0
        for notification in failed:
            notification.status = NotificationStatus.PENDING
            notification.scheduled_for = datetime.now(timezone.utc)
            self.db.commit()
            
            if self.send_notification(notification):
                retried_count += 1

        return retried_count

    def cleanup_old_notifications(self, days: int = 90) -> int:
        """Delete old sent/failed notifications."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        deleted = self.db.query(Notification).filter(
            Notification.created_at < cutoff,
            Notification.status.in_([NotificationStatus.SENT, NotificationStatus.FAILED, NotificationStatus.CANCELLED]),
        ).delete(synchronize_session=False)
        self.db.commit()
        return deleted


import re
from datetime import timedelta
