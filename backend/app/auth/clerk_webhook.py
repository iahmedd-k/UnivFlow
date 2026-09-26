from fastapi import APIRouter, Request, HTTPException, Header, Depends
from sqlalchemy.orm import Session
from app.core.config import settings
from app.db.database import get_db
from app.db.models import Setting
from app.core.logging import logger
import hmac
import hashlib
import json


router = APIRouter(prefix="/clerk", tags=["Clerk Webhooks"])


def verify_clerk_signature(payload: bytes, signature: str, signing_secret: str) -> bool:
    """Verify Clerk webhook signature"""
    try:
        expected = hmac.new(
            signing_secret.encode(),
            payload,
            hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, signature)
    except Exception:
        return False


@router.post("/webhook")
async def clerk_webhook(
    request: Request,
    svix_id: str = Header(None, alias="svix-id"),
    svix_timestamp: str = Header(None, alias="svix-timestamp"),
    svix_signature: str = Header(None, alias="svix-signature"),
    db: Session = Depends(get_db)
):
    """Handle Clerk webhooks for user management"""
    
    # Get signing secret from settings or database
    signing_secret = settings.clerk_signing_secret
    if not signing_secret:
        secret_setting = db.query(Setting).filter(Setting.key == "clerk_signing_secret").first()
        if secret_setting:
            signing_secret = secret_setting.value
    
    if not signing_secret:
        logger.warning("Clerk signing secret not configured")
        # Allow in development
        if settings.environment != "production":
            signing_secret = "dev-secret"
        else:
            raise HTTPException(status_code=500, detail="Clerk webhook not configured")

    # Get raw body
    payload = await request.body()
    
    # Verify signature
    if not verify_clerk_signature(payload, svix_signature, signing_secret):
        logger.warning("Invalid Clerk webhook signature")
        raise HTTPException(status_code=401, detail="Invalid signature")

    try:
        event = json.loads(payload)
        event_type = event.get("type")
        data = event.get("data", {})
        
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
        else:
            logger.info(f"Unhandled Clerk event type: {event_type}")

        return {"status": "ok", "event_type": event_type}

    except json.JSONDecodeError:
        logger.error("Invalid JSON in Clerk webhook")
        raise HTTPException(status_code=400, detail="Invalid JSON")
    except Exception as e:
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
    setting = Setting(
        key=f"clerk_user_{user_id}",
        value=json.dumps({
            "email": email,
            "first_name": first_name,
            "last_name": last_name,
            "created_at": data.get("created_at")
        }),
        description="Clerk user mapping"
    )
    db.add(setting)
    db.commit()


async def handle_user_updated(data: dict, db: Session):
    """Handle user updates from Clerk"""
    user_id = data.get("id")
    logger.info(f"Clerk user updated: {user_id}")
    
    setting = db.query(Setting).filter(Setting.key == f"clerk_user_{user_id}").first()
    if setting:
        setting.value = json.dumps({
            "email": data.get("email_addresses", [{}])[0].get("email_address"),
            "first_name": data.get("first_name", ""),
            "last_name": data.get("last_name", ""),
            "updated_at": data.get("updated_at")
        })
        db.commit()


async def handle_user_deleted(data: dict, db: Session):
    """Handle user deletion from Clerk"""
    user_id = data.get("id")
    logger.info(f"Clerk user deleted: {user_id}")
    
    setting = db.query(Setting).filter(Setting.key == f"clerk_user_{user_id}").first()
    if setting:
        db.delete(setting)
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