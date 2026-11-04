import json
import io
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseUpload
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


def upload_pdf_to_drive(db: Session, user_id: str, filename: str, content: bytes) -> tuple[str, str]:
    """Upload a PDF to the connected user's Drive and return its ID and view URL."""
    drive = get_drive_service(db, user_id)
    try:
        uploaded = drive.files().create(
            body={"name": filename, "mimeType": "application/pdf"},
            media_body=MediaIoBaseUpload(io.BytesIO(content), mimetype="application/pdf", resumable=True),
            fields="id,webViewLink",
        ).execute()
    except HttpError as error:
        if error.resp.status in (401, 403):
            raise HTTPException(
                status_code=409,
                detail="Reconnect Google Classroom to let Uniflow save PDFs to your Google Drive.",
            ) from error
        raise HTTPException(status_code=502, detail="Google Drive could not save this PDF right now.") from error

    file_id = uploaded.get("id")
    if not file_id:
        raise HTTPException(status_code=502, detail="Google Drive did not return a file ID for this PDF.")
    return file_id, uploaded.get("webViewLink") or f"https://drive.google.com/file/d/{file_id}/view"
