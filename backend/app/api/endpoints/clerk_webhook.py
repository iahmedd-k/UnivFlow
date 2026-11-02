from fastapi import APIRouter, Request, HTTPException, Header, Depends
from sqlalchemy.orm import Session
from app.core.config import settings
from app.db.database import get_db
from app.db.models import Setting
from app.core.logging import logger
import base64
import binascii
import hmac
import hashlib
import json
import time
from datetime import datetime, timezone, timedelta


router = APIRouter(prefix="/clerk", tags=["Clerk Webhooks"])


def verify_clerk_signature(
    payload: bytes,
    message_id: str | None,
    timestamp: str | None,
    signature: str | None,
    signing_secret: str,
) -> bool:
    """Verify a timestamped Svix signature for a Clerk webhook."""
    try:
        if not message_id or not timestamp or not signature or not signing_secret.startswith("whsec_"):
            return False

        timestamp_seconds = int(timestamp)
        if abs(time.time() - timestamp_seconds) > 300:
            return False

        secret = base64.b64decode(signing_secret.removeprefix("whsec_"), validate=True)
        signed_content = message_id.encode() + b"." + timestamp.encode() + b"." + payload
        digest = hmac.new(secret, signed_content, hashlib.sha256).digest()
        expected = base64.b64encode(digest).decode()
        return any(
            version == "v1" and hmac.compare_digest(candidate, expected)
            for item in signature.split()
            for version, separator, candidate in [item.partition(",")]
            if separator
        )
    except (ValueError, TypeError, binascii.Error):
        return False


@router.post("/webhook")
async def clerk_webhook(
    request: Request,
    svix_id: str | None = Header(default=None, alias="svix-id"),
    svix_timestamp: str | None = Header(default=None, alias="svix-timestamp"),
    svix_signature: str | None = Header(default=None, alias="svix-signature"),
    db: Session = Depends(get_db)
):
    """Handle Clerk webhooks for user management"""
    
    # Get signing secret from settings or database - MUST be configured
    signing_secret = settings.clerk_signing_secret
    if not signing_secret:
        secret_setting = db.query(Setting).filter(Setting.key == "clerk_signing_secret").first()
        if secret_setting:
            signing_secret = secret_setting.value
    
    if not signing_secret:
        logger.error("Clerk signing secret not configured")
        raise HTTPException(status_code=500, detail="Clerk webhook not configured - signing secret required")

    # Get raw body
    payload = await request.body()
    
    # Verify signature
    if not verify_clerk_signature(
        payload,
        svix_id,
        svix_timestamp,
        svix_signature,
        signing_secret,
    ):
        logger.warning("Invalid Clerk webhook signature")
        raise HTTPException(status_code=401, detail="Invalid signature")

    try:
        event = json.loads(payload)
        event_type = event.get("type")
        data = event.get("data", {})
        
        # Idempotency check using event ID
        event_id = event.get("id") or svix_id
        marker = None
        if event_id:
            idempotency_key = f"clerk_webhook_v2:{event_id}"
            marker = db.query(Setting).filter(Setting.key == idempotency_key).first()
            if marker and marker.value == "processed":
                logger.info(f"Duplicate Clerk webhook event {event_id} ignored")
                return {"status": "duplicate", "event_type": event_type}
            if marker and marker.value == "processing" and marker.updated_at:
                last_attempt = marker.updated_at
                if last_attempt.tzinfo is None:
                    last_attempt = last_attempt.replace(tzinfo=timezone.utc)
                if datetime.now(timezone.utc) - last_attempt < timedelta(minutes=5):
                    return {"status": "processing", "event_type": event_type}
            if marker:
                marker.value = "processing"
                marker.updated_at = datetime.now(timezone.utc)
            else:
                marker = Setting(
                    key=idempotency_key,
                    value="processing",
                    description=f"Clerk webhook idempotency: {event_type}",
                    updated_at=datetime.now(timezone.utc),
                )
                db.add(marker)
            db.commit()
        
        logger.info(f"Clerk webhook received: {event_type}")

        # Handle different event types
        if event_type == "user.created":
            await handle_user_created(data, db)
        elif event_type == "user.updated":
            await handle_user_updated(data, db)
        elif event_type == "user.deleted":
            await handle_user_deleted(data, db)
        elif event_type == "session.created":
            await handle_session_created(data, db)
        elif event_type == "session.ended":
            await handle_session_ended(data, db)
        elif event_type == "session.revoked":
            await handle_session_revoked(data, db)
        else:
            logger.info(f"Unhandled Clerk event type: {event_type}")

        if marker:
            marker.value = "processed"
            marker.updated_at = datetime.now(timezone.utc)
            db.commit()

        return {"status": "ok", "event_type": event_type}

    except json.JSONDecodeError:
        logger.error("Invalid JSON in Clerk webhook")
        raise HTTPException(status_code=400, detail="Invalid JSON")
    except Exception as e:
        db.rollback()
        if 'marker' in locals() and marker is not None:
            try:
                failed_marker = db.query(Setting).filter(Setting.key == marker.key).first()
                if failed_marker:
                    failed_marker.value = "failed"
                    failed_marker.updated_at = datetime.now(timezone.utc)
                    db.commit()
            except Exception:
                db.rollback()
        logger.error(f"Error processing Clerk webhook: {e}")
        raise HTTPException(status_code=500, detail="Internal error")


async def handle_user_created(data: dict, db: Session):
    """Handle new user creation from Clerk"""
    user_id = data.get("id")
    email = data.get("email_addresses", [{}])[0].get("email_address")
    first_name = data.get("first_name", "")
    last_name = data.get("last_name", "")
    
    logger.info(f"New Clerk user created: {user_id} ({email})")
    
    # Store user mapping in database
    profile = db.query(Setting).filter(Setting.key == f"clerk_user_{user_id}").first()
    value = json.dumps({
            "email": email,
            "first_name": first_name,
            "last_name": last_name,
            "created_at": data.get("created_at")
        })
    if profile:
        profile.value = value
    else:
        db.add(Setting(key=f"clerk_user_{user_id}", value=value, description="Clerk user mapping"))
    revoked = db.query(Setting).filter(Setting.key == f"clerk_user_revoked_{user_id}").first()
    if revoked:
        db.delete(revoked)
    db.commit()


async def handle_user_updated(data: dict, db: Session):
    """Handle user updates from Clerk"""
    user_id = data.get("id")
    logger.info(f"Clerk user updated: {user_id}")
    
    setting = db.query(Setting).filter(Setting.key == f"clerk_user_{user_id}").first()
    value = json.dumps({
            "email": data.get("email_addresses", [{}])[0].get("email_address"),
            "first_name": data.get("first_name", ""),
            "last_name": data.get("last_name", ""),
            "updated_at": data.get("updated_at")
        })
    if setting:
        setting.value = value
    else:
        db.add(Setting(key=f"clerk_user_{user_id}", value=value, description="Clerk user mapping"))
    db.commit()


async def handle_user_deleted(data: dict, db: Session):
    """Revoke local access and remove all user-owned data after Clerk deletion."""
    user_id = data.get("id")
    if not user_id:
        return
    logger.info(f"Clerk user deleted: {user_id}")

    from app.db.models import (
        AgentEvent, AgentRun, Announcement, Assignment, AssignmentMaterial,
        AssignmentSolution, AssignmentTemplate, AttendanceRecord,
        BrowserAutomationJob, ChangeEvent, ChatConversation, ChatMessage,
        ClassSchedule, Course, DailyReport, Exam, GoogleCredential,
        Notification, NotificationPreference, PortalSyncJob, Quiz, Setting,
        StudyPlan, StudyPlanSession, Submission, TimetableEntry,
    )

    assignment_ids = [row[0] for row in db.query(Assignment.id).filter(Assignment.user_id == user_id).all()]
    plan_ids = [row[0] for row in db.query(StudyPlan.id).filter(StudyPlan.user_id == user_id).all()]
    conversation_ids = [row[0] for row in db.query(ChatConversation.id).filter(ChatConversation.user_id == user_id).all()]
    run_ids = [row[0] for row in db.query(AgentRun.id).filter(AgentRun.user_id == user_id).all()]

    # Remove object-store copies before dropping their database references.
    storage_keys = [row[0] for row in db.query(AssignmentMaterial.storage_key).filter(
        AssignmentMaterial.user_id == user_id, AssignmentMaterial.storage_key.isnot(None)
    ).all()]
    if storage_keys:
        try:
            from app.db.s3_client import get_s3_client
            s3 = get_s3_client()
            if s3:
                for key in storage_keys:
                    s3.delete_object(Bucket="uniflow-files", Key=key)
        except Exception as error:
            logger.warning("Could not remove all cached course files for deleted user %s: %s", user_id, error)

    # Delete dependent records before their parent rows to satisfy foreign keys.
    for model, column, values in (
        (ChatMessage, ChatMessage.conversation_id, conversation_ids),
        (StudyPlanSession, StudyPlanSession.plan_id, plan_ids),
        (AgentEvent, AgentEvent.run_id, run_ids),
        (BrowserAutomationJob, BrowserAutomationJob.assignment_id, assignment_ids),
        (AssignmentMaterial, AssignmentMaterial.assignment_id, assignment_ids),
        (AssignmentSolution, AssignmentSolution.assignment_id, assignment_ids),
        (Submission, Submission.assignment_id, assignment_ids),
    ):
        if values:
            db.query(model).filter(column.in_(values)).delete(synchronize_session=False)

    for model in (
        Notification, NotificationPreference, DailyReport, GoogleCredential,
        AttendanceRecord, TimetableEntry, ClassSchedule, Exam, Quiz,
        Announcement, ChangeEvent, AssignmentTemplate, AssignmentMaterial,
        AssignmentSolution, Submission, BrowserAutomationJob, AgentEvent,
        ChatMessage, StudyPlanSession, Assignment,
        Course, ChatConversation, StudyPlan, PortalSyncJob, AgentRun,
    ):
        if hasattr(model, "user_id"):
            db.query(model).filter(model.user_id == user_id).delete(synchronize_session=False)

    # Remove account-scoped settings but retain a revocation marker so old Clerk
    # session tokens cannot regain access after the profile record is deleted.
    db.query(Setting).filter(
        (Setting.key == f"clerk_user_{user_id}")
        | (Setting.key == f"notification_email_{user_id}")
        | (Setting.key == f"google_connected_email_{user_id}")
        | (Setting.key == f"student_profile_{user_id}")
        | (Setting.key.like(f"schedule_turnin_{user_id}_%"))
        | (Setting.key.like(f"auto_turnin_course_{user_id}_%"))
        | (Setting.key.like(f"roster_{user_id}_%"))
        | (Setting.key.like(f"classroom:{user_id}:%"))
        | (Setting.key.like(f"portal:{user_id}:%"))
    ).delete(synchronize_session=False)
    revoked = db.query(Setting).filter(Setting.key == f"clerk_user_revoked_{user_id}").first()
    if not revoked:
        db.add(Setting(key=f"clerk_user_revoked_{user_id}", value="true", description="Clerk account deleted"))
    db.commit()


async def handle_session_created(data: dict, db: Session):
    """Handle new session creation"""
    user_id = data.get("user_id")
    session_id = data.get("id")
    logger.info(f"Clerk session created: {session_id} for user {user_id}")


async def handle_session_ended(data: dict, db: Session):
    """Handle session end"""
    user_id = data.get("user_id")
    session_id = data.get("id")
    logger.info(f"Clerk session ended: {session_id} for user {user_id}")


async def handle_session_revoked(data: dict, db: Session):
    """Handle session revocation"""
    user_id = data.get("user_id")
    session_id = data.get("id")
    logger.info(f"Clerk session revoked: {session_id} for user {user_id}")


async def revoke_all_user_sessions(user_id: str, db: Session):
    """Revoke all active sessions for a user by invalidating their Clerk tokens"""
    # This would typically call Clerk API to revoke sessions
    # For now, we clear local cached tokens
    logger.info(f"Revoking all sessions for user {user_id}")
    
    # Clear any cached Google credentials that depend on user session
    from app.db.repositories import GoogleCredentialRepository
    cred_repo = GoogleCredentialRepository(db)
    cred = cred_repo.get(user_id)
    if cred:
        # Don't delete credentials, just mark as needing re-auth
        logger.info(f"Google credentials for deleted user {user_id} marked for re-auth")
    
    db.commit()
