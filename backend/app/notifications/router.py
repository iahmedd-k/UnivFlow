from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
import json
import re
from html import escape
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Optional
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.db.database import get_db
from app.db.repositories import NotificationRepository
from app.db.models import Notification, NotificationStatus, Setting
from app.services.email import send_email
from app.core.config import settings
from app.core.logging import logger
from app.auth.clerk_auth import get_current_user_optional
from app.auth.ownership import require_user_id, user_owner_ids

router = APIRouter(prefix="/notifications", tags=["Notifications"])


class DailyBriefingPreferencePayload(BaseModel):
    enabled: bool = True
    time: str = Field(default="07:30", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    timezone: str = "Asia/Karachi"


def _daily_briefing_key(user_id: str) -> str:
    return f"automation_daily_briefing_{user_id}"


@router.get("/daily-briefing-preferences", response_model=dict)
def get_daily_briefing_preferences(
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional),
):
    user_id = require_user_id(clerk_user)
    row = db.query(Setting).filter(Setting.key == _daily_briefing_key(user_id)).first()
    try:
        saved = json.loads(row.value) if row and row.value else {}
    except (TypeError, json.JSONDecodeError):
        saved = {}
    enabled = bool(saved.get("enabled", True))
    run_time = str(saved.get("time", "07:30"))
    if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", run_time):
        run_time = "07:30"
    timezone_name = str(saved.get("timezone", settings.timezone))
    try:
        zone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        timezone_name = settings.timezone
        zone = ZoneInfo(timezone_name)
    now = datetime.now(zone)
    scheduled = datetime.combine(now.date(), datetime.strptime(run_time, "%H:%M").time(), tzinfo=zone)
    if scheduled <= now:
        scheduled += timedelta(days=1)
    last = db.query(Notification).filter(
        Notification.user_id.in_(user_owner_ids(user_id)),
        Notification.notification_type == "daily_morning_digest",
    ).order_by(Notification.created_at.desc()).first()
    last_status = getattr(last.status, "value", last.status) if last else None
    return {
        "enabled": enabled,
        "time": run_time,
        "timezone": timezone_name,
        "last_run": last.sent_at or last.created_at if last else None,
        "last_result": {"status": last_status, "error": last.error} if last else None,
        "next_run": scheduled if enabled else None,
    }


@router.put("/daily-briefing-preferences", response_model=dict)
def update_daily_briefing_preferences(
    payload: DailyBriefingPreferencePayload,
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional),
):
    user_id = require_user_id(clerk_user)
    try:
        ZoneInfo(payload.timezone)
    except ZoneInfoNotFoundError as error:
        raise HTTPException(status_code=400, detail="Choose a valid timezone.") from error
    key = _daily_briefing_key(user_id)
    row = db.query(Setting).filter(Setting.key == key).first()
    value = json.dumps({"enabled": payload.enabled, "time": payload.time, "timezone": payload.timezone})
    if row:
        row.value = value
    else:
        db.add(Setting(key=key, value=value, description="Per-account daily academic briefing schedule"))
    db.commit()
    return get_daily_briefing_preferences(db, clerk_user)


class CreateNotificationForMeRequest(BaseModel):
    notification_type: str
    subject: str = "Uniflow Notification"
    payload: Optional[str] = None
    external_id: Optional[str] = None
    idempotency_key: Optional[str] = None


def _get_user_notification_email(db: Session, user_id: str = "") -> Optional[str]:
    """Resolve only this user's configured address; never borrow another account's email."""
    if user_id:
        setting = db.query(Setting).filter(Setting.key == f"notification_email_{user_id}").first()
        if setting and setting.value and setting.value.strip() and "@" in setting.value:
            return setting.value.strip()
        if user_id == "dev_student_user" and not settings.is_production:
            default_s = db.query(Setting).filter(Setting.key == "notification_email_default").first()
            if default_s and default_s.value and "@" in default_s.value:
                return default_s.value.strip()

    clerk_s = db.query(Setting).filter(Setting.key == f"clerk_user_{user_id}").first() if user_id else None
    if clerk_s and clerk_s.value:
        try:
            import json
            data = json.loads(clerk_s.value)
            email = data.get("email") or data.get("emailAddress") or ""
            if email and "@" in email:
                return email.strip()
        except Exception:
            pass

    return None


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
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional),
):
    user_id = require_user_id(clerk_user)
    query = db.query(Notification).filter(Notification.user_id.in_(user_owner_ids(user_id)))
    if status:
        try:
            status_enum = NotificationStatus[status.upper()]
            query = query.filter(Notification.status == status_enum)
        except (KeyError, ValueError):
            query = query.filter(Notification.status == status)
    notifications = query.order_by(Notification.created_at.desc()).limit(limit).all()
    return [
        {
            "id": n.id,
            "notification_type": n.notification_type,
            "channel": getattr(n, "channel", "email"),
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
def get_pending_notifications(db: Session = Depends(get_db), clerk_user: Optional[dict] = Depends(get_current_user_optional)):
    user_id = require_user_id(clerk_user)
    notifications = db.query(Notification).filter(
        Notification.user_id.in_(user_owner_ids(user_id)),
        Notification.status == NotificationStatus.PENDING,
    ).order_by(Notification.created_at.desc()).all()
    return [
        {
            "id": n.id,
            "notification_type": n.notification_type,
            "channel": getattr(n, "channel", "email"),
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
def get_notification(notification_id: int, db: Session = Depends(get_db), clerk_user: Optional[dict] = Depends(get_current_user_optional)):
    user_id = require_user_id(clerk_user)
    notification = db.query(Notification).filter(Notification.id == notification_id, Notification.user_id.in_(user_owner_ids(user_id))).first()
    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")
    return {
        "id": notification.id,
        "notification_type": notification.notification_type,
        "channel": getattr(notification, "channel", "email"),
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
def get_notification_stats(db: Session = Depends(get_db), clerk_user: Optional[dict] = Depends(get_current_user_optional)):
    user_id = require_user_id(clerk_user)
    owned = db.query(Notification).filter(Notification.user_id.in_(user_owner_ids(user_id)))
    total = owned.count()
    pending = owned.filter(Notification.status == NotificationStatus.PENDING).count()
    sent = owned.filter(Notification.status == NotificationStatus.SENT).count()
    failed = owned.filter(Notification.status == NotificationStatus.FAILED).count()

    return {
        "total": total,
        "pending": pending,
        "sent": sent,
        "failed": failed,
    }


def _build_email_content(notification: Notification) -> tuple[str, str]:
    """Build HTML and text content from notification with executive styling"""
    subject = notification.subject or "Uniflow Notification"
    payload = notification.payload or ""
    notification_type = (notification.notification_type or "general").upper()
    sent_time_str = datetime.now().strftime("%B %d, %Y at %I:%M %p")
    preheader_snippet = (payload[:140] + "...") if len(payload) > 140 else (payload or subject)

    html = f"""<!DOCTYPE html>
<html lang="en" xmlns="http://www.w3.org/1999/xhtml">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta http-equiv="X-UA-Compatible" content="IE=edge">
  <title>{escape(subject)}</title>
  <style>
    body {{
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
      background-color: #f1f5f9;
      color: #0f172a;
      margin: 0;
      padding: 32px 12px;
      line-height: 1.6;
      -webkit-font-smoothing: antialiased;
    }}
    .email-container {{
      max-width: 600px;
      margin: 0 auto;
      background: #ffffff;
      border-radius: 14px;
      overflow: hidden;
      border: 1px solid #e2e8f0;
      box-shadow: 0 4px 12px rgba(15, 23, 42, 0.05), 0 1px 3px rgba(15, 23, 42, 0.08);
    }}
    .accent-bar {{
      height: 4px;
      background: linear-gradient(90deg, #4f46e5 0%, #6366f1 50%, #818cf8 100%);
      line-height: 4px;
      font-size: 0;
    }}
    .header-bar {{
      background: #090d16;
      padding: 26px 32px;
      border-bottom: 1px solid #1e293b;
    }}
    .brand-title {{
      font-size: 11px;
      font-weight: 700;
      letter-spacing: 0.14em;
      text-transform: uppercase;
      color: #94a3b8;
      margin-bottom: 6px;
    }}
    .header-title {{
      color: #ffffff;
      font-size: 21px;
      font-weight: 700;
      margin: 0;
      letter-spacing: -0.02em;
      line-height: 1.3;
    }}
    .content-body {{
      padding: 32px;
      background: #ffffff;
    }}
    .status-badge {{
      display: inline-block;
      padding: 5px 12px;
      border-radius: 9999px;
      font-size: 11px;
      font-weight: 700;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      background: #eef2ff;
      color: #3730a3;
      border: 1px solid #c7d2fe;
      margin-bottom: 20px;
    }}
    .payload-card {{
      background: #f8fafc;
      border: 1px solid #e2e8f0;
      border-left: 4px solid #6366f1;
      border-radius: 8px;
      padding: 20px;
      font-size: 14px;
      color: #1e293b;
      line-height: 1.65;
    }}
    .footer-bar {{
      background: #f8fafc;
      padding: 22px 32px;
      font-size: 11px;
      color: #64748b;
      text-align: center;
      border-top: 1px solid #e2e8f0;
      line-height: 1.65;
    }}
    @media only screen and (max-width: 620px) {{
      .email-container {{
        width: 100% !important;
        border-radius: 8px !important;
      }}
      .content-body {{
        padding: 20px 16px !important;
      }}
      .header-bar {{
        padding: 20px 18px !important;
      }}
    }}
  </style>
</head>
<body>
  <div style="display:none;font-size:1px;color:#ffffff;line-height:1px;max-height:0px;max-width:0px;opacity:0;overflow:hidden;mso-hide:all;">
    {escape(preheader_snippet)}
    &#847; &zwnj; &nbsp; &#8199; &shy; &#847; &zwnj; &nbsp; &#8199; &shy;
  </div>
  <table role="presentation" width="100%" border="0" cellspacing="0" cellpadding="0" style="background-color:#f1f5f9; padding:0; margin:0;">
    <tr>
      <td align="center">
        <div class="email-container">
          <div class="accent-bar"></div>
          <div class="header-bar">
            <div class="brand-title">Uniflow Academic Suite · Dispatch</div>
            <h1 class="header-title">{escape(subject)}</h1>
          </div>
          <div class="content-body">
            <div class="status-badge">NOTIFICATION · {escape(notification_type)}</div>
            <div class="payload-card">
              {escape(payload).replace(chr(10), '<br>') if payload else '<em style="color:#94a3b8;">No content</em>'}
            </div>
          </div>
          <div class="footer-bar">
            This is an automated notification from Uniflow Academic Suite.<br>
            Category: {escape(notification_type)} · Dispatched at {sent_time_str}
          </div>
        </div>
      </td>
    </tr>
  </table>
</body>
</html>"""

    text = f"""{subject}

{payload if payload else 'No content'}

---
This is an automated notification from Uniflow Academic Suite.
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
def send_notification(notification_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db), clerk_user: Optional[dict] = Depends(get_current_user_optional)):
    """Queue a notification for sending via email"""
    user_id = require_user_id(clerk_user)
    notification = db.query(Notification).filter(Notification.id == notification_id, Notification.user_id.in_(user_owner_ids(user_id))).first()
    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")

    if notification.status == NotificationStatus.SENT:
        return {"message": "Already sent", "notification_id": notification_id, "status": "sent"}

    background_tasks.add_task(_send_notification_email, notification_id)
    return {"message": "Notification queued for sending", "notification_id": notification_id}


@router.post("/send-pending", response_model=dict)
def send_pending_notifications(background_tasks: BackgroundTasks, limit: int = 50, db: Session = Depends(get_db), clerk_user: Optional[dict] = Depends(get_current_user_optional)):
    """Queue all pending notifications for sending"""
    user_id = require_user_id(clerk_user)
    notifications = db.query(Notification).filter(
        Notification.user_id.in_(user_owner_ids(user_id)),
        Notification.status == NotificationStatus.PENDING,
    ).limit(max(1, min(limit, 100))).all()

    if not notifications:
        return {"message": "No pending notifications", "count": 0}

    for n in notifications:
        background_tasks.add_task(_send_notification_email, n.id)

    return {"message": f"Queued {len(notifications)} notifications", "count": len(notifications)}


@router.post("/create", response_model=dict)
def create_notification(
    notification_type: str,
    background_tasks: BackgroundTasks,
    recipient: str = None,
    subject: str = "Uniflow Notification",
    payload: str = None,
    external_id: str = None,
    idempotency_key: str = None,
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional)
):
    """Create a new notification and immediately dispatch it via SendGrid to the recipient."""
    user_id = require_user_id(clerk_user)
    configured_recipient = _get_user_notification_email(db, user_id)
    if not configured_recipient:
        raise HTTPException(status_code=400, detail="No notification email configured. Please set one in Settings.")
    if recipient and recipient.strip().casefold() != configured_recipient.casefold():
        raise HTTPException(status_code=403, detail="Notifications can only be sent to your configured email address.")
    recipient = configured_recipient
    scoped_idempotency_key = f"{user_id}:{idempotency_key}" if idempotency_key else None

    # Check idempotency
    if idempotency_key:
        existing = db.query(Notification).filter(
            Notification.user_id == user_id,
            Notification.idempotency_key == scoped_idempotency_key,
        ).first()
        if existing:
            return {"message": "Already exists", "notification_id": existing.id, "status": existing.status.value}

    notification = Notification(
        user_id=user_id,
        notification_type=notification_type,
        recipient=recipient,
        subject=subject,
        payload=payload,
        external_id=external_id,
        idempotency_key=scoped_idempotency_key,
        status=NotificationStatus.PENDING,
    )
    db.add(notification)
    db.commit()
    db.refresh(notification)

    # Dispatch email immediately in background via SendGrid
    if background_tasks:
        background_tasks.add_task(_send_notification_email, notification.id)

    return {
        "message": "Notification created and queued for email delivery",
        "notification_id": notification.id,
        "recipient": recipient,
        "status": notification.status.value,
    }


@router.post("/create-for-me", response_model=dict)
def create_notification_for_me(
    request: CreateNotificationForMeRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional)
):
    """Create and immediately dispatch a notification for current user using their configured alert email"""
    user_id = clerk_user.get("id") if clerk_user else None
    if not user_id:
        raise HTTPException(status_code=401, detail="User not authenticated")

    recipient = _get_user_notification_email(db, user_id)
    if not recipient:
        raise HTTPException(status_code=400, detail="No notification email configured. Please set one in Settings.")

    return create_notification(
        notification_type=request.notification_type,
        background_tasks=background_tasks,
        recipient=recipient,
        subject=request.subject,
        payload=request.payload,
        external_id=request.external_id,
        idempotency_key=request.idempotency_key,
        db=db,
        clerk_user=clerk_user
    )


@router.post("/test-email", response_model=dict)
def send_test_email(
    recipient: Optional[str] = None,
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional)
):
    """Directly dispatch an immediate test alert via SendGrid to verify delivery to the user's dashboard email"""
    user_id = require_user_id(clerk_user)
    target_email = _get_user_notification_email(db, user_id)
    if recipient and target_email and recipient.strip().casefold() != target_email.casefold():
        raise HTTPException(status_code=403, detail="Test email can only be sent to your configured email address.")
    if not target_email:
        raise HTTPException(status_code=400, detail="No notification email found. Please configure an alert email in Settings.")

    subject = "[Uniflow] Test Alert: Email Delivery Verified"
    html = f"""<!DOCTYPE html>
<html lang="en" xmlns="http://www.w3.org/1999/xhtml">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta http-equiv="X-UA-Compatible" content="IE=edge">
  <title>Alert System Verification Successful</title>
  <style>
    body {{
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
      background-color: #f1f5f9;
      color: #0f172a;
      margin: 0;
      padding: 32px 12px;
      line-height: 1.6;
      -webkit-font-smoothing: antialiased;
    }}
    .email-container {{
      max-width: 580px;
      margin: 0 auto;
      background: #ffffff;
      border-radius: 14px;
      overflow: hidden;
      border: 1px solid #e2e8f0;
      box-shadow: 0 4px 12px rgba(15, 23, 42, 0.05), 0 1px 3px rgba(15, 23, 42, 0.08);
    }}
    .accent-bar {{
      height: 4px;
      background: linear-gradient(90deg, #10b981 0%, #059669 50%, #047857 100%);
      line-height: 4px;
      font-size: 0;
    }}
    .header-bar {{
      background: #090d16;
      padding: 26px 32px;
      border-bottom: 1px solid #1e293b;
    }}
    .brand-title {{
      font-size: 11px;
      font-weight: 700;
      letter-spacing: 0.14em;
      text-transform: uppercase;
      color: #94a3b8;
      margin-bottom: 6px;
    }}
    .header-title {{
      color: #ffffff;
      font-size: 21px;
      font-weight: 700;
      margin: 0;
      letter-spacing: -0.02em;
      line-height: 1.3;
    }}
    .content-body {{
      padding: 32px;
      background: #ffffff;
    }}
    .status-badge {{
      display: inline-block;
      padding: 5px 12px;
      border-radius: 9999px;
      font-size: 11px;
      font-weight: 700;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      background: #ecfdf5;
      color: #047857;
      border: 1px solid #a7f3d0;
      margin-bottom: 20px;
    }}
    .details-card {{
      background: #f0fdf4;
      border: 1px solid #bbf7d0;
      border-left: 4px solid #10b981;
      border-radius: 8px;
      padding: 18px 20px;
      font-size: 13px;
      color: #166534;
      line-height: 1.8;
      margin-top: 20px;
    }}
    .footer-bar {{
      background: #f8fafc;
      padding: 22px 32px;
      font-size: 11px;
      color: #64748b;
      text-align: center;
      border-top: 1px solid #e2e8f0;
      line-height: 1.65;
    }}
    @media only screen and (max-width: 620px) {{
      .email-container {{
        width: 100% !important;
        border-radius: 8px !important;
      }}
      .content-body {{
        padding: 20px 16px !important;
      }}
      .header-bar {{
        padding: 20px 18px !important;
      }}
    }}
  </style>
</head>
<body>
  <div style="display:none;font-size:1px;color:#ffffff;line-height:1px;max-height:0px;max-width:0px;opacity:0;overflow:hidden;mso-hide:all;">
    Alert System Verification: Email delivery verified for {escape(target_email)}.
    &#847; &zwnj; &nbsp; &#8199; &shy; &#847; &zwnj; &nbsp; &#8199; &shy;
  </div>
  <table role="presentation" width="100%" border="0" cellspacing="0" cellpadding="0" style="background-color:#f1f5f9; padding:0; margin:0;">
    <tr>
      <td align="center">
        <div class="email-container">
          <div class="accent-bar"></div>
          <div class="header-bar">
            <div class="brand-title">Uniflow Academic Alerts · Verified</div>
            <h1 class="header-title">Alert System Verification Successful</h1>
          </div>
          <div class="content-body">
            <div class="status-badge">DELIVERY CHANNEL · SENDGRID VERIFIED</div>
            <p style="color:#334155; font-size:14px; line-height:1.6; margin:0 0 16px 0;">
              This email confirms that your alert settings are active and that Uniflow is delivering notifications to: <strong>{escape(target_email)}</strong>.
            </p>
            <div class="details-card">
              ✓ <strong>Primary Delivery Channel:</strong> SendGrid Transactional API<br>
              ✓ <strong>Configured Recipient:</strong> {escape(target_email)}<br>
              ✓ <strong>Morning Academic Briefing:</strong> Active (Daily morning dispatch)<br>
              ✓ <strong>Class Timetable Reminders:</strong> Active (20m &amp; 5m advance notices)<br>
              ✓ <strong>Google Classroom Deadlines:</strong> Active (Synchronized coursework tracking)
            </div>
          </div>
          <div class="footer-bar">
            Automated verification dispatched by Uniflow Academic Suite.<br>
            Air University Student Intelligence &amp; Schedule Synchronization.
          </div>
        </div>
      </td>
    </tr>
  </table>
</body>
</html>"""
    success = send_email(
        to_email=target_email,
        subject=subject,
        html_content=html,
        categories=["test-notification", "verification"]
    )
    if not success:
        raise HTTPException(status_code=500, detail="Failed to deliver test email via SendGrid.")

    return {
        "status": "sent",
        "recipient": target_email,
        "message": f"Test alert email successfully delivered to {target_email} via SendGrid!"
    }


@router.post("/daily-digest", response_model=dict)
def trigger_daily_digest(
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional)
):
    """Trigger the Daily Morning Schedule & Attendance Digest via SendGrid."""
    from app.services.alert_service import AlertService
    user_id = require_user_id(clerk_user)
    service = AlertService(db)
    digest = service.generate_daily_morning_digest(user_id=user_id, send_immediately=True)
    if not digest:
        return {
            "status": "already_sent_or_skipped",
            "message": "Daily morning digest was already delivered today (idempotency enforced)."
        }
    return {
        "status": "sent",
        "digest": digest,
        "message": f"Daily morning briefing successfully dispatched to {digest.get('recipient')} via SendGrid!"
    }


@router.post("/check-alerts", response_model=dict)
def check_and_send_alerts(
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional)
):
    """Trigger on-demand check for morning digest, low-attendance class-day warnings, 20m/5m class reminders, and GCR deadlines."""
    from app.services.alert_service import AlertService
    user_id = require_user_id(clerk_user)
    service = AlertService(db)
    digest = service.generate_daily_morning_digest(user_id=user_id, send_immediately=True)
    att_alerts = service.generate_daily_attendance_warnings(user_id=user_id, send_immediately=True)
    tt_reminders = service.generate_upcoming_class_reminders(user_id=user_id, send_immediately=True)
    gcr_alerts = service.generate_upcoming_assignment_reminders(user_id=user_id, send_immediately=True)
    return {
        "status": "success",
        "daily_digest": digest,
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
    user_id = require_user_id(clerk_user)
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
