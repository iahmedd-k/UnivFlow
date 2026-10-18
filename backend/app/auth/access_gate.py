"""Private beta access grants and admin-relayed, account-bound OTPs."""

import hashlib
import hmac
import json
import secrets
import time
from datetime import datetime, timezone
from html import escape

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.auth.clerk_auth import require_current_user
from app.core.config import settings
from app.db.database import get_db
from app.db.models import Setting


def _key(prefix: str, user_id: str) -> str:
    # Clerk IDs are opaque; keep keys within the settings column's length.
    return f"private_access_{prefix}_{hashlib.sha256(user_id.encode()).hexdigest()}"


def _read(db: Session, key: str) -> dict:
    row = db.query(Setting).filter(Setting.key == key).first()
    if not row or not row.value:
        return {}
    try:
        value = json.loads(row.value)
        return value if isinstance(value, dict) else {}
    except (TypeError, json.JSONDecodeError):
        return {}


def _write(db: Session, key: str, value: dict, description: str) -> None:
    row = db.query(Setting).filter(Setting.key == key).with_for_update().first()
    if row:
        row.value = json.dumps(value, separators=(",", ":"))
    else:
        db.add(Setting(key=key, value=json.dumps(value, separators=(",", ":")), description=description))


def _user_id(user: dict) -> str:
    return str(user.get("id") or "")


def _otp_digest(user_id: str, otp: str) -> str:
    return hmac.new(settings.secret_key.encode(), f"{user_id}:{otp}".encode(), hashlib.sha256).hexdigest()


def get_access_status(user: dict, db: Session) -> dict:
    if not settings.is_production:
        return {"granted": True, "email": user.get("email", ""), "expires_at": None}
    grant = _read(db, _key("grant", _user_id(user)))
    return {
        "granted": bool(grant.get("granted_at")),
        "email": user.get("email", ""),
        "expires_at": None,
    }


def require_access_grant(
    user: dict = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Protect every feature router after login; development remains convenient."""
    if settings.is_production and not get_access_status(user, db)["granted"]:
        raise HTTPException(status_code=403, detail="Private beta access has not been approved for this account.")
    return user


def request_access_otp(request: Request, user: dict, db: Session) -> dict:
    user_id = _user_id(user)
    if not user_id:
        raise HTTPException(status_code=401, detail="Sign in before requesting access.")
    if not settings.is_production:
        return {"sent": True, "message": "Development accounts already have access."}
    if get_access_status(user, db)["granted"]:
        return {"sent": False, "message": "This account already has access."}
    if not settings.access_admin_email or "@" not in settings.access_admin_email:
        raise HTTPException(status_code=503, detail="Private access approval email is not configured.")
    email = str(user.get("email") or "").strip()
    if not email:
        raise HTTPException(status_code=400, detail="Your account has no email address. Add one to your sign-in account first.")

    now = int(time.time())
    # Persisted throttles keep the admin inbox protected even when Redis is not configured.
    user_key = _key("request_limit", user_id)
    global_key = "private_access_global_limit"
    previous_user = _read(db, user_key)
    if now - int(previous_user.get("at", 0)) < 600:
        raise HTTPException(status_code=429, detail="An access request was sent recently. Please try again later.")
    global_state = _read(db, global_key)
    recent_events = [int(event) for event in global_state.get("events", []) if now - int(event) < 86400]
    if (
        now - int(global_state.get("at", 0)) < 60
        or sum(now - event < 3600 for event in recent_events) >= 5
        or len(recent_events) >= 20
    ):
        raise HTTPException(status_code=429, detail="The private access request limit has been reached. Try again later.")
    _write(db, user_key, {"at": now}, "Private access OTP rate limit")
    _write(db, global_key, {"at": now, "events": recent_events + [now]}, "Private access OTP rate limit")

    otp = f"{secrets.randbelow(100_000_000):08d}"
    ttl = max(2, min(int(settings.access_otp_ttl_minutes or 10), 30))
    _write(
        db,
        _key("otp", user_id),
        {"digest": _otp_digest(user_id, otp), "expires_at": now + ttl * 60, "attempts": 0, "email": email},
        "Private beta OTP state",
    )
    db.commit()

    from app.services.email import send_email

    subject = "Uniflow private access approval request"
    text_body = (
        f"A signed-in account requested private access.\n\n"
        f"Name: {user.get('name') or 'Unknown'}\nEmail: {email}\nAccount ID: {user_id}\n\n"
        f"One-time approval code: {otp}\nExpires in {ttl} minutes.\n"
        "Only give this code to the person whose account details are shown above."
    )
    html_body = "<br>".join(escape(line) for line in text_body.splitlines())
    try:
        delivered = send_email(
            to_email=settings.access_admin_email,
            subject=subject,
            html_content=f"<p>{html_body}</p>",
            text_content=text_body,
            from_name="Uniflow access gate",
        )
    except Exception:
        delivered = False
    if not delivered:
        # Keep throttles even on delivery failure so retries cannot be used to
        # repeatedly hammer the administrator's configured mail provider.
        db.query(Setting).filter(Setting.key == _key("otp", user_id)).delete(synchronize_session=False)
        db.commit()
        raise HTTPException(status_code=503, detail="Could not deliver the request to the access administrator. Try again later.")
    return {"sent": True, "message": "A one-time approval code was sent to the administrator. Ask them to share it with you."}


def redeem_access_otp(user: dict, otp: str, db: Session) -> dict:
    user_id = _user_id(user)
    if not settings.is_production:
        return {"granted": True, "message": "Development accounts already have access."}
    if get_access_status(user, db)["granted"]:
        return {"granted": True, "message": "This account already has access."}
    key = _key("otp", user_id)
    state = _read(db, key)
    now = int(time.time())
    if not state or int(state.get("expires_at", 0)) <= now:
        raise HTTPException(status_code=400, detail="The code is missing or expired. Request a new one.")
    if int(state.get("attempts", 0)) >= 5:
        raise HTTPException(status_code=429, detail="Too many incorrect codes. Request a new code later.")
    supplied = _otp_digest(user_id, otp.strip())
    if not hmac.compare_digest(supplied, str(state.get("digest", ""))):
        state["attempts"] = int(state.get("attempts", 0)) + 1
        _write(db, key, state, "Private beta OTP state")
        db.commit()
        raise HTTPException(status_code=400, detail="That code is incorrect.")
    _write(db, _key("grant", user_id), {"granted_at": datetime.now(timezone.utc).isoformat(), "email": user.get("email", "")}, "Private beta access grant")
    db.query(Setting).filter(Setting.key == key).delete(synchronize_session=False)
    db.commit()
    return {"granted": True, "message": "Access approved for this account."}
