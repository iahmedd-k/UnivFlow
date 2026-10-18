import json
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import get_google_credential_tokens, encrypt_token_if_needed
from app.db.models import GoogleCredential
from fastapi import HTTPException

def get_drive_service(db: Session, user_id: str):
    """Return an authenticated Google Drive service instance.
    Reuses the same credential handling logic as the Google integrations router.
    """
    credential = db.query(GoogleCredential).filter(GoogleCredential.user_id == user_id).first()
    if not credential:
        raise HTTPException(status_code=409, detail="Connect your Google account first.")

    access_token, refresh_token = get_google_credential_tokens(db, credential)
    credentials = Credentials(
        token=access_token,
        refresh_token=refresh_token,
        token_uri=credential.token_uri or "https://oauth2.googleapis.com/token",
        client_id=credential.client_id or settings.google_client_id,
        client_secret=credential.client_secret or settings.google_client_secret,
        scopes=json.loads(credential.scopes) if credential.scopes else settings.google_scopes_list,
    )
    if credentials.expired and credentials.refresh_token:
        from google.auth.transport.requests import Request
        credentials.refresh(Request())
        credential.access_token = encrypt_token_if_needed(credentials.token)
        credential.expiry = credentials.expiry
        db.commit()
    # Build Drive service
    return build("drive", "v3", credentials=credentials, cache_discovery=False)
