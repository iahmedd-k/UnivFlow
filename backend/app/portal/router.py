import asyncio
import json
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlsplit

from typing import Optional, Dict, Any, Tuple

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth.clerk_auth import require_current_user
from app.core.logging import logger
from app.db.database import get_db, SessionLocal
from app.db.models import Course, Setting, TimetableEntry, ClassSchedule
from app.db.repositories import AttendanceRecordRepository, CourseRepository, ClassScheduleRepository

router = APIRouter(prefix="/portal", tags=["University portal"])

PORTAL_PROFILE_ROOT = Path(__file__).resolve().parent.parent.parent / "tmp" / "portal_browser_profiles"
PORTAL_PROFILE_ROOT.mkdir(parents=True, exist_ok=True)

_portal_processes: dict[str, Any] = {}
_sync_locks: dict[str, threading.Lock] = {}
_sync_jobs: dict[str, dict] = {}
_active_sync_jobs: dict[str, str] = {}
_sync_jobs_lock = threading.Lock()


class PortalUrlInput(BaseModel):
    url: str = Field(min_length=8, max_length=1000)
    attendance_url: str | None = Field(default=None, max_length=1000)
    timetable_url: str | None = Field(default=None, max_length=1000)
    login_email: str | None = Field(default=None, max_length=320)
    auth_method: str = Field(default="google", pattern="^(google|password|either)$")


def _find_system_browser() -> str:
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    for command in ("chrome", "google-chrome", "msedge", "microsoft-edge", "chromium", "chromium-browser"):
        found = shutil.which(command)
        if found:
            return found
    return ""


def _cleanup_dead_portal_processes():
    dead = []
    for uid, proc in list(_portal_processes.items()):
        try:
            if hasattr(proc, "poll") and proc.poll() is not None:
                dead.append(uid)
        except Exception:
            dead.append(uid)
    for uid in dead:
        _portal_processes.pop(uid, None)


def _validate_portal_url(value: str) -> str:
    cleaned = value.strip()
    if not cleaned.startswith("http://") and not cleaned.startswith("https://"):
        cleaned = f"https://{cleaned}"
    parsed = urlsplit(cleaned)
    if parsed.scheme not in ("https", "http") or not parsed.hostname or parsed.username or parsed.password:
        raise HTTPException(status_code=422, detail="Enter a valid university portal URL (e.g. https://portals.au.edu.pk/students/).")
    # SSRF protection: reject loopback / link-local / AWS metadata addresses
    hostname = (parsed.hostname or "").lower()
    if hostname in ("localhost", "127.0.0.1", "::1", "0.0.0.0") or hostname.startswith("169.254.") or hostname.startswith("10.") or hostname.startswith("192.168."):
        raise HTTPException(status_code=422, detail="Internal network and metadata addresses are not permitted as portal URLs.")
    return cleaned


def _setting(db: Session, key: str):
    return db.query(Setting).filter(Setting.key == key).first()


def _set_setting(db: Session, key: str, value: str, description: str = ""):
    item = _setting(db, key)
    if not item:
        item = Setting(key=key, description=description or key)
        db.add(item)
    item.value = value
    return item


def _user_id(user: dict | None) -> str:
    return str((user or {}).get("id") or "dev_student_user")


def _user_setting_key(user_id: str, key: str) -> str:
    # Clerk IDs are short and let the background worker enumerate connected users.
    return f"portal:{user_id}:{key}"


def _portal_setting(db: Session, user_id: str, key: str):
    return _setting(db, _user_setting_key(user_id, key))


def _set_portal_setting(db: Session, user_id: str, key: str, value: str, description: str = ""):
    return _set_setting(db, _user_setting_key(user_id, key), value, description)


def _profile_dir(user_id: str) -> Path:
    # Use a fresh automation profile rather than a personal Chrome profile.
    # Chrome cannot add the CDP debugging port when it reuses an already-running
    # regular profile, which made portal login detection and sync fail silently.
    path = PORTAL_PROFILE_ROOT / (sha256(user_id.encode("utf-8")).hexdigest()[:32] + "-automation-v2")
    path.mkdir(parents=True, exist_ok=True)
    return path


def _cdp_port(user_id: str) -> int:
    # Chrome only permits one listener per port; keep concurrent student profiles isolated.
    return 10000 + int(sha256(user_id.encode("utf-8")).hexdigest()[:4], 16) % 40000


def _cdp_is_available(user_id: str, timeout: float = 0.4) -> bool:
    """Return true only when this user's Chrome remote-debugging endpoint is live."""
    request = urllib.request.Request(f"http://127.0.0.1:{_cdp_port(user_id)}/json/version")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return bool(payload.get("webSocketDebuggerUrl"))
    except (OSError, ValueError, urllib.error.URLError):
        return False


def _wait_for_cdp(user_id: str, timeout: float = 8.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _cdp_is_available(user_id):
            return True
        time.sleep(0.2)
    return _cdp_is_available(user_id)


@router.get("/settings", response_model=dict)
def get_portal_settings(db: Session = Depends(get_db), user: dict = Depends(require_current_user)):
    uid = _user_id(user)
    url_setting = _portal_setting(db, uid, "university_portal_url")
    att_url_setting = _portal_setting(db, uid, "portal_attendance_url")
    tt_url_setting = _portal_setting(db, uid, "portal_timetable_url")
    grades_url_setting = _portal_setting(db, uid, "portal_grades_url")
    email = _portal_setting(db, uid, "university_portal_login_email")
    auth_method = _portal_setting(db, uid, "university_portal_auth_method")
    report = _portal_setting(db, uid, "portal_academic_summary")
    session_status = _portal_setting(db, uid, "portal_session_status")
    last_synced = _portal_setting(db, uid, "portal_last_synced_at")

    profile = _profile_dir(uid)
    has_saved_session = profile.exists() and any(profile.iterdir())

    status = "NOT_CONFIGURED"
    if session_status and session_status.value:
        status = session_status.value
    elif has_saved_session:
        status = "ACTIVE"

    process = _portal_processes.get(uid)
    is_open = (process is not None and process.poll() is None) or _cdp_is_available(uid)

    return {
        "url": url_setting.value if url_setting else "",
        "attendance_url": att_url_setting.value if att_url_setting else "",
        "timetable_url": tt_url_setting.value if tt_url_setting else "",
        "grades_url": grades_url_setting.value if grades_url_setting else "",
        "login_email": email.value if email else "",
        "auth_method": auth_method.value if auth_method else "google",
        "report": json.loads(report.value) if report and report.value else None,
        "browser_open": is_open,
        "has_saved_session": has_saved_session,
        "session_status": status,
        "last_synced_at": last_synced.value if last_synced else None,
    }


@router.put("/settings", response_model=dict)
def save_portal_settings(payload: PortalUrlInput, db: Session = Depends(get_db), user: dict = Depends(require_current_user)):
    uid = _user_id(user)
    url = _validate_portal_url(payload.url)
    _set_portal_setting(db, uid, "university_portal_url", url, "Student-configured university portal URL")
    if payload.attendance_url:
        att_url = _validate_portal_url(payload.attendance_url)
        _set_portal_setting(db, uid, "portal_attendance_url", att_url, "Discovered attendance report URL")
    if payload.timetable_url:
        tt_url = _validate_portal_url(payload.timetable_url)
        _set_portal_setting(db, uid, "portal_timetable_url", tt_url, "Discovered timetable report URL")
    _set_portal_setting(db, uid, "university_portal_login_email", payload.login_email or "", "Email used for university portal sign-in")
    _set_portal_setting(db, uid, "university_portal_auth_method", payload.auth_method, "Portal sign-in method selected by the student")
    db.commit()
    return {"url": url, "saved": True}


@router.post("/open", response_model=dict)
async def open_portal_browser(db: Session = Depends(get_db), user: dict = Depends(require_current_user)):
    uid = _user_id(user)
    url_setting = _portal_setting(db, uid, "university_portal_url")
    if not url_setting or not url_setting.value:
        raise HTTPException(status_code=409, detail="Save your university portal URL first.")

    url = _validate_portal_url(url_setting.value)
    browser_bin = _find_system_browser()
    process = _portal_processes.get(uid)
    if _cdp_is_available(uid):
        _set_portal_setting(db, uid, "portal_session_status", "CONNECTING", "University portal sign-in is open")
        db.commit()
        return {
            "opened": True,
            "title": "Google Chrome (Sign-In Window)",
            "url": url,
            "password_form_available": True,
            "google_sign_in_available": True,
            "is_direct_google_oauth": True,
            "login_email": (_portal_setting(db, uid, "university_portal_login_email").value if _portal_setting(db, uid, "university_portal_login_email") else ""),
            "auth_method": (_portal_setting(db, uid, "university_portal_auth_method").value if _portal_setting(db, uid, "university_portal_auth_method") else "google"),
            "message": "Your portal sign-in window is open. Sign in once; Uniflow will discover and sync your academic pages automatically.",
        }

    if not browser_bin:
        raise HTTPException(status_code=503, detail="Chrome or Edge was not found on the computer running the Uniflow API.")

    # If a previous launch is still alive but its debugging endpoint is gone,
    # retire that owned process before starting a correctly configured profile.
    if process is not None and process.poll() is None:
        try:
            process.terminate()
        except Exception:
            pass
    elif process is not None:
        _portal_processes.pop(uid, None)

    _set_portal_setting(db, uid, "portal_session_status", "CONNECTING", "University portal sign-in is open")
    db.commit()
    cmd = [
        browser_bin,
        f"--user-data-dir={str(_profile_dir(uid))}",
        f"--remote-debugging-port={_cdp_port(uid)}",
        "--remote-debugging-address=127.0.0.1",
        "--no-first-run",
        "--no-default-browser-check",
        "--start-maximized",
        url,
    ]

    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=(os.name != "nt")
        )
        _portal_processes[uid] = process
    except Exception as error:
        _set_portal_setting(db, uid, "portal_session_status", "ERROR", "Could not launch portal sign-in browser")
        db.commit()
        raise HTTPException(status_code=502, detail=f"Could not launch browser: {str(error)}") from error

    if not _wait_for_cdp(uid):
        try:
            process.terminate()
        except Exception:
            pass
        _portal_processes.pop(uid, None)
        _set_portal_setting(db, uid, "portal_session_status", "ERROR", "University browser remote debugging did not start")
        db.commit()
        raise HTTPException(status_code=502, detail="The sign-in browser opened, but its local connection did not start. Close other Uniflow portal windows and try again.")

    login_email_val = _portal_setting(db, uid, "university_portal_login_email")
    auth_method_val = _portal_setting(db, uid, "university_portal_auth_method")

    return {
        "opened": True,
        "title": "Google Chrome (Sign-In Window)",
        "url": url,
        "password_form_available": True,
        "google_sign_in_available": True,
        "is_direct_google_oauth": True,
        "login_email": login_email_val.value if login_email_val and login_email_val.value else "",
        "auth_method": auth_method_val.value if auth_method_val and auth_method_val.value else "google",
        "message": "Sign in once in Uniflow's separate university window. Your saved session will be reused for future syncs.",
    }


def _report_summary(tables: list, text: str):
    cgpa_match = re.search(r"(?:c\.?g\.?p\.?a\.?|cumulative\s+gpa|overall\s+gpa)\s*[:\-]?\s*(\d{1,2}(?:\.\d{1,3})?)", text, re.IGNORECASE)
    sgpa_match = re.search(r"(?:s\.?g\.?p\.?a\.?|semester\s+gpa|term\s+gpa|current\s+gpa)\s*[:\-]?\s*(\d{1,2}(?:\.\d{1,3})?)", text, re.IGNORECASE)
    credits_match = re.search(r"(?:earned\s+credits?|cr(?:\.?\s*hrs?)?\s*earned|completed\s+credits?|total\s+cr(?:\.?\s*hrs?)?)\s*[:\-]?\s*(\d{1,3})", text, re.IGNORECASE)
    semester_match = re.search(r"((?:current\s+)?semester\s*[:\-]?\s*[^\n|]{2,60})", text, re.IGNORECASE)

    semesters = []
    # Search tables for semester history / grade report
    for table in tables:
        if not table or len(table) < 2:
            continue
        headers = [str(c).strip().lower() for c in table[0]]
        sem_col = -1
        sgpa_col = -1
        cgpa_col = -1
        cr_col = -1

        for idx, h in enumerate(headers):
            if any(k in h for k in ["semester", "term", "session"]) and not any(k in h for k in ["start", "end", "date"]):
                sem_col = idx
            elif any(k in h for k in ["sgpa", "gpa", "term gpa", "semester gpa"]):
                sgpa_col = idx
            elif any(k in h for k in ["cgpa", "cum gpa", "overall gpa"]):
                cgpa_col = idx
            elif any(k in h for k in ["credit", "cr. hrs", "cr hrs", "credits", "ch"]):
                cr_col = idx

        if sem_col != -1 and (sgpa_col != -1 or cgpa_col != -1):
            for row in table[1:]:
                cells = [str(c).strip() for c in row]
                if len(cells) <= max(sem_col, sgpa_col if sgpa_col != -1 else 0):
                    continue
                sem_name = cells[sem_col]
                if not sem_name or len(sem_name) < 2 or sem_name.lower() in ["total", "summary", "average"]:
                    continue
                s_val = None
                c_val = None
                cr_val = None
                try:
                    if sgpa_col != -1 and sgpa_col < len(cells):
                        s_m = re.search(r"(\d{1,2}(?:\.\d{1,3})?)", cells[sgpa_col])
                        if s_m:
                            s_val = float(s_m.group(1))
                except Exception:
                    pass
                try:
                    if cgpa_col != -1 and cgpa_col < len(cells):
                        c_m = re.search(r"(\d{1,2}(?:\.\d{1,3})?)", cells[cgpa_col])
                        if c_m:
                            c_val = float(c_m.group(1))
                except Exception:
                    pass
                try:
                    if cr_col != -1 and cr_col < len(cells):
                        cr_m = re.search(r"(\d{1,3})", cells[cr_col])
                        if cr_m:
                            cr_val = int(cr_m.group(1))
                except Exception:
                    pass
                if s_val is not None or c_val is not None:
                    semesters.append({
                        "semester": sem_name,
                        "sgpa": s_val,
                        "cgpa": c_val,
                        "credits": cr_val
                    })

    parsed_cgpa = float(cgpa_match.group(1)) if cgpa_match else (semesters[-1]["cgpa"] if semesters and semesters[-1].get("cgpa") else None)
    parsed_sgpa = float(sgpa_match.group(1)) if sgpa_match else (semesters[-1]["sgpa"] if semesters and semesters[-1].get("sgpa") else None)
    parsed_credits = int(credits_match.group(1)) if credits_match else (sum(s["credits"] for s in semesters if s.get("credits")) if semesters else None)

    strategy = None
    if parsed_cgpa is not None:
        if parsed_cgpa >= 3.5:
            strategy = "Dean's Honor Standing. Maintain >= 3.50 this semester to secure academic distinction."
        elif parsed_cgpa >= 3.0:
            strategy = "Strong Academic Standing. Aim for >= 3.60 to elevate your CGPA into distinction honors."
        elif parsed_cgpa >= 2.5:
            strategy = "Satisfactory Progress. Target >= 3.30 next semester to strengthen your graduation standing."
        else:
            strategy = "Academic Focus Needed. Prioritize higher credit core courses to pull CGPA above 2.50."

    return {
        "cgpa": parsed_cgpa,
        "sgpa": parsed_sgpa,
        "earned_credits": parsed_credits,
        "semester_name": re.sub(r"\s+", " ", semester_match.group(1)).strip() if semester_match else None,
        "semesters": semesters,
        "strategy_summary": strategy,
    }


def _attendance_rows(tables: list, text: str = ""):
    results = []
    seen_subjects = set()

    for table in tables:
        if not table:
            continue
        headers = [str(cell).strip().lower() for cell in table[0]]
        subject_col = -1
        attended_col = -1
        total_col = -1
        percent_col = -1

        for idx, h in enumerate(headers):
            if any(k in h for k in ["subject", "course", "title", "name", "paper"]) and not any(k in h for k in ["room", "teacher", "day"]):
                subject_col = idx
            elif any(k in h for k in ["present", "attended", "delivered present", "lec present"]):
                attended_col = idx
            elif any(k in h for k in ["total", "held", "delivered", "lectures"]):
                total_col = idx
            elif any(k in h for k in ["percentage", "percent", "%", "attendance %"]):
                percent_col = idx

        for row in table[1:]:
            cells = [str(cell).strip() for cell in row]
            if not cells or len(cells) < 2:
                continue

            subject = ""
            if subject_col != -1 and subject_col < len(cells) and cells[subject_col]:
                subject = cells[subject_col]
            else:
                for c in cells:
                    if len(c) > 3 and not re.fullmatch(r"[\d.%/ -]+", c):
                        subject = c
                        break

            if not subject or subject.lower() in ["total", "summary", "average", "status", "gpa", "cgpa", "overall"]:
                continue

            attended, total, percentage = None, None, None

            if attended_col != -1 and attended_col < len(cells) and total_col != -1 and total_col < len(cells):
                try:
                    att_num = int(re.sub(r"[^\d]", "", cells[attended_col]))
                    tot_num = int(re.sub(r"[^\d]", "", cells[total_col]))
                    if tot_num > 0 and att_num <= tot_num:
                        attended, total = att_num, tot_num
                        percentage = round(attended * 100 / total, 2)
                except Exception:
                    pass

            if percentage is None and percent_col != -1 and percent_col < len(cells):
                try:
                    pct_match = re.search(r"(\d{1,3}(?:\.\d+)?)", cells[percent_col])
                    if pct_match:
                        percentage = float(pct_match.group(1))
                        total = 100
                        attended = round(percentage)
                except Exception:
                    pass

            if percentage is None:
                combined = " ".join(cells)
                fraction = re.search(r"(\d+)\s*/\s*(\d+)", combined)
                percent = re.search(r"(\d{1,3}(?:\.\d+)?)\s*%", combined)
                if fraction:
                    att, tot = int(fraction.group(1)), int(fraction.group(2))
                    if tot > 0 and att <= tot:
                        attended, total = att, tot
                        percentage = round(attended * 100 / total, 2) if total > 0 else 0.0
                elif percent:
                    percentage = float(percent.group(1))
                    total, attended = 100, round(percentage)

            if subject and percentage is not None and subject.lower() not in seen_subjects:
                seen_subjects.add(subject.lower())
                results.append({
                    "subject": subject,
                    "attended": attended or (round(percentage) if percentage is not None else 0),
                    "total": total or 100,
                    "percentage": percentage
                })

    if not results and text:
        lines = text.split("\n")
        for line in lines:
            line_str = line.strip()
            if not line_str or len(line_str) < 5:
                continue
            fraction = re.search(r"([A-Za-z0-9\s\-–:()]{3,40}?)\s+[:\-–]?\s*(\d+)\s*/\s*(\d+)", line_str)
            percent = re.search(r"([A-Za-z0-9\s\-–:()]{3,40}?)\s+[:\-–]?\s*(\d{1,3}(?:\.\d+)?)\s*%", line_str)
            if fraction:
                subj = fraction.group(1).strip()
                att, tot = int(fraction.group(2)), int(fraction.group(3))
                if tot > 0 and att <= tot and subj.lower() not in seen_subjects:
                    seen_subjects.add(subj.lower())
                    results.append({
                        "subject": subj,
                        "attended": att,
                        "total": tot,
                        "percentage": round(att * 100 / tot, 2) if tot > 0 else 0.0
                    })
            elif percent:
                subj = percent.group(1).strip()
                pct = float(percent.group(2))
                if 0 <= pct <= 100 and subj.lower() not in seen_subjects:
                    seen_subjects.add(subj.lower())
                    results.append({
                        "subject": subj,
                        "attended": round(pct),
                        "total": 100,
                        "percentage": pct
                    })

    return results


WEEKDAY_NAME_TO_INT = {
    "monday": 0, "mon": 0,
    "tuesday": 1, "tue": 1, "tues": 1,
    "wednesday": 2, "wed": 2,
    "thursday": 3, "thu": 3, "thur": 3, "thurs": 3,
    "friday": 4, "fri": 4,
    "saturday": 5, "sat": 5,
    "sunday": 6, "sun": 6,
}

TIME_RANGE_REGEX = re.compile(
    r"(?P<start>(?:(?:[01]?\d|2[0-3]):[0-5]\d(?::[0-5]\d)?|\b(?:[01]\d|2[0-3])[0-5]\d\b|\b(?:[1-9]|1[0-2])(?::[0-5]\d)?\s*(?:AM|PM|am|pm)\b|\b(?:[01]?\d|2[0-3])\s*(?:AM|PM|am|pm)\b))"
    r"\s*(?:-|–|—|to|until|till|/)\s*"
    r"(?P<end>(?:(?:[01]?\d|2[0-3]):[0-5]\d(?::[0-5]\d)?|\b(?:[01]\d|2[0-3])[0-5]\d\b|\b(?:[1-9]|1[0-2])(?::[0-5]\d)?\s*(?:AM|PM|am|pm)\b|\b(?:[01]?\d|2[0-3])\s*(?:AM|PM|am|pm)\b))",
    re.IGNORECASE,
)

ROOM_REGEX = re.compile(
    r"(?:"
    r"\b(?:Room|Rm|Lab|Hall|LT|CL|Classroom|Venue|Location|Auditorium)\s*[-:#]?\s*[A-Za-z0-9\s\-]+|"
    r"\b(?:CS|EE|SE|AI|IT|DLD|Data|Networks?|Software|Hardware|Physics|Chem|Cyber)\s+(?:Lab|Room|Hall)(?:\s*[0-9A-Za-z\-]+)?\b|"
    r"\b[A-F]\s*[-–]\s*\d{2,4}[A-Za-z]?\b|"
    r"\([A-Za-z0-9\s\-–:]{2,20}\)"
    r")",
    re.IGNORECASE,
)

TEACHER_REGEX = re.compile(
    r"\b(?:Dr|Prof|Professor|Mr|Ms|Mrs|Engr|Engineer|Sir|Madam|Lecturer|Instructor)\.?\s+[A-Za-z][A-Za-z\s.\']{1,30}[A-Za-z]\b",
    re.IGNORECASE,
)


def _to_24h(val: str) -> Optional[str]:
    if not val:
        return None
    cleaned = re.sub(r"\s+", "", str(val).upper()).replace(".", ":").strip(" ()[]{}hrsHRS")
    if re.fullmatch(r"^\d{4}$", cleaned):
        h = int(cleaned[:2])
        m = int(cleaned[2:])
        if 0 <= h < 24 and 0 <= m < 60:
            return f"{h:02d}:{m:02d}"
    for fmt in ["%I:%M:%S%p", "%I:%M%p", "%I%p", "%H:%M:%S", "%H:%M", "%H"]:
        try:
            return datetime.strptime(cleaned, fmt).strftime("%H:%M")
        except ValueError:
            continue
    match = re.match(r"^(\d{1,2}):(\d{2})(?::\d{2})?$", cleaned)
    if match:
        h = int(match.group(1))
        m = int(match.group(2))
        if 0 <= h < 24 and 0 <= m < 60:
            return f"{h:02d}:{m:02d}"
    match_single = re.match(r"^(\d{1,2})$", cleaned)
    if match_single:
        h = int(match_single.group(1))
        if 0 <= h < 24:
            return f"{h:02d}:00"
    return None


def _find_day_in_text(txt: str) -> Optional[int]:
    if not txt:
        return None
    txt_clean = re.sub(r"[^a-zA-Z]", " ", txt.lower())
    for word in txt_clean.split():
        if word in WEEKDAY_NAME_TO_INT:
            return WEEKDAY_NAME_TO_INT[word]
    for d_name, d_int in WEEKDAY_NAME_TO_INT.items():
        if d_name in txt.lower():
            return d_int
    return None


def _extract_cell_details(cell_text: str) -> tuple[str, str, Optional[str]]:
    """
    Extracts (subject, room, teacher) from a cell text blob.
    Mandatory details: subject name and class/room location (defaults to 'Main Campus' if unstated).
    Teacher/instructor is optional.
    """
    lines = [line.strip() for line in cell_text.split("\n") if line.strip()]
    if not lines:
        return "", "Main Campus", None

    room = None
    teacher = None
    subject_parts = []

    for line in lines:
        r_match = ROOM_REGEX.search(line)
        t_match = TEACHER_REGEX.search(line)

        if r_match and not room:
            raw_room = r_match.group(0).strip(" ()[]{}")
            if not TEACHER_REGEX.search(raw_room) and not TIME_RANGE_REGEX.search(raw_room):
                room = raw_room

        if t_match and not teacher:
            teacher = t_match.group(0).strip()

        # Clean subject part by stripping room, teacher, times, and brackets
        clean_l = ROOM_REGEX.sub("", line)
        clean_l = TEACHER_REGEX.sub("", clean_l)
        clean_l = TIME_RANGE_REGEX.sub("", clean_l)
        clean_l = re.sub(r"[\(\)\[\]\{\}]", " ", clean_l)
        clean_l = re.sub(r"\b(?:Venue|Room|Location|Instructor|Teacher|Course|Subject)\s*[:\-–]?", "", clean_l, flags=re.IGNORECASE)
        clean_l = re.sub(r"\s+", " ", clean_l).strip(" -–:;,|")
        if clean_l and len(clean_l) >= 2 and not re.fullmatch(r"[\d\s\-–:]+", clean_l):
            subject_parts.append(clean_l)

    subject = " ".join(subject_parts).strip() if subject_parts else lines[0]
    subject = re.sub(r"\s+", " ", subject).strip(" -–:;,|")

    # If room wasn't found line-by-line, try matching within the entire cell
    if not room:
        full_r_match = ROOM_REGEX.search(cell_text)
        if full_r_match:
            raw_room = full_r_match.group(0).strip(" ()[]{}")
            if not TEACHER_REGEX.search(raw_room) and not TIME_RANGE_REGEX.search(raw_room):
                room = raw_room

    if not room:
        room = "Main Campus"

    return subject, room, teacher


def _timetable_rows(tables: list, text: str = "") -> list:
    """
    Extracts weekly timetable classes from portal DOM tables or text.
    Handles grid layouts (Days across headers or rows, time slots on the other axis),
    list-based timetable rows, and multi-line text block fallbacks.
    """
    results = []
    seen = set()

    for table in tables:
        if not table or len(table) < 2:
            continue

        # Look for the actual header row in the first 3 rows
        header_idx = -1
        header_row = []
        day_cols = {}
        time_cols = {}

        for r_i in range(min(3, len(table))):
            row_items = table[r_i]
            if len(row_items) < 2:
                continue
            h_candidate = [str(c).strip().lower() for c in row_items]
            d_found = {}
            t_found = {}
            for c_idx, h in enumerate(h_candidate):
                d_val = _find_day_in_text(h)
                if d_val is not None:
                    d_found[c_idx] = d_val
                tm = TIME_RANGE_REGEX.search(h)
                if tm:
                    st = _to_24h(tm.group("start"))
                    et = _to_24h(tm.group("end"))
                    if st and et and et > st:
                        t_found[c_idx] = (st, et)

            if len(d_found) >= 2:
                header_idx = r_i
                header_row = h_candidate
                day_cols = d_found
                break
            elif len(t_found) >= 2:
                header_idx = r_i
                header_row = h_candidate
                time_cols = t_found
                break
            elif any(re.search(rf"\b{re.escape(k)}\b", " ".join(h_candidate)) for k in ["day", "weekday", "slot", "slots", "timing", "time", "course", "subject"]):
                header_idx = r_i
                header_row = h_candidate

        if header_idx == -1:
            header_idx = 0
            header_row = [str(c).strip().lower() for c in table[0]]

        # Layout A: Days across Column Headers (e.g. ['Sr#', 'Subject Name', 'Faculty Name', 'Monday', 'Tuesday', ...])
        if len(day_cols) >= 2:
            subj_col = -1
            teacher_col = -1
            for idx, h in enumerate(header_row):
                if any(k in h for k in ["subject", "course", "paper", "title", "module"]):
                    subj_col = idx
                elif any(k in h for k in ["faculty", "teacher", "instructor", "lecturer", "staff"]):
                    teacher_col = idx

            for row in table[header_idx + 1:]:
                if not row:
                    continue

                # Pattern A1: Times in column 0 or 1, and subjects inside day cells
                first_cell = str(row[0]).strip()
                t_match = TIME_RANGE_REGEX.search(first_cell)
                if not t_match and len(row) > 1:
                    t_match = TIME_RANGE_REGEX.search(str(row[1]).strip())

                if t_match:
                    st = _to_24h(t_match.group("start"))
                    et = _to_24h(t_match.group("end"))
                    if st and et and et > st:
                        for c_idx, weekday in day_cols.items():
                            if c_idx < len(row):
                                cell_txt = str(row[c_idx]).strip()
                                if not cell_txt or len(cell_txt) < 3 or cell_txt.lower() in ["nil", "none", "off", "break", "recess", "lunch", "-"]:
                                    continue
                                subj, room, teacher = _extract_cell_details(cell_txt)
                                if subj and len(subj) >= 2:
                                    key = f"{subj.lower()}|{weekday}|{st}|{et}"
                                    if key not in seen:
                                        seen.add(key)
                                        results.append({
                                            "subject": subj,
                                            "weekday": weekday,
                                            "start_time": st,
                                            "end_time": et,
                                            "room": room,
                                            "teacher": teacher,
                                        })
                    continue

                # Pattern A2: Subject & Teacher in row, Time ranges inside day cells (Air University / ASP.NET format)
                row_subj_raw = ""
                if subj_col != -1 and subj_col < len(row):
                    row_subj_raw = str(row[subj_col]).strip()
                elif len(row) >= 2 and not TIME_RANGE_REGEX.search(str(row[1])):
                    row_subj_raw = str(row[1]).strip()

                if not row_subj_raw or len(row_subj_raw) < 2 or row_subj_raw.lower() in ["nil", "none", "off", "total"]:
                    continue

                # Clean subject name: e.g. "F-26-Deep Learning-772" -> "Deep Learning"
                clean_subj = re.sub(r"^[A-Z]{1,2}-\d{2,4}-", "", row_subj_raw)
                clean_subj = re.sub(r"-\d{2,6}$", "", clean_subj).strip()
                if not clean_subj:
                    clean_subj = row_subj_raw

                row_teacher = None
                if teacher_col != -1 and teacher_col < len(row):
                    row_teacher = str(row[teacher_col]).strip() or None

                for c_idx, weekday in day_cols.items():
                    if c_idx < len(row):
                        cell_txt = str(row[c_idx]).strip()
                        if not cell_txt or cell_txt.lower() in ["nil", "none", "-", "off", ""]:
                            continue

                        # Find all time ranges in this cell
                        for tm in TIME_RANGE_REGEX.finditer(cell_txt):
                            st = _to_24h(tm.group("start"))
                            et = _to_24h(tm.group("end"))
                            if st and et and et > st:
                                cell_subj, cell_room, cell_teacher = _extract_cell_details(cell_txt)
                                room = cell_room if cell_room and cell_room != "Main Campus" else "Main Campus"
                                teacher = row_teacher or cell_teacher
                                key = f"{clean_subj.lower()}|{weekday}|{st}|{et}"
                                if key not in seen:
                                    seen.add(key)
                                    results.append({
                                        "subject": clean_subj,
                                        "weekday": weekday,
                                        "start_time": st,
                                        "end_time": et,
                                        "room": room,
                                        "teacher": teacher,
                                    })

        # Layout B: Time slots in Column Headers, Days in Rows
        elif len(time_cols) >= 2:
            current_day = None
            for row in table[header_idx + 1:]:
                if not row:
                    continue
                first_cell = str(row[0]).strip()
                d_val = _find_day_in_text(first_cell)
                if d_val is not None:
                    current_day = d_val
                if current_day is None:
                    continue

                for c_idx, (st, et) in time_cols.items():
                    if c_idx < len(row):
                        cell_txt = str(row[c_idx]).strip()
                        if not cell_txt or len(cell_txt) < 3 or cell_txt.lower() in ["nil", "none", "off", "break", "recess", "lunch", "-"]:
                            continue
                        subj, room, teacher = _extract_cell_details(cell_txt)
                        if subj and len(subj) >= 2:
                            key = f"{subj.lower()}|{current_day}|{st}|{et}"
                            if key not in seen:
                                seen.add(key)
                                results.append({
                                    "subject": subj,
                                    "weekday": current_day,
                                    "start_time": st,
                                    "end_time": et,
                                    "room": room,
                                    "teacher": teacher,
                                })

        # Layout C: Columnar / List-based Table (Day, Time, Course, Room, Teacher)
        else:
            day_col = -1
            time_col = -1
            subj_col = -1
            room_col = -1
            teacher_col = -1

            for idx, h in enumerate(header_row):
                if any(k in h for k in ["day", "weekday", "days"]):
                    day_col = idx
                elif any(k in h for k in ["time", "timing", "timings", "slot", "slots", "duration", "period", "hours"]):
                    time_col = idx
                elif any(k in h for k in ["subject", "course", "title", "paper", "class", "module"]) and not any(k in h for k in ["room", "teacher", "instructor", "faculty"]):
                    subj_col = idx
                elif any(k in h for k in ["room", "venue", "hall", "lab", "location", "place"]):
                    room_col = idx
                elif any(k in h for k in ["teacher", "instructor", "faculty", "lecturer", "staff", "professor"]):
                    teacher_col = idx

            current_row_day = None
            for row in table[header_idx + 1:]:
                cells = [str(c).strip() for c in row]
                if not any(cells):
                    continue

                # Check if entire row is a day section header (e.g. ['--- Monday ---'] or ['Monday'])
                combined_row_text = " ".join(cells)
                row_day = _find_day_in_text(combined_row_text)
                if len(cells) <= 2 and row_day is not None:
                    current_row_day = row_day
                    continue

                if day_col != -1 and day_col < len(cells):
                    cell_day = _find_day_in_text(cells[day_col])
                    if cell_day is not None:
                        current_row_day = cell_day

                weekday = current_row_day
                if weekday is None:
                    for c_val in cells:
                        d_cand = _find_day_in_text(c_val)
                        if d_cand is not None:
                            weekday = d_cand
                            break

                if weekday is None:
                    continue

                st, et = "09:00", "10:30"
                time_found = False
                if time_col != -1 and time_col < len(cells):
                    tm = TIME_RANGE_REGEX.search(cells[time_col])
                    if tm:
                        st_c = _to_24h(tm.group("start"))
                        et_c = _to_24h(tm.group("end"))
                        if st_c and et_c and et_c > st_c:
                            st, et = st_c, et_c
                            time_found = True

                if not time_found:
                    for c_val in cells:
                        tm = TIME_RANGE_REGEX.search(c_val)
                        if tm:
                            st_c = _to_24h(tm.group("start"))
                            et_c = _to_24h(tm.group("end"))
                            if st_c and et_c and et_c > st_c:
                                st, et = st_c, et_c
                                time_found = True
                                break

                subj = cells[subj_col] if (subj_col != -1 and subj_col < len(cells)) else ""
                room_val = cells[room_col] if (room_col != -1 and room_col < len(cells)) else None
                teacher_val = cells[teacher_col] if (teacher_col != -1 and teacher_col < len(cells)) else None

                if not subj or len(subj) < 2:
                    for c_idx, c_val in enumerate(cells):
                        if c_idx not in [day_col, time_col, room_col, teacher_col] and len(c_val) > len(subj):
                            if not TIME_RANGE_REGEX.search(c_val) and _find_day_in_text(c_val) is None:
                                subj = c_val

                if subj:
                    clean_subj, r_cand, t_cand = _extract_cell_details(subj)
                    subj = clean_subj
                    room = room_val if (room_val and room_val != "Main Campus") else r_cand
                    teacher = teacher_val or t_cand
                else:
                    room = room_val or "Main Campus"
                    teacher = teacher_val

                if not subj or len(subj) < 2 or subj.lower() in ["nil", "none", "off", "break"]:
                    continue

                key = f"{subj.lower()}|{weekday}|{st}|{et}"
                if key not in seen:
                    seen.add(key)
                    results.append({
                        "subject": subj,
                        "weekday": weekday,
                        "start_time": st,
                        "end_time": et,
                        "room": room or "Main Campus",
                        "teacher": teacher,
                    })

    # Layout D: Multi-line and text-based parser fallback
    if not results and text:
        current_day = None
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        i = 0
        while i < len(lines):
            line = lines[i]
            d_cand = _find_day_in_text(line)
            if d_cand is not None and (len(line) < 30 or re.match(r"^(?:mon|tue|wed|thu|fri|sat|sun)[a-z]*[:\s-]*$", line, re.I)):
                current_day = d_cand
                i += 1
                continue

            tm = TIME_RANGE_REGEX.search(line)
            if tm:
                st = _to_24h(tm.group("start"))
                et = _to_24h(tm.group("end"))
                line_day = _find_day_in_text(line) or current_day
                if st and et and et > st and line_day is not None:
                    clean_line = TIME_RANGE_REGEX.sub("", line)
                    clean_line = re.sub(r"^(?:mon|tue|wed|thu|fri|sat|sun)[a-z]*[:\s-]*", "", clean_line, flags=re.I).strip()
                    subj, room, teacher = _extract_cell_details(clean_line)

                    if not subj or len(subj) < 2:
                        j = i + 1
                        gathered = []
                        while j < len(lines) and j <= i + 3:
                            next_line = lines[j]
                            if TIME_RANGE_REGEX.search(next_line) or _find_day_in_text(next_line) is not None:
                                break
                            gathered.append(next_line)
                            j += 1
                        if gathered:
                            subj, room, teacher = _extract_cell_details("\n".join(gathered))
                            i = j - 1

                    if subj and len(subj) >= 2 and subj.lower() not in ["nil", "none", "off", "break"]:
                        key = f"{subj.lower()}|{line_day}|{st}|{et}"
                        if key not in seen:
                            seen.add(key)
                            results.append({
                                "subject": subj,
                                "weekday": line_day,
                                "start_time": st,
                                "end_time": et,
                                "room": room or "Main Campus",
                                "teacher": teacher,
                            })
            i += 1

    return results


def _sync_timetable_to_schedules(db: Session, timetable_entries: list, semester_name: Optional[str] = None):
    """
    Upserts timetable classes into TimetableEntry and generates ClassSchedule entries
    for the upcoming 30 days so dashboard counters and schedule views populate immediately.
    """
    from datetime import date, datetime, timedelta, time as dtime
    from app.db.models import ClassSchedule, TimetableEntry
    from app.db.repositories import CourseRepository

    today = datetime.now(timezone.utc).date()
    course_repo = CourseRepository(db)

    # Check for semester_start setting
    sem_start_setting = _setting(db, "semester_start_date")
    sem_start_dt = None
    if sem_start_setting and sem_start_setting.value:
        try:
            sem_start_dt = datetime.fromisoformat(sem_start_setting.value.replace("Z", "+00:00"))
        except Exception:
            pass

    for item in timetable_entries:
        subj = item["subject"].strip()
        weekday = item["weekday"]
        st = item["start_time"]
        et = item["end_time"]
        room = item.get("room") or "Main Campus"
        teacher = item.get("teacher")

        # 1. Upsert TimetableEntry
        identity = f"{subj.lower()}|{weekday}|{st}|{et}"
        tt_ext_id = "portal-tt:" + sha256(identity.encode("utf-8")).hexdigest()[:32]
        tt_entry = db.query(TimetableEntry).filter(TimetableEntry.external_id == tt_ext_id).first()
        if not tt_entry:
            tt_entry = TimetableEntry(
                external_id=tt_ext_id,
                subject=subj,
                weekday=weekday,
                start_time=st,
                end_time=et,
                room=room,
                teacher=teacher,
                semester_name=semester_name,
                semester_start=sem_start_dt,
            )
            db.add(tt_entry)
        else:
            tt_entry.subject = subj
            tt_entry.room = room or tt_entry.room
            tt_entry.teacher = teacher or tt_entry.teacher
            tt_entry.semester_name = semester_name or tt_entry.semester_name
            if sem_start_dt and not tt_entry.semester_start:
                tt_entry.semester_start = sem_start_dt

        # 2. Link Course
        course_ext_id = "portal-course:" + sha256(subj.lower().encode("utf-8")).hexdigest()[:32]
        course = course_repo.create_or_update({
            "external_id": course_ext_id,
            "name": subj,
            "room": room,
            "teacher_name": teacher,
            "course_state": "ACTIVE",
        })

        # 3. Generate ClassSchedule for upcoming 30 days
        try:
            s_h, s_m = map(int, st.split(":"))
            e_h, e_m = map(int, et.split(":"))
            for day_offset in range(30):
                target_date = today + timedelta(days=day_offset)
                if target_date.weekday() == weekday:
                    sch_ext_id = f"portal-sch:{course.id}:{target_date.isoformat()}:{st}"
                    st_dt = datetime.combine(target_date, dtime(s_h, s_m)).replace(tzinfo=timezone.utc)
                    et_dt = datetime.combine(target_date, dtime(e_h, e_m)).replace(tzinfo=timezone.utc)

                    existing_sch = db.query(ClassSchedule).filter(ClassSchedule.external_id == sch_ext_id).first()
                    if not existing_sch:
                        new_sch = ClassSchedule(
                            external_id=sch_ext_id,
                            course_id=course.id,
                            subject=subj,
                            date=st_dt,
                            start_time=st_dt,
                            end_time=et_dt,
                            teacher=teacher,
                            room=room,
                            status="scheduled",
                        )
                        db.add(new_sch)
                    else:
                        existing_sch.teacher = teacher or existing_sch.teacher
                        existing_sch.room = room or existing_sch.room
        except Exception:
            pass

    db.flush()


def _ingest_report_data(db: Session, report: dict, source_url: str, user_id: str = "dev_student_user"):
    clean_link = (source_url or "").strip()
    if "accounts.google.com" in clean_link or len(clean_link) > 490:
        clean_link = clean_link[:490]
        if "accounts.google.com" in clean_link:
            clean_link = "https://portals.au.edu.pk/students/attendance.aspx"

    attendance_rows = _attendance_rows(report.get("tables", []), report.get("text", ""))
    timetable_rows = _timetable_rows(report.get("tables", []), report.get("text", ""))
    summary = _report_summary(report.get("tables", []), report.get("text", ""))
    captured_at = datetime.now(timezone.utc).isoformat()
    summary.update({"captured_at": captured_at, "source_url": clean_link, "page_title": report.get("title")})

    # Save attendance records
    for row in attendance_rows:
        external_id = "portal-attendance:" + sha256(row["subject"].strip().lower().encode("utf-8")).hexdigest()
        course = CourseRepository(db).create_or_update({
            "external_id": external_id,
            "name": row["subject"],
            "course_state": "ACTIVE",
            "alternate_link": clean_link,
        })
        AttendanceRecordRepository(db).create_or_update({
            "external_id": external_id,
            "course_id": course.id,
            "subject": row["subject"],
            "attended": row["attended"],
            "total": row["total"],
            "percentage": row["percentage"],
            "last_updated": datetime.now(timezone.utc),
        })

    # Save timetable classes & schedules
    if timetable_rows:
        _sync_timetable_to_schedules(db, timetable_rows, summary.get("semester_name"))

    stored = _portal_setting(db, user_id, "portal_academic_summary")
    if stored and stored.value:
        try:
            previous = json.loads(stored.value)
            for field in ("cgpa", "sgpa", "earned_credits", "semester_name", "semesters", "strategy_summary"):
                if summary.get(field) is None and previous.get(field) is not None:
                    summary[field] = previous.get(field)
        except Exception:
            pass
    if not stored:
        stored = Setting(key=_user_setting_key(user_id, "portal_academic_summary"), description="Latest university portal GPA and semester summary")
        db.add(stored)
    stored.value = json.dumps(summary)

    _set_portal_setting(db, user_id, "portal_last_synced_at", captured_at, "Last successful portal sync timestamp")
    _set_portal_setting(db, user_id, "portal_session_status", "ACTIVE", "Portal login session status")

    is_timetable_page = any(k in (clean_link.lower() + " " + str(report.get("title", "")).lower()) for k in ["timetable", "schedule", "routine"])
    if is_timetable_page and clean_link and "accounts.google.com" not in clean_link:
        _set_portal_setting(db, user_id, "portal_timetable_url", clean_link, "Discovered timetable report URL")
    elif attendance_rows and clean_link and "accounts.google.com" not in clean_link:
        _set_portal_setting(db, user_id, "portal_attendance_url", clean_link, "Discovered attendance report URL")

    db.commit()
    return attendance_rows, timetable_rows, summary


DOM_EXTRACTION_SCRIPT = """() => {
  const getTablesFromDoc = (d) => {
    if (!d) return [];
    let tbls = [];
    try {
      tbls = Array.from(d.querySelectorAll('table')).map(table =>
        Array.from(table.querySelectorAll('tr')).map(row =>
          Array.from(row.querySelectorAll('th,td')).map(cell => (cell.innerText || '').trim())
        )
      );
      const iframes = d.querySelectorAll('iframe, frame');
      for (const ifr of iframes) {
        try {
          const frameDoc = ifr.contentDocument || (ifr.contentWindow && ifr.contentWindow.document);
          if (frameDoc) {
            tbls = tbls.concat(getTablesFromDoc(frameDoc));
          }
        } catch (e) {}
      }
    } catch (e) {}
    return tbls;
  };

  const getTextFromDoc = (d) => {
    if (!d) return '';
    let txt = (d.body?.innerText || '');
    try {
      const iframes = d.querySelectorAll('iframe, frame');
      for (const ifr of iframes) {
        try {
          const frameDoc = ifr.contentDocument || (ifr.contentWindow && ifr.contentWindow.document);
          if (frameDoc) {
            txt += '\\n' + getTextFromDoc(frameDoc);
          }
        } catch (e) {}
      }
    } catch (e) {}
    return txt.slice(0, 250000);
  };

  return {
    title: document.title,
    url: location.href,
    text: getTextFromDoc(document),
    tables: getTablesFromDoc(document)
  };
}"""


def _scrape_report_thread(target_urls: str | list[str], profile_dir: Path, user_id: str):
    """Reuse one authenticated user profile and one browser startup for all portal pages."""
    from playwright.sync_api import sync_playwright

    if isinstance(target_urls, str):
        target_urls = [target_urls]
    target_urls = list(dict.fromkeys(url for url in target_urls if url))
    if not target_urls:
        return {"status": "error", "error": "No portal pages are configured."}

    with sync_playwright() as p:
        browser = None
        context = None
        owns_context = False
        try:
            if _cdp_is_available(user_id):
                browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{_cdp_port(user_id)}", timeout=10000)
                context = browser.contexts[0] if browser.contexts else None
        except Exception as error:
            logger.warning(f"Could not attach to the open portal browser for {user_id}: {error}")

        if context is None:
            last_error = None
            for channel_opt in ["chrome", "msedge", None]:
                try:
                    kwargs = {"user_data_dir": str(profile_dir), "headless": True, "args": ["--no-sandbox"]}
                    if channel_opt:
                        kwargs["channel"] = channel_opt
                    context = p.chromium.launch_persistent_context(**kwargs)
                    owns_context = True
                    break
                except Exception as error:
                    last_error = error
            if context is None:
                return {"status": "error", "error": f"Could not reopen the saved portal session. Close any Uniflow sign-in window, then retry. ({last_error})"}

        reports = []
        try:
            page = context.pages[0] if context.pages else context.new_page()
            # Discover the portal's own academic links after authentication; no report-page capture step.
            page.goto(target_urls[0], wait_until="domcontentloaded", timeout=25000)
            page.wait_for_timeout(800)
            portal_host = (urlsplit(target_urls[0]).hostname or "").lower()
            if _portal_page_needs_login(page, portal_host):
                return {"status": "session_expired", "current_url": page.url, "detail": "University sign-in is required. Reconnect once to continue automatic sync."}

            discovered = page.evaluate("""() => Array.from(document.querySelectorAll('a[href]'))
              .map(a => ({href: a.href, text: (a.innerText || a.textContent || '').trim()}))
              .filter(a => /attendance|timetable|time table|schedule|grade|transcript|result|academic/i.test(a.href + ' ' + a.text))
              .map(a => a.href)""")
            urls = list(target_urls)
            if portal_host == "portals.au.edu.pk":
                for path in ("Attendance.aspx", "TimeTable.aspx"):
                    candidate = urlsplit(target_urls[0])
                    preset_url = f"{candidate.scheme}://{candidate.netloc}/students/{path}"
                    if preset_url not in urls:
                        urls.append(preset_url)
            for link in discovered:
                parsed = urlsplit(link)
                if parsed.scheme in ("http", "https") and (parsed.hostname or "").lower() == portal_host and link not in urls:
                    urls.append(link)

            for url in urls:
                try:
                    if page.url != url:
                        page.goto(url, wait_until="domcontentloaded", timeout=20000)
                        page.wait_for_timeout(600)
                    current_url = page.url or url
                    if _portal_page_needs_login(page, portal_host):
                        return {"status": "session_expired", "current_url": current_url, "detail": "University sign-in expired. Reconnect once to resume automatic sync."}
                    report = page.evaluate(DOM_EXTRACTION_SCRIPT)
                    report["discovered_urls"] = urls
                    reports.append({"report": report, "current_url": current_url})
                except Exception as error:
                    reports.append({"error": str(error), "current_url": url})

            if not any(item.get("report") for item in reports):
                return {"status": "error", "error": "The portal pages could not be read. Check the connection and try again.", "reports": reports}
            return {"status": "success", "reports": reports, "current_url": reports[0].get("current_url")}
        finally:
            if owns_context and context:
                context.close()


def _portal_page_needs_login(page, portal_host: str) -> bool:
    """Detect login/SSO pages instead of treating every same-host page as signed in."""
    current_url = page.url or ""
    parsed = urlsplit(current_url)
    current_host = (parsed.hostname or "").lower()
    if current_host != portal_host or re.search(r"/(login|signin|sign-in|auth)(/|$)", parsed.path, re.I):
        return True
    try:
        if page.locator("input[type='password']:visible").count() > 0:
            return True
        text = (page.locator("body").inner_text(timeout=2500) or "").lower()
    except Exception:
        return True
    return any(phrase in text for phrase in (
        "sign in with google", "please log in", "please login", "student login",
        "forgot password", "enter your password", "invalid username or password",
        "verification code", "one-time password", "two-factor", "verify it's you",
    ))


def _portal_browser_authenticated(user_id: str, portal_url: str) -> bool:
    """Check the live sign-in window without changing its current page."""
    from playwright.sync_api import sync_playwright
    portal_host = (urlsplit(portal_url).hostname or "").lower()
    if not _cdp_is_available(user_id):
        return False
    try:
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{_cdp_port(user_id)}", timeout=5000)
            pages = [page for context in browser.contexts for page in context.pages]
            for page in pages:
                if not _portal_page_needs_login(page, portal_host):
                    return True
    except Exception:
        return False
    return False


@router.get("/connection-status", response_model=dict)
async def portal_connection_status(db: Session = Depends(get_db), user: dict = Depends(require_current_user)):
    uid = _user_id(user)
    portal_url = _portal_setting(db, uid, "university_portal_url")
    if not portal_url or not portal_url.value:
        raise HTTPException(status_code=409, detail="Save your university portal address first.")
    authenticated = await asyncio.to_thread(_portal_browser_authenticated, uid, portal_url.value)
    return {"status": "authenticated" if authenticated else "waiting"}


@router.post("/capture", response_model=dict)
async def capture_portal_report(db: Session = Depends(get_db), user: dict = Depends(require_current_user)):
    uid = _user_id(user)
    result = await asyncio.to_thread(_sync_portal_for_user, uid)
    if result.get("status") == "session_expired":
        return {"session_expired": True, "message": result.get("detail"), "status": "reconnect_required"}
    if result.get("status") == "error":
        raise HTTPException(status_code=502, detail=result.get("error", "Could not sync the university portal."))
    return result


def _sync_portal_for_user(uid: str):
    lock = _sync_locks.setdefault(uid, threading.Lock())
    if not lock.acquire(blocking=False):
        return {"status": "already_running", "message": "A portal sync is already running."}
    db = SessionLocal()
    lock_id = int(sha256(f"portal-sync:{uid}".encode("utf-8")).hexdigest()[:15], 16)
    distributed_lock = False
    lock_connection = None
    try:
        if db.bind and db.bind.dialect.name == "postgresql":
            try:
                lock_connection = db.bind.connect()
                distributed_lock = bool(lock_connection.execute(text("SELECT pg_try_advisory_lock(:lock_id)"), {"lock_id": lock_id}).scalar())
            except Exception:
                # Local lock remains in force if the database doesn't support advisory locks.
                if lock_connection:
                    lock_connection.close()
                    lock_connection = None
            if not distributed_lock:
                return {"status": "already_running", "message": "A portal sync is already running."}
        base = _portal_setting(db, uid, "university_portal_url")
        if not base or not base.value:
            return {"status": "error", "error": "Save your university portal address before connecting."}
        target_urls = [base.value]
        for key in ("portal_attendance_url", "portal_timetable_url", "portal_grades_url"):
            item = _portal_setting(db, uid, key)
            if item and item.value and item.value not in target_urls:
                target_urls.append(item.value)

        result = _scrape_report_thread(target_urls, _profile_dir(uid), uid)
        if result.get("status") == "session_expired":
            _set_portal_setting(db, uid, "portal_session_status", "REAUTH_REQUIRED", "Portal sign-in needs renewal")
            db.commit()
            return result
        if result.get("status") != "success":
            _set_portal_setting(db, uid, "portal_session_status", "ERROR", "Last portal sync failed")
            db.commit()
            return {"status": "error", "error": result.get("error", "No portal pages could be read."), "failed_pages": result.get("reports", [])}

        attendance, timetable = [], []
        summaries, pages, errors = [], [], []
        for page in result.get("reports", []):
            if page.get("error"):
                errors.append({"url": page.get("current_url"), "error": page["error"]})
                continue
            report = page.get("report") or {}
            current_url = page.get("current_url") or base.value
            att, tt, summary = _ingest_report_data(db, report, current_url, uid)
            attendance.extend(att)
            timetable.extend(tt)
            if summary:
                summaries.append(summary)
            pages.append({"url": current_url, "title": report.get("title"), "tables": len(report.get("tables", []))})
            for link in report.get("discovered_urls", []):
                label = link.lower()
                if "attendance" in label:
                    _set_portal_setting(db, uid, "portal_attendance_url", link, "Automatically discovered attendance page")
                if "timetable" in label or "time%20table" in label or "schedule" in label:
                    _set_portal_setting(db, uid, "portal_timetable_url", link, "Automatically discovered timetable page")
                if any(word in label for word in ("grade", "result", "transcript")):
                    _set_portal_setting(db, uid, "portal_grades_url", link, "Automatically discovered grades page")

        has_data = any(page.get("tables", 0) for page in pages) or attendance or timetable or any(
            any(summary.get(key) is not None for key in ("cgpa", "sgpa", "earned_credits", "semesters")) for summary in summaries
        )
        if not pages or not has_data:
            _set_portal_setting(db, uid, "portal_session_status", "ERROR", "No academic data page was readable")
            db.commit()
            return {"status": "error", "error": "The portal opened, but no academic records were found. Check that your student account is fully signed in and the portal pages are available.", "failed_pages": errors}

        # Choose the richest summary so a sparse dashboard page cannot erase GPA data.
        summary = max(summaries, key=lambda item: sum(item.get(k) is not None for k in ("cgpa", "sgpa", "earned_credits", "semester_name", "semesters")), default={})
        _set_portal_setting(db, uid, "portal_session_status", "ACTIVE", "Portal session is usable")
        db.commit()
        return {"status": "partial" if errors else "success", "attendance": attendance, "timetable": timetable,
                "summary": summary, "pages_synced": pages, "failed_pages": errors,
                "last_synced_at": datetime.now(timezone.utc).isoformat(), "message": f"Synced {len(pages)} portal pages."}
    finally:
        if distributed_lock:
            try:
                lock_connection.execute(text("SELECT pg_advisory_unlock(:lock_id)"), {"lock_id": lock_id})
            except Exception:
                pass
        if lock_connection:
            lock_connection.close()
        db.close()
        lock.release()


@router.post("/sync-headless", response_model=dict)
async def sync_portal_headless(db: Session = Depends(get_db), user: dict = Depends(require_current_user)):
    result = await asyncio.to_thread(_sync_portal_for_user, _user_id(user))
    if result.get("status") == "error":
        raise HTTPException(status_code=502, detail=result.get("error", "Portal sync failed."))
    return result


def _run_portal_sync_job(uid: str, job_id: str):
    _persist_sync_job(uid, job_id, {"status": "running", "started_at": datetime.now(timezone.utc).isoformat()})
    try:
        result = _sync_portal_for_user(uid)
        _persist_sync_job(uid, job_id, {**result, "finished_at": datetime.now(timezone.utc).isoformat()})
    except Exception as error:
        _persist_sync_job(uid, job_id, {"status": "error", "error": str(error), "finished_at": datetime.now(timezone.utc).isoformat()})
    finally:
        with _sync_jobs_lock:
            if _active_sync_jobs.get(uid) == job_id:
                _active_sync_jobs.pop(uid, None)


def _persist_sync_job(uid: str, job_id: str, result: dict):
    db = SessionLocal()
    try:
        _set_portal_setting(db, uid, f"sync_job_{job_id}", json.dumps(result), "Portal sync job status")
        db.commit()
    finally:
        db.close()


@router.post("/sync", response_model=dict)
def queue_portal_sync(background_tasks: BackgroundTasks, db: Session = Depends(get_db), user: dict = Depends(require_current_user)):
    uid = _user_id(user)
    with _sync_jobs_lock:
        active_id = _active_sync_jobs.get(uid)
        if active_id and _sync_jobs.get(active_id, {}).get("status") in ("queued", "running"):
            return {"status": "queued", "job_id": active_id, "message": "Your portal sync is already in progress."}
        job_id = sha256(f"{uid}:{time.time_ns()}".encode()).hexdigest()[:20]
        queued = {"status": "queued", "created_at": datetime.now(timezone.utc).isoformat()}
        _sync_jobs[job_id] = queued
        _active_sync_jobs[uid] = job_id
    _set_portal_setting(db, uid, f"sync_job_{job_id}", json.dumps(queued), "Portal sync job status")
    db.commit()
    background_tasks.add_task(_run_portal_sync_job, uid, job_id)
    return {"status": "queued", "job_id": job_id, "message": "Sync started. Your saved portal data remains available while it refreshes."}


@router.get("/sync/{job_id}", response_model=dict)
def get_portal_sync_status(job_id: str, db: Session = Depends(get_db), user: dict = Depends(require_current_user)):
    item = _portal_setting(db, _user_id(user), f"sync_job_{job_id}")
    if not item or not item.value:
        raise HTTPException(status_code=404, detail="Sync job was not found or has expired.")
    try:
        return json.loads(item.value)
    except Exception:
        raise HTTPException(status_code=500, detail="Sync status is unreadable.")


@router.post("/close", response_model=dict)
def close_portal_browser(user: dict = Depends(require_current_user)):
    uid = _user_id(user)
    process = _portal_processes.pop(uid, None)
    if process is not None:
        try:
            process.terminate()
        except Exception:
            pass
    return {"closed": True}
