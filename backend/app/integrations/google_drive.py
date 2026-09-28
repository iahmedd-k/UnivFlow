import json
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import GoogleCredential
from fastapi import HTTPException

def get_drive_service(db: Session):
    """Return an authenticated Google Drive service instance.
    Reuses the same credential handling logic as the Google integrations router.
    """
    credential = db.query(GoogleCredential).first()
    if not credential:
        raise HTTPException(status_code=409, detail="Connect your Google account first.")

    credentials = Credentials(
        token=credential.access_token,
        refresh_token=credential.refresh_token,
        token_uri=credential.token_uri or "https://oauth2.googleapis.com/token",
        client_id=credential.client_id or settings.google_client_id,
        client_secret=credential.client_secret or settings.google_client_secret,
        scopes=json.loads(credential.scopes) if credential.scopes else settings.google_scopes_list,
    )
    if credentials.expired and credentials.refresh_token:
        from google.auth.transport.requests import Request
        credentials.refresh(Request())
        credential.access_token = credentials.token
        credential.expiry = credentials.expiry
        db.commit()
    # Build Drive service
    return build("drive", "v3", credentials=credentials, cache_discovery=False)
