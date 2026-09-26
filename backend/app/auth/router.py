from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import RedirectResponse
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from sqlalchemy.orm import Session
from app.core.config import settings
from app.db.database import get_db
from app.db.repositories import GoogleCredentialRepository
from app.core.logging import logger
import json


router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.get("/google")
def google_auth():
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
    code = request.query_params.get("code")
    state = request.query_params.get("state")
    error = request.query_params.get("error")

    if error:
        raise HTTPException(status_code=400, detail=f"OAuth error: {error}")

    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code")

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
        state=state,
    )
    flow.redirect_uri = settings.google_redirect_uri

    try:
        flow.fetch_token(code=code)
    except Exception as e:
        logger.error(f"Failed to fetch token: {e}")
        raise HTTPException(status_code=400, detail=f"Failed to exchange code: {e}")

    creds = flow.credentials

    userinfo = get_user_info(creds)
    expected_email = settings.notification_email
    if expected_email and userinfo.get("email") != expected_email:
        logger.warning(f"Unauthorized account: {userinfo.get('email')}")
        raise HTTPException(status_code=403, detail="Unauthorized Google account")

    repo = GoogleCredentialRepository(db)
    cred_data = {
        "access_token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": json.dumps(creds.scopes),
        "expiry": creds.expiry,
    }
    repo.create_or_update(cred_data)

    logger.info(f"Google OAuth successful for {userinfo.get('email')}")
    return {"message": "Google account connected successfully", "email": userinfo.get("email")}


@router.post("/logout")
def logout(db: Session = Depends(get_db)):
    repo = GoogleCredentialRepository(db)
    cred = repo.get()
    if cred:
        db.delete(cred)
        db.commit()
    return {"message": "Logged out successfully"}


@router.get("/me")
def get_current_user(db: Session = Depends(get_db)):
    repo = GoogleCredentialRepository(db)
    cred = repo.get()
    if not cred:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    try:
        creds = Credentials(
            token=cred.access_token,
            refresh_token=cred.refresh_token,
            token_uri=cred.token_uri,
            client_id=cred.client_id,
            client_secret=cred.client_secret,
            scopes=json.loads(cred.scopes) if cred.scopes else settings.google_scopes_list,
        )
        userinfo = get_user_info(creds)
        return {"authenticated": True, "email": userinfo.get("email"), "name": userinfo.get("name")}
    except Exception as e:
        logger.error(f"Failed to get user info: {e}")
        raise HTTPException(status_code=401, detail="Invalid credentials")


def get_user_info(creds: Credentials) -> dict:
    from googleapiclient.discovery import build
    service = build("oauth2", "v2", credentials=creds)
    return service.userinfo().get().execute()