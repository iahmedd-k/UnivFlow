import os
import json
import secrets
import httpx
import time
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import settings
from app.db.database import get_db
from app.db.repositories import GoogleCredentialRepository
from app.db.models import Setting
from app.core.logging import logger
from app.auth.clerk_auth import get_current_user_optional, require_current_user
from app.auth.access_gate import get_access_status, redeem_access_otp, request_access_otp
from app.auth.access_gate import require_access_grant
from app.auth.ownership import require_user_id
from app.core.redis import check_rate_limit as redis_check_rate_limit
from app.core.security import decrypt_token_if_encrypted, get_google_credential_tokens, encrypt_token_if_needed
from pydantic import BaseModel, EmailStr, Field

# Only allow HTTP transport in local development/test environments
if settings.environment == "development" or settings.debug:
    os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"
os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"

router = APIRouter(prefix="/auth", tags=["Authentication"])


class UserSyncRequest(BaseModel):
    userId: str
    email: Optional[str] = ""
    firstName: Optional[str] = ""
    lastName: Optional[str] = ""
    imageUrl: Optional[str] = ""


class NotificationEmailRequest(BaseModel):
    email: EmailStr


class NotificationEmailResponse(BaseModel):
    email: Optional[str] = None
    message: str


class AccessOtpRequest(BaseModel):
    code: str = Field(min_length=8, max_length=8, pattern=r"^[0-9]{8}$")


@router.get("/access/status")
def private_access_status(
    user: dict = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    return get_access_status(user, db)


@router.post("/access/request")
def request_private_access(
    request: Request,
    user: dict = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    return request_access_otp(request, user, db)


@router.post("/access/redeem")
def redeem_private_access(
    payload: AccessOtpRequest,
    user: dict = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    return redeem_access_otp(user, payload.code, db)


# Per-user cache for connected Google emails: {user_id: email}
_cached_google_emails: Dict[str, str] = {}


def _google_owner_id(clerk_user: Optional[dict], *, required: bool = False) -> Optional[str]:
    user_id = str((clerk_user or {}).get("id") or "")
    if user_id:
        return user_id
    if required:
        raise HTTPException(status_code=401, detail="Sign in before connecting Google Classroom.")
    return None


def _check_rate_limit(key: str, limit: int = 20, window_sec: int = 60) -> None:
    allowed = redis_check_rate_limit(key, limit, window_sec)
    if not allowed:
        raise HTTPException(status_code=429, detail="Too many requests. Please try again in a moment.")


def _upsert_setting(db: Session, key: str, value: str, description: str = "") -> Setting:
    """Safely insert or update a Setting row without risking UniqueViolation or merge issues."""
    try:
        setting = db.query(Setting).filter(Setting.key == key).first()
        if setting:
            setting.value = value
            if description:
                setting.description = description
        else:
            setting = Setting(key=key, value=value, description=description)
            db.add(setting)
        db.commit()
        return setting
    except Exception:
        db.rollback()
        raise


def _safe_oauth_redirect_to(redirect_to: Optional[str]) -> Optional[str]:
    """Accept only same-site dashboard paths for the post-OAuth return destination."""
    if not redirect_to or not redirect_to.startswith("/") or redirect_to.startswith("//") or "\\" in redirect_to:
        return None
    parsed = urlsplit(redirect_to)
    if parsed.scheme or parsed.netloc:
        return None
    if parsed.path == "/dashboard" or parsed.path.startswith("/dashboard/"):
        return urlunsplit(("", "", parsed.path, parsed.query, parsed.fragment))
    return None


def _get_frontend_origin(request: Optional[Request] = None, state_origin: Optional[str] = None) -> str:
    """Resolve only an explicitly configured frontend origin for OAuth redirects."""
    canonical_origin = "https://univ-flow-bt12.vercel.app"
    configured_origins = {canonical_origin}
    if settings.frontend_url:
        frontend = urlsplit(settings.frontend_url)
        browser_viewer = urlsplit(settings.browser_viewer_base_url)
        same_as_backend_host = bool(frontend.netloc and browser_viewer.netloc and frontend.netloc == browser_viewer.netloc)
        if frontend.scheme in {"http", "https"} and frontend.netloc and not same_as_backend_host:
            configured_origins.add(f"{frontend.scheme}://{frontend.netloc}".rstrip("/"))
    configured_origins.update(
        origin.strip().rstrip("/")
        for origin in (settings.cors_origins or "").split(",")
        if origin.strip().startswith(("https://", "http://"))
    )

    if state_origin and state_origin.rstrip("/") in configured_origins:
        return state_origin.rstrip("/")
    if request:
        origin = request.headers.get("origin")
        if origin and origin.rstrip("/") in configured_origins:
            return origin.rstrip("/")
        referer = request.headers.get("referer")
        if referer:
            parsed = urlsplit(referer)
            candidate = f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
            if candidate in configured_origins:
                return candidate
    return next((origin for origin in configured_origins if origin != canonical_origin), canonical_origin)


def _oauth_frontend_redirect(
    redirect_to: Optional[str] = None,
    frontend_origin: Optional[str] = None,
    **query_params: str
) -> str:
    """Build a frontend callback URL without allowing an external redirect."""
    origin = _get_frontend_origin(state_origin=frontend_origin)
    frontend = urlsplit(origin)
    destination = _safe_oauth_redirect_to(redirect_to)
    destination_parts = urlsplit(destination) if destination else None
    path = destination_parts.path if destination_parts else ""
    target_path = f"{frontend.path.rstrip('/')}{path}"
    query = parse_qsl(destination_parts.query, keep_blank_values=True) if destination_parts else []
    query.extend((key, value) for key, value in query_params.items() if value is not None)
    return urlunsplit((frontend.scheme, frontend.netloc, target_path, urlencode(query), ""))


@router.get("/status", dependencies=[Depends(require_current_user), Depends(require_access_grant)])
def get_auth_status(
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional)
):
    """Check overall auth status (Clerk user & Google Classroom connection) - Fast Per-User Cached"""
    user_id = _google_owner_id(clerk_user)
    repo = GoogleCredentialRepository(db)
    cred = repo.get(user_id) if user_id else None
    google_connected = cred is not None and bool(cred.access_token)
    google_email = _cached_google_emails.get(user_id) if user_id else None

    if google_connected and not google_email:
        setting_key = f"google_connected_email_{user_id}"
        email_setting = db.query(Setting).filter(Setting.key == setting_key).first()

        if email_setting and email_setting.value:
            google_email = email_setting.value
            _cached_google_emails[user_id] = google_email
        else:
            # 2. Only fetch via network if never saved
            try:
                access_token, refresh_token = get_google_credential_tokens(db, cred)
                creds = Credentials(
                    token=access_token,
                    refresh_token=refresh_token,
                    token_uri=cred.token_uri or "https://oauth2.googleapis.com/token",
                    client_id=cred.client_id or settings.google_client_id,
                    client_secret=settings.google_client_secret,
                    scopes=json.loads(cred.scopes) if cred.scopes else settings.google_scopes_list,
                )
                userinfo = get_user_info(creds)
                google_email = userinfo.get("email")
                if google_email:
                    _cached_google_emails[user_id] = google_email
                    _upsert_setting(db, key=setting_key, value=google_email, description="Google OAuth Account Email")
            except Exception as e:
                logger.warning(f"Could not fetch Google userinfo: {e}")
                google_email = "connected"
    elif not google_connected:
        _cached_google_emails.pop(user_id, None)

    return {
        "authenticated": clerk_user is not None,
        "clerk_user": clerk_user,
        "google_connected": google_connected,
        "google_email": google_email,
    }


@router.post("/sync-user", dependencies=[Depends(require_current_user)])
def sync_user(
    request: Request,
    payload: UserSyncRequest,
    db: Session = Depends(get_db),
    current_user: Optional[dict] = Depends(get_current_user_optional)
):
    """Sync Clerk user profile from frontend into backend database with identity verification"""
    client_ip = request.client.host if request.client else "unknown"
    _check_rate_limit(f"sync-user:{client_ip}", limit=30, window_sec=60)

    if not payload.userId:
        raise HTTPException(status_code=400, detail="User ID is required")

    # Verify that authenticated session matches requested sync user ID (unless in dev mode without token)
    if current_user and current_user.get("id") and current_user.get("id") != payload.userId:
        raise HTTPException(status_code=403, detail="Forbidden: User ID does not match authenticated token")

    key = f"clerk_user_{payload.userId}"
    user_data = {
        "email": payload.email,
        "first_name": payload.firstName,
        "last_name": payload.lastName,
        "image_url": payload.imageUrl,
    }

    setting = db.query(Setting).filter(Setting.key == key).first()
    if setting:
        setting.value = json.dumps(user_data)
    else:
        setting = Setting(
            key=key,
            value=json.dumps(user_data),
            description="Clerk user profile"
        )
        db.add(setting)

    db.commit()
    logger.info(f"Synced Clerk user {payload.userId} ({payload.email})")
    return {"status": "success", "user": user_data}


@router.get("/google")
def google_auth(
    request: Request,
    redirect_to: Optional[str] = None,
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional),
):
    """Generate Google OAuth authorization URL with CSRF state protection"""
    # If Google redirected directly back to /auth/google with code or error
    if request.query_params.get("code") or request.query_params.get("error"):
        return google_callback(request=request, db=db)

    client_ip = request.client.host if request.client else "unknown"
    _check_rate_limit(f"google-auth:{client_ip}", limit=20, window_sec=60)

    user_id = _google_owner_id(clerk_user, required=True)
    require_access_grant(user=clerk_user, db=db)
    frontend_origin = _get_frontend_origin(request)
    dest_path = _safe_oauth_redirect_to(redirect_to) or "/dashboard/classroom"

    # Generate a cryptographically secure CSRF state token
    csrf_token = secrets.token_urlsafe(32)
    state_key = f"oauth_csrf_state_{csrf_token}"
    _upsert_setting(
        db,
        key=state_key,
        value=json.dumps({
            "created_at": time.time(),
            "redirect_to": dest_path,
            "user_id": user_id,
            "frontend_origin": frontend_origin,
        }),
        description="OAuth CSRF State Token",
    )

    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [settings.google_redirect_uri],
            }
        },
        scopes=settings.google_scopes_list,
    )
    flow.redirect_uri = settings.google_redirect_uri
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
        state=csrf_token,
    )
    return {"auth_url": auth_url, "state": csrf_token}


@router.get("/google/callback")
def google_callback(request: Request, db: Session = Depends(get_db)):
    """Handle Google OAuth callback, validating CSRF state and exchanging code for tokens"""
    code = request.query_params.get("code")
    error = request.query_params.get("error")
    state = request.query_params.get("state")
    redirect_to = "/dashboard/classroom"
    user_id = None
    frontend_origin = None

    try:
        if state:
            state_key = f"oauth_csrf_state_{state}"
            try:
                state_record = db.query(Setting).filter(Setting.key == state_key).first()
                if state_record:
                    try:
                        oauth_state = json.loads(state_record.value)
                        redirect_to = _safe_oauth_redirect_to(oauth_state.get("redirect_to")) or "/dashboard/classroom"
                        user_id = str(oauth_state.get("user_id") or "")
                        frontend_origin = oauth_state.get("frontend_origin")
                    except (TypeError, ValueError, json.JSONDecodeError):
                        pass
                    try:
                        db.delete(state_record)
                        db.commit()
                    except Exception:
                        db.rollback()
            except (KeyError, SQLAlchemyError) as e:
                logger.warning(f"Could not read or clean up OAuth state record: {e}")
                db.rollback()
                return RedirectResponse(
                    url=_oauth_frontend_redirect(
                        redirect_to=redirect_to,
                        frontend_origin=frontend_origin,
                        google_error="callback_failed",
                    ),
                    status_code=302,
                )
            except Exception as e:
                logger.warning(f"Unexpected error reading OAuth state record: {e}")
                db.rollback()

        if error:
            logger.error(f"Google OAuth error received: {error}")
            return RedirectResponse(
                url=_oauth_frontend_redirect(
                    redirect_to=redirect_to,
                    frontend_origin=frontend_origin,
                    google_error=error if user_id else "invalid_oauth_state",
                ),
                status_code=302,
            )

        if not code or not state or not user_id:
            logger.warning(
                f"Google OAuth callback missing required data (code={bool(code)}, state={bool(state)}, user_id={bool(user_id)})"
            )
            return RedirectResponse(
                url=_oauth_frontend_redirect(
                    redirect_to=redirect_to,
                    frontend_origin=frontend_origin,
                    google_error="invalid_oauth_state",
                ),
                status_code=302,
            )

        # Exchange code for tokens directly with Google
        token_url = "https://oauth2.googleapis.com/token"
        token_payload = {
            "code": code,
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "redirect_uri": settings.google_redirect_uri,
            "grant_type": "authorization_code",
        }

        with httpx.Client(timeout=15.0) as client:
            token_resp = client.post(token_url, data=token_payload)

        if token_resp.status_code != 200:
            logger.error(f"Token exchange failed from Google: {token_resp.status_code} - {token_resp.text}")
            return RedirectResponse(
                url=_oauth_frontend_redirect(
                    redirect_to=redirect_to,
                    frontend_origin=frontend_origin,
                    google_error="token_exchange_failed",
                ),
                status_code=302,
            )

        token_data = token_resp.json()
        access_token = token_data.get("access_token")
        refresh_token = token_data.get("refresh_token")
        expires_in = token_data.get("expires_in", 3600)
        scopes = token_data.get("scope", "")
        expiry = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

        repo = GoogleCredentialRepository(db)
        existing_cred = repo.get(user_id)
        if not refresh_token and existing_cred:
            refresh_token = decrypt_token_if_encrypted(existing_cred.refresh_token)

        user_email = ""
        try:
            with httpx.Client(timeout=10.0) as client:
                userinfo_resp = client.get(
                    "https://www.googleapis.com/oauth2/v2/userinfo",
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                if userinfo_resp.status_code == 200:
                    userinfo = userinfo_resp.json()
                    user_email = userinfo.get("email", "")
        except Exception as e:
            logger.warning(f"Failed to fetch userinfo in callback: {e}")

        cred_data = {
            "access_token": encrypt_token_if_needed(access_token),
            "refresh_token": encrypt_token_if_needed(refresh_token),
            "token_uri": "https://oauth2.googleapis.com/token",
            "client_id": settings.google_client_id,
            "client_secret": None,
            "scopes": json.dumps(scopes.split()) if isinstance(scopes, str) else json.dumps(scopes),
            "expiry": expiry,
        }
        repo.create_or_update(user_id, cred_data)
        if user_email:
            email_key = f"google_connected_email_{user_id}"
            _upsert_setting(db, key=email_key, value=user_email, description="Google OAuth Account Email")
            _cached_google_emails[user_id] = user_email

        logger.info(f"Google OAuth connected successfully for user {user_id} ({user_email})")

        return RedirectResponse(
            url=_oauth_frontend_redirect(
                redirect_to=redirect_to,
                frontend_origin=frontend_origin,
                google_connected="true",
                email=user_email,
            ),
            status_code=302,
        )

    except Exception as exc:
        logger.error(f"Error during Google OAuth callback: {exc}", exc_info=True)
        db.rollback()
        return RedirectResponse(
            url=_oauth_frontend_redirect(
                redirect_to=redirect_to,
                frontend_origin=frontend_origin,
                google_error="callback_failed",
            ),
            status_code=302,
        )


@router.post("/google/disconnect", dependencies=[Depends(require_current_user), Depends(require_access_grant)])
@router.post("/logout", dependencies=[Depends(require_current_user)])
def logout(
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional),
):
    """Disconnect Google account"""
    user_id = _google_owner_id(clerk_user, required=True)
    repo = GoogleCredentialRepository(db)
    cred = repo.get(user_id)
    if cred:
        db.delete(cred)
        db.commit()
    _cached_google_emails.pop(user_id, None)
    return {"message": "Google account disconnected successfully"}


@router.get("/me", dependencies=[Depends(require_current_user)])
def get_current_user(
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional)
):
    """Get current user info combining Clerk profile and Google Classroom state"""
    repo = GoogleCredentialRepository(db)
    user_id = _google_owner_id(clerk_user)
    cred = repo.get(user_id) if user_id else None
    google_data = None
    if cred:
        try:
            access_token, refresh_token = get_google_credential_tokens(db, cred)
            creds = Credentials(
                token=access_token,
                refresh_token=refresh_token,
                token_uri=cred.token_uri or "https://oauth2.googleapis.com/token",
                client_id=cred.client_id or settings.google_client_id,
                client_secret=cred.client_secret or settings.google_client_secret,
                scopes=json.loads(cred.scopes) if cred.scopes else settings.google_scopes_list,
            )
            google_data = get_user_info(creds)
        except Exception as e:
            logger.warning(f"Failed to get Google user info: {e}")

    return {
        "authenticated": clerk_user is not None or google_data is not None,
        "user": clerk_user,
        "google": google_data,
        "google_connected": cred is not None,
    }


def get_user_info(creds: Credentials) -> dict:
    from googleapiclient.discovery import build
    service = build("oauth2", "v2", credentials=creds)
    return service.userinfo().get().execute()


def _get_notification_email_key(user_id: str) -> str:
    return f"notification_email_{user_id}"


@router.get(
    "/notification-email",
    response_model=NotificationEmailResponse,
    dependencies=[Depends(require_current_user), Depends(require_access_grant)],
)
def get_notification_email(
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional)
):
    """Get the user's configured notification email"""
    user_id = require_user_id(clerk_user)
    key = _get_notification_email_key(user_id)
    setting = db.query(Setting).filter(Setting.key == key).first()
    email = setting.value if setting and setting.value else None
    return NotificationEmailResponse(email=email, message="Notification email retrieved")


@router.put(
    "/notification-email",
    response_model=NotificationEmailResponse,
    dependencies=[Depends(require_current_user), Depends(require_access_grant)],
)
def set_notification_email(
    payload: NotificationEmailRequest,
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional)
):
    """Set the user's notification email for alerts and notifications"""
    user_id = require_user_id(clerk_user)

    key = _get_notification_email_key(user_id)
    setting = db.query(Setting).filter(Setting.key == key).first()
    if setting:
        setting.value = payload.email
    else:
        setting = Setting(key=key, value=payload.email, description="User notification email for alerts")
        db.add(setting)

    db.commit()
    return NotificationEmailResponse(email=payload.email, message="Notification email updated successfully")


@router.delete(
    "/notification-email",
    response_model=NotificationEmailResponse,
    dependencies=[Depends(require_current_user), Depends(require_access_grant)],
)
def delete_notification_email(
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional)
):
    """Remove the user's notification email preference"""
    user_id = require_user_id(clerk_user)
    key = _get_notification_email_key(user_id)
    setting = db.query(Setting).filter(Setting.key == key).first()
    if setting:
        db.delete(setting)
    db.commit()
    return NotificationEmailResponse(email=None, message="Notification email removed")
