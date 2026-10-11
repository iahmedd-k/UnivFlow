from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Optional
from datetime import datetime

from app.db.database import get_db
from app.db.repositories import NotificationRepository
from app.db.models import Notification, NotificationStatus, Setting
from app.services.email import send_email
from app.core.config import settings
from app.core.logging import logger
from app.auth.clerk_auth import get_current_user_optional

router = APIRouter(prefix="/notifications", tags=["Notifications"])


def _get_user_notification_email(db: Session, user_id: str) -> Optional[str]:
    """Get the user's configured notification email from settings"""
    setting = db.query(Setting).filter(Setting.key == f"notification_email_{user_id}").first()
    return setting.value if setting and setting.value else None


@router.get("/my-email", response_model=dict)
def get_my_notification_email(
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional)
):
    """Get the current user's configured notification email"""
    user_id = clerk_user.get("id") if clerk_user else None
    if not user_id:
        raise HTTPException(status_code=401, detail="User not authenticated")
    
    email = _get_user_notification_email(db, user_id)
    return {"email": email}


@router.get("", response_model=List[dict])
def get_notifications(
    status: str = None,
    limit: int = 50,
    db: Session = Depends(get_db)
):
    repo = NotificationRepository(db)
    query = db.query(Notification)
    if status:
        query = query.filter(Notification.status == status)
    notifications = query.order_by(Notification.created_at.desc()).limit(limit).all()
    return [
        {
            "id": n.id,
            "notification_type": n.notification_type,
            "recipient": n.recipient,
            "subject": n.subject,
            "payload": n.payload,
            "status": n.status.value if n.status else None,
            "external_id": n.external_id,
            "idempotency_key": n.idempotency_key,
            "sent_at": n.sent_at,
            "error": n.error,
            "created_at": n.created_at,
        }
        for n in notifications
    ]


@router.get("/pending", response_model=List[dict])
def get_pending_notifications(db: Session = Depends(get_db)):
    repo = NotificationRepository(db)
    notifications = repo.get_pending()
    return [
        {
            "id": n.id,
            "notification_type": n.notification_type,
            "recipient": n.recipient,
            "subject": n.subject,
            "payload": n.payload,
            "status": n.status.value if n.status else None,
            "external_id": n.external_id,
            "idempotency_key": n.idempotency_key,
            "created_at": n.created_at,
        }
        for n in notifications
    ]


@router.get("/{notification_id}", response_model=dict)
def get_notification(notification_id: int, db: Session = Depends(get_db)):
    notification = db.query(Notification).filter(Notification.id == notification_id).first()
    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")
    return {
        "id": notification.id,
        "notification_type": notification.notification_type,
        "recipient": notification.recipient,
        "subject": notification.subject,
        "payload": notification.payload,
        "status": notification.status.value if notification.status else None,
        "external_id": notification.external_id,
        "idempotency_key": notification.idempotency_key,
        "sent_at": notification.sent_at,
        "error": notification.error,
        "created_at": notification.created_at,
    }


@router.get("/stats/summary", response_model=dict)
def get_notification_stats(db: Session = Depends(get_db)):
    total = db.query(Notification).count()
    pending = db.query(Notification).filter(Notification.status == NotificationStatus.PENDING).count()
    sent = db.query(Notification).filter(Notification.status == NotificationStatus.SENT).count()
    failed = db.query(Notification).filter(Notification.status == NotificationStatus.FAILED).count()

    return {
        "total": total,
        "pending": pending,
        "sent": sent,
        "failed": failed,
    }


def _build_email_content(notification: Notification) -> tuple[str, str]:
    """Build HTML and text content from notification"""
    subject = notification.subject or "Uniflow Notification"
    payload = notification.payload or ""
    notification_type = notification.notification_type or "general"

    html = f"""
    <html>
    <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">
        <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 30px; border-radius: 10px 10px 0 0; text-align: center;">
            <h1 style="color: white; margin: 0; font-size: 24px;">Uniflow</h1>
        </div>
        <div style="background: #f9f9f9; padding: 30px; border-radius: 0 0 10px 10px; border: 1px solid #eee;">
            <h2 style="color: #333; margin-top: 0;">{subject}</h2>
            <div style="background: white; padding: 20px; border-radius: 8px; border-left: 4px solid #667eea;">
                {payload.replace(chr(10), '<br>') if payload else '<em>No content</em>'}
            </div>
            <hr style="border: none; border-top: 1px solid #eee; margin: 20px 0;">
            <p style="color: #888; font-size: 12px; margin: 0;">
                This is an automated notification from Uniflow.<br>
                Type: {notification_type} | Sent at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
            </p>
        </div>
    </body>
    </html>
    """

    text = f"""
{subject}

{payload if payload else 'No content'}

---
This is an automated notification from Uniflow.
Type: {notification_type}
Sent at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
    """

    return html.strip(), text.strip()


def _send_notification_email(notification_id: int):
    """Background task to send a single notification email"""
    from app.db.database import SessionLocal
    db = SessionLocal()
    try:
        notification = db.query(Notification).filter(Notification.id == notification_id).first()
        if not notification:
            logger.error(f"Notification {notification_id} not found")
            return

        if notification.status != NotificationStatus.PENDING:
            logger.warning(f"Notification {notification_id} already processed: {notification.status}")
            return

        html_content, text_content = _build_email_content(notification)

        success = send_email(
            to_email=notification.recipient,
            subject=notification.subject or "Uniflow Notification",
            html_content=html_content,
            text_content=text_content,
            categories=["notification", notification.notification_type or "general"],
            custom_args={"notification_id": str(notification_id), "idempotency_key": notification.idempotency_key or ""},
        )

        if success:
            notification.status = NotificationStatus.SENT
            notification.sent_at = func.now()
            notification.error = None
        else:
            notification.status = NotificationStatus.FAILED
            notification.error = "SendGrid API error"
        
        db.commit()
        logger.info(f"Notification {notification_id} {'sent' if success else 'failed'} to {notification.recipient}")

    except Exception as e:
        logger.error(f"Failed to send notification {notification_id}: {e}")
        try:
            notification = db.query(Notification).filter(Notification.id == notification_id).first()
            if notification:
                notification.status = NotificationStatus.FAILED
                notification.error = str(e)
                db.commit()
        except Exception:
            pass
    finally:
        db.close()


@router.post("/send/{notification_id}", response_model=dict)
def send_notification(notification_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Queue a notification for sending via email"""
    notification = db.query(Notification).filter(Notification.id == notification_id).first()
    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")

    if notification.status == NotificationStatus.SENT:
        return {"message": "Already sent", "notification_id": notification_id, "status": "sent"}

    background_tasks.add_task(_send_notification_email, notification_id)
    return {"message": "Notification queued for sending", "notification_id": notification_id}


@router.post("/send-pending", response_model=dict)
def send_pending_notifications(background_tasks: BackgroundTasks, limit: int = 50, db: Session = Depends(get_db)):
    """Queue all pending notifications for sending"""
    notifications = db.query(Notification).filter(
        Notification.status == NotificationStatus.PENDING
    ).limit(limit).all()

    if not notifications:
        return {"message": "No pending notifications", "count": 0}

    for n in notifications:
        background_tasks.add_task(_send_notification_email, n.id)

    return {"message": f"Queued {len(notifications)} notifications", "count": len(notifications)}


@router.post("/create", response_model=dict)
def create_notification(
    notification_type: str,
    recipient: str = None,
    subject: str = "Uniflow Notification",
    payload: str = None,
    external_id: str = None,
    idempotency_key: str = None,
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional)
):
    """Create a new notification (queued as PENDING). If recipient not provided, uses current user's notification email."""
    # Determine recipient
    if not recipient:
        user_id = clerk_user.get("id") if clerk_user else None
        if not user_id:
            raise HTTPException(status_code=401, detail="User not authenticated and no recipient provided")
        recipient = _get_user_notification_email(db, user_id)
        if not recipient:
            raise HTTPException(status_code=400, detail="No notification email configured. Please set one in Settings.")

    # Check idempotency
    if idempotency_key:
        existing = db.query(Notification).filter(Notification.idempotency_key == idempotency_key).first()
        if existing:
            return {"message": "Already exists", "notification_id": existing.id, "status": existing.status.value}

    notification = Notification(
        notification_type=notification_type,
        recipient=recipient,
        subject=subject,
        payload=payload,
        external_id=external_id,
        idempotency_key=idempotency_key,
        status=NotificationStatus.PENDING,
    )
    db.add(notification)
    db.commit()
    db.refresh(notification)

    return {
        "message": "Notification created",
        "notification_id": notification.id,
        "status": notification.status.value,
    }


@router.post("/create-for-me", response_model=dict)
def create_notification_for_me(
    notification_type: str,
    subject: str = "Uniflow Notification",
    payload: str = None,
    external_id: str = None,
    idempotency_key: str = None,
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional)
):
    """Create a notification for the current user using their configured notification email"""
    user_id = clerk_user.get("id") if clerk_user else None
    if not user_id:
        raise HTTPException(status_code=401, detail="User not authenticated")

    recipient = _get_user_notification_email(db, user_id)
    if not recipient:
        raise HTTPException(status_code=400, detail="No notification email configured. Please set one in Settings.")

    return create_notification(
        notification_type=notification_type,
        recipient=recipient,
        subject=subject,
        payload=payload,
        external_id=external_id,
        idempotency_key=idempotency_key,
        db=db,
        clerk_user=clerk_user
    )


@router.post("/check-alerts", response_model=dict)
def check_and_send_alerts(
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional)
):
    """Trigger on-demand check for low-attendance class-day warnings, upcoming 10-min class reminders, and GCR deadlines."""
    from app.services.alert_service import AlertService
    user_id = clerk_user.get("id") if clerk_user else "dev_student_user"
    service = AlertService(db)
    att_alerts = service.generate_daily_attendance_warnings(user_id=user_id, send_immediately=True)
    tt_reminders = service.generate_upcoming_class_reminders(user_id=user_id, send_immediately=True)
    gcr_alerts = service.generate_upcoming_assignment_reminders(user_id=user_id, send_immediately=True)
    return {
        "status": "success",
        "attendance_warnings_generated": len(att_alerts),
        "attendance_warnings": att_alerts,
        "timetable_reminders_generated": len(tt_reminders),
        "timetable_reminders": tt_reminders,
        "assignment_deadlines_generated": len(gcr_alerts),
        "assignment_deadlines": gcr_alerts,
    }


@router.get("/preview-alerts", response_model=dict)
def preview_alerts(
    target_date: Optional[str] = None,
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional)
):
    """Preview low-attendance warnings without persisting or sending emails."""
    from app.services.alert_service import AlertService
    from datetime import date
    user_id = clerk_user.get("id") if clerk_user else "dev_student_user"
    service = AlertService(db)
    
    t_date = date.fromisoformat(target_date) if target_date else None
    att_alerts = service.generate_daily_attendance_warnings(
        user_id=user_id, target_date=t_date, send_immediately=False
    )
    # Rollback to avoid persisting previewed notifications
    db.rollback()
    return {
        "user_id": user_id,
        "attendance_warnings": att_alerts,
    }