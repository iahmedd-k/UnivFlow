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
    applicant_name = escape(user.get("name") or "Unknown")
    applicant_email = escape(email)
    applicant_id = escape(user_id)

    html_content = f"""<!DOCTYPE html>
<html lang="en" xmlns="http://www.w3.org/1999/xhtml">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta http-equiv="X-UA-Compatible" content="IE=edge">
  <title>Private Access Approval Request</title>
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
      background: linear-gradient(90deg, #6366f1 0%, #8b5cf6 50%, #d946ef 100%);
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
    .details-table {{
      width: 100%;
      border-collapse: separate;
      border-spacing: 0;
      margin: 20px 0;
      font-size: 13px;
      border: 1px solid #e2e8f0;
      border-radius: 10px;
      overflow: hidden;
    }}
    .details-table tr:last-child td {{
      border-bottom: none;
    }}
    .details-table td {{
      padding: 12px 16px;
      border-bottom: 1px solid #f1f5f9;
      color: #0f172a;
      vertical-align: middle;
    }}
    .details-table td.label-col {{
      width: 32%;
      font-weight: 600;
      color: #475569;
      background: #f8fafc;
      border-right: 1px solid #f1f5f9;
    }}
    .otp-card {{
      background: #090d16;
      border-radius: 10px;
      padding: 22px 16px;
      text-align: center;
      margin: 24px 0;
    }}
    .otp-label {{
      font-size: 11px;
      font-weight: 700;
      letter-spacing: 0.12em;
      text-transform: uppercase;
      color: #94a3b8;
      margin-bottom: 8px;
    }}
    .otp-code {{
      font-family: 'Courier New', Courier, monospace;
      font-size: 34px;
      font-weight: 800;
      letter-spacing: 0.22em;
      color: #ffffff;
      line-height: 1.1;
    }}
    .security-notice {{
      background: #fffbeb;
      border: 1px solid #fde68a;
      border-left: 4px solid #f59e0b;
      border-radius: 8px;
      padding: 14px 18px;
      font-size: 13px;
      color: #92400e;
      line-height: 1.6;
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
    Private Access Request: {applicant_name} ({applicant_email}) has requested authorization. Code: {otp}.
    &#847; &zwnj; &nbsp; &#8199; &shy; &#847; &zwnj; &nbsp; &#8199; &shy;
  </div>
  <table role="presentation" width="100%" border="0" cellspacing="0" cellpadding="0" style="background-color:#f1f5f9; padding:0; margin:0;">
    <tr>
      <td align="center">
        <div class="email-container">
          <div class="accent-bar"></div>
          <div class="header-bar">
            <div class="brand-title">Uniflow Access Gate · Security Verification</div>
            <h1 class="header-title">Private Access Approval Request</h1>
          </div>
          <div class="content-body">
            <div class="status-badge">SECURITY NOTICE · ACTION REQUIRED</div>
            <p style="color:#334155; font-size:14px; line-height:1.6; margin:0 0 16px 0;">
              A signed-in account has requested authorization to access the Uniflow private academic platform.
            </p>

            <table class="details-table" role="presentation">
              <tr>
                <td class="label-col">Applicant Name</td>
                <td><strong>{applicant_name}</strong></td>
              </tr>
              <tr>
                <td class="label-col">Applicant Email</td>
                <td>{applicant_email}</td>
              </tr>
              <tr>
                <td class="label-col">Account ID</td>
                <td><code style="font-family:monospace; background:#f1f5f9; padding:2px 6px; border-radius:4px; font-size:12px;">{applicant_id}</code></td>
              </tr>
              <tr>
                <td class="label-col">Validity Window</td>
                <td>Expires in {ttl} minutes</td>
              </tr>
            </table>

            <div class="otp-card">
              <div class="otp-label">One-Time Approval Code</div>
              <div class="otp-code">{otp}</div>
            </div>

            <div class="security-notice">
              <strong>Security Policy:</strong> Only give this code directly to the person whose identity and account details are shown above. Do not forward this message.
            </div>
          </div>
          <div class="footer-bar">
            Automated security authorization dispatch by Uniflow Access Gate.<br>
            Confidential administrative communication.
          </div>
        </div>
      </td>
    </tr>
  </table>
</body>
</html>"""
    try:
        delivered = send_email(
            to_email=settings.access_admin_email,
            subject=subject,
            html_content=html_content,
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
