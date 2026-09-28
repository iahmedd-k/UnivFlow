import json
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.database import get_db
from app.db.models import GoogleCredential, Setting

router = APIRouter(prefix="/integrations/google", tags=["Google integrations"])


def _services(db: Session):
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

    return credentials


def _execute(request):
    try:
        return request.execute()
    except HttpError as error:
        if error.resp.status in (401, 403):
            raise HTTPException(
                status_code=403,
                detail="Google access needs the latest read permissions. Disconnect and reconnect your Google account.",
            ) from error
        raise HTTPException(status_code=502, detail="Google could not return this data right now.") from error


def _get_semester_start(db: Session, override: Optional[str] = None) -> Optional[datetime]:
    val = override
    if not val:
        setting = db.query(Setting).filter(Setting.key == "semester_start_date").first()
        if setting and setting.value:
            val = setting.value.strip().replace('"', '')
    if val:
        try:
            if len(val) == 10:
                dt = datetime.fromisoformat(f"{val}T00:00:00+00:00")
            else:
                dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            pass
    return None


def _categorize_email(from_str: str, subject_str: str, snippet_str: str) -> tuple[str, str]:
    subj_lower = (subject_str or "").lower()
    from_lower = (from_str or "").lower()
    combined = f"{from_str} {subject_str} {snippet_str}".lower()

    # 1. Google Classroom Notifications
    if any(k in combined for k in [
        "classroom.google.com", "notifications@google.com", "google classroom",
        "new assignment", "new material", "new question", "due tomorrow", "due today",
        "returned:", "graded:", "posted a new", "coursework"
    ]):
        return "classroom", "Google Classroom"

    # 2. University Official: Subject MUST explicitly include titles like 'notification', 'notice', 'circular', 'advisory', etc.
    is_university_source = any(k in from_lower or k in combined for k in [
        "@au.edu.pk", "@students.au.edu.pk", "air university", "registrar",
        "examination", "facilitation", "qec", "vice chancellor", "vc office",
        "admissions", "fee section", "directorate", "academic"
    ])
    has_notification_title = any(k in subj_lower for k in [
        "notification", "notice", "circular", "advisory", "official announcement", "announcement", "office order", "memo"
    ])

    if is_university_source and has_notification_title:
        return "university", "University Notification"

    # 3. Other / General / Social (All other university correspondence and external emails go to 'other')
    return "other", "General / Other"


@router.get("/emails", response_model=list[dict])
def get_recent_emails(
    limit: int = Query(20, ge=1, le=50),
    since: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    credentials = _services(db)
    gmail = build("gmail", "v1", credentials=credentials, cache_discovery=False)

    since_dt = _get_semester_start(db, since)
    q_filter = ""
    if since_dt:
        # Gmail after query format: YYYY/MM/DD
        q_filter = f"after:{since_dt.strftime('%Y/%m/%d')}"

    # Fetch slightly more to satisfy category filter limits
    fetch_max = min(50, limit * 2) if category and category != "all" else limit
    list_params = {"userId": "me", "maxResults": fetch_max, "labelIds": ["INBOX"]}
    if q_filter:
        list_params["q"] = q_filter

    listed = _execute(gmail.users().messages().list(**list_params))
    emails = []
    for item in listed.get("messages", []):
        message = _execute(
            gmail.users().messages().get(
                userId="me", id=item["id"], format="metadata", metadataHeaders=["From", "Subject", "Date"]
            )
        )
        headers = {header["name"].lower(): header["value"] for header in message.get("payload", {}).get("headers", [])}
        from_val = headers.get("from", "Unknown sender")
        subj_val = headers.get("subject", "(no subject)")
        snip_val = message.get("snippet", "")
        cat_key, cat_label = _categorize_email(from_val, subj_val, snip_val)

        if category and category != "all" and cat_key != category.lower():
            continue

        emails.append({
            "id": message["id"],
            "thread_id": message.get("threadId"),
            "from": from_val,
            "subject": subj_val,
            "date": headers.get("date"),
            "snippet": snip_val,
            "category": cat_key,
            "category_label": cat_label,
            "unread": "UNREAD" in message.get("labelIds", []),
        })

        if len(emails) >= limit:
            break

    return emails


@router.get("/drive", response_model=list[dict])
def get_recent_drive_files(
    limit: int = Query(12, ge=1, le=50),
    since: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    credentials = _services(db)
    drive = build("drive", "v3", credentials=credentials, cache_discovery=False)

    since_dt = _get_semester_start(db, since)
    q_filter = "trashed = false"
    if since_dt:
        iso_str = since_dt.strftime('%Y-%m-%dT%H:%M:%SZ')
        q_filter += f" and modifiedTime >= '{iso_str}'"

    files = _execute(drive.files().list(
        q=q_filter,
        orderBy="modifiedTime desc",
        pageSize=limit,
        fields="files(id,name,mimeType,modifiedTime,webViewLink,iconLink,owners(displayName,emailAddress))",
    ))
    return files.get("files", [])
