import os
import json
import httpx
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.database import get_db
from app.db.repositories import GoogleCredentialRepository
from app.db.models import Setting
from app.core.logging import logger
from app.auth.clerk_auth import get_current_user_optional

# Allow HTTP transport for local development OAuth
os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"
os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"

router = APIRouter(prefix="/auth", tags=["Authentication"])


class UserSyncRequest(BaseModel):
    userId: str
    email: Optional[str] = ""
    firstName: Optional[str] = ""
    lastName: Optional[str] = ""
    imageUrl: Optional[str] = ""


@router.get("/status")
def get_auth_status(
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional)
):
    """Check overall auth status (Clerk user & Google Classroom connection)"""
    repo = GoogleCredentialRepository(db)
    cred = repo.get()
    google_connected = cred is not None
    google_email = None

    if cred:
        try:
            creds = Credentials(
                token=cred.access_token,
                refresh_token=cred.refresh_token,
                token_uri=cred.token_uri or "https://oauth2.googleapis.com/token",
                client_id=cred.client_id or settings.google_client_id,
                client_secret=cred.client_secret or settings.google_client_secret,
                scopes=json.loads(cred.scopes) if cred.scopes else settings.google_scopes_list,
            )
            userinfo = get_user_info(creds)
            google_email = userinfo.get("email")
        except Exception as e:
            logger.warning(f"Could not fetch Google userinfo: {e}")
            # If cred exists in DB, treat as connected even if token needs refresh
            google_connected = cred.access_token is not None

    return {
        "authenticated": clerk_user is not None,
        "clerk_user": clerk_user,
        "google_connected": google_connected,
        "google_email": google_email,
    }


@router.post("/sync-user")
def sync_user(payload: UserSyncRequest, db: Session = Depends(get_db)):
    """Sync Clerk user profile from frontend into backend database"""
    if not payload.userId:
        raise HTTPException(status_code=400, detail="User ID is required")

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
    db: Session = Depends(get_db)
):
    """Generate Google OAuth authorization URL, or handle callback if code is present"""
    # If Google redirected directly back to /auth/google with code or error
    if request.query_params.get("code") or request.query_params.get("error"):
        return google_callback(request=request, db=db)

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
    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    return {"auth_url": auth_url, "state": state}


@router.get("/google/callback")
def google_callback(request: Request, db: Session = Depends(get_db)):
    """Handle Google OAuth callback and exchange authorization code for tokens"""
    code = request.query_params.get("code")
    error = request.query_params.get("error")

    if error:
        logger.error(f"Google OAuth error received: {error}")
        return RedirectResponse(
            url=f"{settings.frontend_url}?google_error={error}",
            status_code=302
        )

    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code")

    try:
        # Direct, resilient token exchange with Google
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
                url=f"{settings.frontend_url}?google_error=token_exchange_failed",
                status_code=302
            )

        token_data = token_resp.json()
        access_token = token_data.get("access_token")
        refresh_token = token_data.get("refresh_token")
        expires_in = token_data.get("expires_in", 3600)
        scopes = token_data.get("scope", "")
        expiry = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

        # Get existing credential if any to retain refresh token if not in response
        repo = GoogleCredentialRepository(db)
        existing_cred = repo.get()
        if not refresh_token and existing_cred:
            refresh_token = existing_cred.refresh_token

        # Fetch user info using access token
        user_email = ""
        try:
            with httpx.Client(timeout=10.0) as client:
                userinfo_resp = client.get(
                    "https://www.googleapis.com/oauth2/v2/userinfo",
                    headers={"Authorization": f"Bearer {access_token}"}
                )
                if userinfo_resp.status_code == 200:
                    userinfo = userinfo_resp.json()
                    user_email = userinfo.get("email", "")
        except Exception as e:
            logger.warning(f"Failed to fetch userinfo in callback: {e}")

        # Save credentials to database
        cred_data = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_uri": "https://oauth2.googleapis.com/token",
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "scopes": json.dumps(scopes.split()) if isinstance(scopes, str) else json.dumps(scopes),
            "expiry": expiry,
        }
        repo.create_or_update(cred_data)

        logger.info(f"Google OAuth connected successfully for {user_email or 'User'}")

        # Clean redirect to frontend
        return RedirectResponse(
            url=f"{settings.frontend_url}?google_connected=true&email={user_email}",
            status_code=302
        )

    except Exception as e:
        logger.error(f"Error during Google OAuth callback: {e}", exc_info=True)
        return RedirectResponse(
            url=f"{settings.frontend_url}?google_error=token_exchange_failed",
            status_code=302
        )


@router.post("/google/disconnect")
@router.post("/logout")
def logout(db: Session = Depends(get_db)):
    """Disconnect Google account"""
    repo = GoogleCredentialRepository(db)
    cred = repo.get()
    if cred:
        db.delete(cred)
        db.commit()
    return {"message": "Google account disconnected successfully"}


@router.get("/me")
def get_current_user(
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional)
):
    """Get current user info combining Clerk profile and Google Classroom state"""
    repo = GoogleCredentialRepository(db)
    cred = repo.get()
    google_data = None
    if cred:
        try:
            creds = Credentials(
                token=cred.access_token,
                refresh_token=cred.refresh_token,
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