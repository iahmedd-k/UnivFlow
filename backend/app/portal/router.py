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
import uuid
from datetime import datetime, timezone, timedelta
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlsplit, urljoin

from typing import Optional, Dict, Any, Tuple

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text, func
from sqlalchemy.orm import Session

from app.auth.clerk_auth import require_current_user
from app.core.redis import (
    UpstashRedisError,
    acquire_lock as acquire_redis_lock,
    invalidate_attendance_summary_cache,
    is_configured as is_redis_configured,
    release_lock as release_redis_lock,
)
from app.core.logging import logger
from app.db.database import get_db, SessionLocal
from app.db.models import Course, Setting, TimetableEntry, ClassSchedule, PortalSyncJob
from app.db.repositories import AttendanceRecordRepository, CourseRepository, ClassScheduleRepository
from app.db.repositories.portal import PortalSyncJobRepository

router = APIRouter(prefix="/portal", tags=["University portal"])

PORTAL_PROFILE_ROOT = Path(__file__).resolve().parent.parent.parent / "tmp" / "portal_browser_profiles"
PORTAL_PROFILE_ROOT.mkdir(parents=True, exist_ok=True)

_portal_processes: dict[str, Any] = {}
_sync_locks: dict[str, threading.Lock] = {}


class PortalUrlInput(BaseModel):
    url: str = Field(min_length=8, max_length=1000)
    attendance_url: str | None = Field(default=None, max_length=1000)
    timetable_url: str | None = Field(default=None, max_length=1000)
    login_email: str | None = Field(default=None, max_length=320)
    auth_method: str = Field(default="google", pattern="^(google|password|either)$")


class PortalCookieSyncRequest(BaseModel):
    cookies: str
    portal_url: Optional[str] = None



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
    # Allow private IP ranges (10.x, 172.16-31.x, 192.168.x) for on-premise university portals
    hostname = (parsed.hostname or "").lower()
    if hostname in ("localhost", "127.0.0.1", "::1", "0.0.0.0") or hostname.startswith("169.254."):
        raise HTTPException(status_code=422, detail="Loopback and link-local addresses are not permitted as portal URLs.")
    # Check for AWS/GCP/Azure metadata service endpoints
    if hostname in ("metadata.google.internal", "169.254.169.254", "metadata.azure.com", "metadata"):
        raise HTTPException(status_code=422, detail="Cloud metadata service addresses are not permitted as portal URLs.")
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
    item = _setting(db, _user_setting_key(user_id, key))
    if not item and user_id != "dev_student_user":
        item = _setting(db, _user_setting_key("dev_student_user", key))
    if not item:
        item = _setting(db, key)
    return item


def _set_portal_setting(db: Session, user_id: str, key: str, value: str, description: str = ""):
    item = _set_setting(db, _user_setting_key(user_id, key), value, description)
    if user_id != "dev_student_user":
        _set_setting(db, _user_setting_key("dev_student_user", key), value, description)
    return item


USER_CDP_PORT = 9222
UNIFLOW_CDP_PORT = 9222
UNIFLOW_SHARED_PROFILE = Path(__file__).resolve().parent.parent.parent / "tmp" / "claude_browser_profile"
UNIFLOW_SHARED_PROFILE.mkdir(parents=True, exist_ok=True)


def _profile_dir(user_id: str) -> Path:
    """Return the shared browser profile to allow Claude, Google, and Portal sessions to share one browser."""
    return UNIFLOW_SHARED_PROFILE


def _cdp_port(user_id: str) -> int:
    return USER_CDP_PORT


def _is_port_live(port: int, timeout: float = 0.4) -> bool:
    request = urllib.request.Request(f"http://127.0.0.1:{port}/json/version")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return bool(payload.get("webSocketDebuggerUrl"))
    except (OSError, ValueError, urllib.error.URLError):
        return False


def _find_active_browser_port(user_id: str = "") -> Optional[int]:
    """Check if Chrome is already active on port 9222."""
    if _is_port_live(USER_CDP_PORT):
        return USER_CDP_PORT
    return None


def _cdp_is_available(user_id: str, timeout: float = 0.4) -> bool:
    """Return true when any supported Chrome remote-debugging endpoint is live."""
    return _find_active_browser_port(user_id) is not None


def _cleanup_untrusted_tabs_port(port: int) -> None:
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/json")
        with urllib.request.urlopen(req, timeout=1.0) as resp:
            tabs = json.loads(resp.read().decode("utf-8"))
            for t in tabs:
                t_url = t.get("url", "")
                t_id = t.get("id")
                if t_id and (t_url.startswith("chrome://newtab") or t_url.startswith("chrome://new-tab-page")):
                    try:
                        urllib.request.urlopen(f"http://127.0.0.1:{port}/json/close/{t_id}", timeout=1.0)
                    except Exception:
                        pass
    except Exception:
        pass


def _cleanup_untrusted_tabs(user_id: str) -> None:
    port = _find_active_browser_port(user_id) or UNIFLOW_CDP_PORT
    _cleanup_untrusted_tabs_port(port)


def _wait_for_cdp(user_id: str, timeout: float = 10.0) -> bool:
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
    cookie_setting = _portal_setting(db, uid, "portal_session_cookies")

    profile = _profile_dir(uid)
    has_saved_session = profile.exists() and any(profile.iterdir())
    has_session_cookies = bool(cookie_setting and cookie_setting.value)

    status = "NOT_CONFIGURED"
    if session_status and session_status.value:
        status = session_status.value
    elif has_session_cookies or has_saved_session:
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
        "has_session_cookies": has_session_cookies,
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


def _parse_cookie_header(raw: str) -> dict[str, str]:
    if not raw or not isinstance(raw, str):
        return {}
    raw = raw.strip()
    if not raw:
        return {}

    # 1. If user pasted a cURL command, extract the cookie header parameter
    if "curl" in raw.lower() and ("--header" in raw.lower() or "-h" in raw.lower() or "-b" in raw.lower() or "--cookie" in raw.lower()):
        m = re.search(r'''(?:--header|-H|-b|--cookie)\s+['"](?:cookie:\s*)?([^'"]+)['"]''', raw, re.I)
        if m:
            raw = m.group(1).strip()

    # 2. Check if JSON (from browser extensions like Cookie-Editor or EditThisCookie)
    if (raw.startswith("{") and raw.endswith("}")) or (raw.startswith("[") and raw.endswith("]")):
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                return {str(k).strip(): str(v).strip() for k, v in data.items() if k and v}
            elif isinstance(data, list):
                res = {}
                for item in data:
                    if isinstance(item, dict):
                        name = item.get("name") or item.get("key")
                        value = item.get("value")
                        if name and value is not None:
                            res[str(name).strip()] = str(value).strip()
                if res:
                    return res
        except Exception:
            pass

    cookie_attribute_names = {
        "path", "domain", "expires", "max-age", "samesite", "httponly", "secure", "priority", "size"
    }
    cookies: dict[str, str] = {}

    # 3. Check for tab-separated rows copied directly from DevTools Application -> Cookies table
    # Format: Name \t Value \t Domain \t Path \t Expires ...
    lines = raw.splitlines()
    has_tabs = any("\t" in line for line in lines)
    if has_tabs:
        for line in lines:
            line = line.strip()
            if not line:
                continue
            cols = [c.strip() for c in line.split("\t")]
            if len(cols) >= 2:
                name, val = cols[0], cols[1]
                # Skip table header row
                if name.lower() in ("name", "cookie name", "cookiename") and val.lower() in ("value", "cookie value"):
                    continue
                if name.lower() not in cookie_attribute_names and name and val:
                    cookies[name] = val
        if cookies:
            return cookies

    # 4. Standard Cookie string parsing (semicolon or newline delimited)
    if raw.lower().startswith("cookie:"):
        raw = raw[7:].strip()

    parts = re.split(r"[;\r\n]+", raw)
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if part.lower().startswith("cookie:"):
            part = part[7:].strip()
        if "=" in part:
            key, val = part.split("=", 1)
            key = key.strip()
            val = val.strip().strip('"\'')
            if key.lower().startswith("cookie:"):
                key = key[7:].strip()
            if key and key.lower() not in cookie_attribute_names:
                cookies[key] = val
        else:
            cleaned = part.strip().strip('"\'')
            if cleaned.lower() not in cookie_attribute_names and len(cleaned) >= 8:
                # ASP.NET Core Data Protection signature or long auth ticket
                if cleaned.startswith("CfDJ8") or len(cleaned) > 80:
                    cookies[".AspNetCore.Cookies"] = cleaned
                elif not cookies:
                    cookies["ASP.NET_SessionId"] = cleaned

    return cookies


def _parse_html_report(html: str) -> tuple[str, str, list]:
    """Extract (title, text_lower, tables) from HTML.
    Uses BeautifulSoup if available, and gracefully falls back to built-in HTMLParser.
    """
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        text_lower = soup.get_text(separator=" ").lower()
        title = soup.title.string.strip() if soup.title and soup.title.string else "Attendance Report"
        tables = []
        for t in soup.find_all("table"):
            rows = []
            for tr in t.find_all("tr"):
                cells = [td.get_text(separator=" ", strip=True) for td in tr.find_all(["th", "td"])]
                if cells:
                    rows.append(cells)
            if rows:
                tables.append(rows)
        return title, text_lower, tables
    except ImportError:
        from html.parser import HTMLParser

        class _TableParser(HTMLParser):
            def __init__(self):
                super().__init__()
                self.title = ""
                self._in_title = False
                self.text_parts = []
                self.tables = []
                self._curr_table = None
                self._curr_row = None
                self._curr_cell = None

            def handle_starttag(self, tag, attrs):
                t = tag.lower()
                if t == "title":
                    self._in_title = True
                elif t == "table":
                    self._curr_table = []
                elif t == "tr" and self._curr_table is not None:
                    self._curr_row = []
                elif t in ("td", "th") and self._curr_row is not None:
                    self._curr_cell = []

            def handle_endtag(self, tag):
                t = tag.lower()
                if t == "title":
                    self._in_title = False
                elif t in ("td", "th") and self._curr_cell is not None:
                    cell_text = " ".join(self._curr_cell).strip()
                    if self._curr_row is not None:
                        self._curr_row.append(cell_text)
                    self._curr_cell = None
                elif t == "tr" and self._curr_row is not None:
                    if self._curr_row:
                        self._curr_table.append(self._curr_row)
                    self._curr_row = None
                elif t == "table" and self._curr_table is not None:
                    if self._curr_table:
                        self.tables.append(self._curr_table)
                    self._curr_table = None

            def handle_data(self, data):
                text = data.strip()
                if not text:
                    return
                if self._in_title:
                    self.title += " " + text
                if self._curr_cell is not None:
                    self._curr_cell.append(text)
                self.text_parts.append(text)

        parser = _TableParser()
        parser.feed(html)
        title = parser.title.strip() or "Attendance Report"
        text_lower = " ".join(parser.text_parts).lower()
        return title, text_lower, parser.tables


def _fetch_and_sync_portal_http(db: Session, uid: str, cookies: dict, portal_base_url: Optional[str] = None) -> dict:
    import httpx

    if not cookies:
        raise HTTPException(status_code=400, detail="No portal session cookies provided.")

    base = (portal_base_url or "https://portals.au.edu.pk/students/").rstrip("/")
    if not base.startswith("http"):
        base = "https://" + base
    if "portals.au.edu.pk" in base.lower() and "/students" not in base.lower():
        base = f"{base}/students"

    parsed_base = urlsplit(base)
    portal_host = parsed_base.netloc or "portals.au.edu.pk"
    origin = f"{parsed_base.scheme}://{portal_host}"

    att_setting = _portal_setting(db, uid, "portal_attendance_url")
    candidate_att_urls = []
    if att_setting and att_setting.value:
        candidate_att_urls.append(att_setting.value)

    default_candidates = [
        f"{base}/Reports/Attendance",
        f"{base}/attendance.aspx",
        f"{base}/Attendance.aspx",
        f"{base}/Reports/Attendance.aspx",
        f"{base}/Student/Attendance",
        f"{base}/Attendance",
    ]
    for cand in default_candidates:
        if cand not in candidate_att_urls:
            candidate_att_urls.append(cand)

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": base + "/",
        "Origin": origin,
        "Host": portal_host,
    }

    attendance_rows = []
    timetable_rows = []
    summary = {}
    successful_url = None
    auth_redirect_count = 0

    with httpx.Client(timeout=15.0, follow_redirects=False, headers=headers) as client:
        last_resp = None
        for cand_url in candidate_att_urls:
            try:
                resp = client.get(cand_url, cookies=cookies)
                last_resp = resp

                if resp.status_code in (301, 302, 303, 307, 308):
                    loc = resp.headers.get("Location", "")
                    if any(k in loc.lower() for k in ("login", "signin", "auth", "accounts.google.com")):
                        auth_redirect_count += 1
                        logger.warning("Candidate URL %s redirected to auth: %s", cand_url, loc)
                        continue
                    if loc.startswith("/") or portal_host in loc:
                        target = loc if loc.startswith("http") else urljoin(cand_url, loc)
                        resp = client.get(target, cookies=cookies)
                        last_resp = resp
                        if resp.status_code in (301, 302, 303, 307, 308):
                            loc2 = resp.headers.get("Location", "")
                            if any(k in loc2.lower() for k in ("login", "signin", "auth", "accounts.google.com")):
                                auth_redirect_count += 1
                                continue

                if resp.status_code == 200:
                    html = resp.text
                    title, text_lower, tables = _parse_html_report(html)

                    if "enter your password" in text_lower or ("sign in with google" in text_lower and not tables):
                        auth_redirect_count += 1
                        continue

                    parsed_att = _attendance_rows(tables, text_lower)
                    if parsed_att:
                        report = {"tables": tables, "text": text_lower, "title": title}
                        attendance_rows, timetable_rows, summary = _ingest_report_data(db, report, cand_url, uid)
                        successful_url = cand_url

                        for k, v in resp.cookies.items():
                            cookies[k] = v
                        break
            except Exception as e:
                logger.debug("Candidate URL %s error: %s", cand_url, e)
                continue

        if not attendance_rows and auth_redirect_count > 0:
            has_auth_token = any(
                k in cookies for k in (
                    ".AspNetCore.Cookies",
                    ".AspNetCore.CookiesC1",
                    ".AspNetCore.CookiesC2",
                    ".AspNetCore.Identity.Application",
                    ".AspNet.ApplicationCookie",
                    ".ASPXAUTH",
                )
            ) or any("auth" in k.lower() or "token" in k.lower() for k in cookies)
            has_session_id = any(k.lower() == "asp.net_sessionid" for k in cookies)

            if has_session_id and not has_auth_token:
                raise HTTPException(
                    status_code=401,
                    detail=(
                        "Authentication cookie missing. Only 'ASP.NET_SessionId' was provided, but the university portal requires "
                        "'.AspNetCore.Cookies' for student authentication. "
                        "In your browser DevTools (F12) → Network tab on portals.au.edu.pk, click any request and copy the full 'Cookie' request header, "
                        "or copy all cookies from Application → Storage → Cookies."
                    ),
                )
            raise HTTPException(
                status_code=401,
                detail="Session cookie expired or unauthenticated. Please sign into the university portal and copy fresh cookies (including .AspNetCore.Cookies).",
            )

        if not attendance_rows and last_resp is not None and last_resp.status_code != 200:
            raise HTTPException(
                status_code=last_resp.status_code,
                detail=f"University portal returned HTTP {last_resp.status_code}. Please verify your portal URL and cookies.",
            )

        # Optional timetable fetch
        if successful_url:
            tt_urls = [f"{base}/Reports/Timetable", f"{base}/timetable.aspx"]
            for tt_url in tt_urls:
                try:
                    tt_resp = client.get(tt_url, cookies=cookies)
                    if tt_resp.status_code == 200:
                        tt_title, tt_text_lower, tt_tables = _parse_html_report(tt_resp.text)
                        if tt_tables:
                            _ingest_report_data(
                                db,
                                {"tables": tt_tables, "text": tt_text_lower, "title": tt_title or "Timetable"},
                                tt_url,
                                uid,
                            )
                            break
                except Exception:
                    pass

    if not attendance_rows:
        raise HTTPException(
            status_code=400,
            detail="Connected to portal, but no course attendance records were found. Check your portal cookies or permissions.",
        )

    _set_portal_setting(db, uid, "portal_session_cookies", json.dumps(cookies), "Saved session cookies for portal HTTP sync")
    _set_portal_setting(db, uid, "portal_session_status", "ACTIVE", "Active portal session via cookies")
    if successful_url:
        _set_portal_setting(db, uid, "portal_attendance_url", successful_url, "Verified attendance report URL")
    db.commit()

    return {
        "status": "success",
        "attendance_count": len(attendance_rows),
        "attendance": attendance_rows,
        "summary": summary,
        "message": f"Successfully synced {len(attendance_rows)} course attendance records in milliseconds!",
    }


@router.post("/sync-cookies", response_model=dict)
def sync_portal_cookies(
    payload: PortalCookieSyncRequest,
    db: Session = Depends(get_db),
    user: dict = Depends(require_current_user),
):
    """Sync student's attendance instantly using HTTP session cookies (no browser needed)."""
    uid = _user_id(user)
    cookies = _parse_cookie_header(payload.cookies)
    if not cookies:
        raise HTTPException(
            status_code=400,
            detail="Invalid cookie format. Please paste your full portal Cookie header or session cookies.",
        )

    url = payload.portal_url
    if not url:
        stored_url = _portal_setting(db, uid, "university_portal_url")
        url = stored_url.value if stored_url else "https://portals.au.edu.pk/students/"
    else:
        url = _validate_portal_url(url)
        _set_portal_setting(db, uid, "university_portal_url", url, "Student-configured university portal URL")

    return _fetch_and_sync_portal_http(db, uid, cookies, url)


@router.delete("/cookies", response_model=dict)
def disconnect_portal_cookies(
    db: Session = Depends(get_db),
    user: dict = Depends(require_current_user),
):
    """Disconnect saved portal session cookies."""
    uid = _user_id(user)
    db.query(Setting).filter(
        Setting.key == _user_setting_key(uid, "portal_session_cookies")
    ).delete(synchronize_session=False)
    _set_portal_setting(db, uid, "portal_session_status", "NOT_CONFIGURED", "Portal session cookies cleared")
    db.commit()
    return {"status": "disconnected", "has_session_cookies": False}



def _portal_page_needs_login(page, portal_host: str) -> bool:
    """Detect login/SSO pages instead of treating every same-host page as signed in."""
    current_url = getattr(page, "url", "") or ""
    parsed = urlsplit(current_url)
    current_host = (parsed.hostname or "").lower()
    if current_host != portal_host or re.search(r"/(login|signin|sign-in|auth)(/|\.aspx|\.php|\.html|$)", parsed.path, re.I):
        return True
    try:
        # If there is an active visible password input, login is definitely needed
        if page.locator("input[type='password']:visible").count() > 0:
            return True

        # Check for clear signs of an active student session
        has_logout = page.locator("a[href*='logout' i], a[href*='signout' i], a:has-text('Logout'), a:has-text('Log Out')").count() > 0
        has_student_tables = page.locator("table").count() > 0
        if has_logout or has_student_tables:
            return False

        text = (page.locator("body").inner_text(timeout=2500) or "").lower()
    except Exception:
        return True

    login_indicators = (
        "please log in", "please login",
        "forgot password", "enter your password", "invalid username or password",
        "verification code", "one-time password", "two-factor", "verify it's you",
    )
    return any(phrase in text for phrase in login_indicators)


def _get_student_portal_email(db: Session, uid: str) -> str:
    """Resolve the student's university email from portal settings, Clerk profile, or Google credentials."""
    email_setting = _portal_setting(db, uid, "university_portal_login_email")
    if email_setting and email_setting.value and "@" in email_setting.value:
        return email_setting.value.strip()

    g_setting = _setting(db, "google_connected_email")
    if g_setting and g_setting.value and "@" in g_setting.value:
        return g_setting.value.strip()

    profile_row = db.query(Setting).filter(Setting.key.like("clerk_user_%")).order_by(Setting.updated_at.desc()).first()
    if profile_row and profile_row.value:
        try:
            prof = json.loads(profile_row.value)
            email = prof.get("email") or prof.get("emailAddress") or ""
            if email and "@" in email:
                return email.strip()
        except Exception:
            pass

    return "232530@students.au.edu.pk"


def _handle_portal_login_page(page, portal_host: str) -> bool:
    """If on university portal login page, auto-click 'Sign in with Google'."""
    current_url = getattr(page, "url", "") or ""
    if portal_host not in current_url.lower():
        return False
    if not _portal_page_needs_login(page, portal_host):
        return False

    try:
        google_btn_selectors = [
            "button:has-text('Sign In with Google')",
            "a:has-text('Sign In with Google')",
            "button:has-text('Sign in with Google')",
            "a:has-text('Sign in with Google')",
            "button:has-text('Google')",
            "a:has-text('Google')",
            "#btnGoogle",
            "a[href*='google' i]",
            "input[value*='Google' i]",
            ".btn-google",
        ]
        for sel in google_btn_selectors:
            loc = page.locator(sel)
            if hasattr(loc, "first"):
                loc = loc.first
            if hasattr(loc, "is_visible") and loc.is_visible():
                logger.info(f"Auto-clicking Google sign-in on portal: {sel}")
                loc.click(force=True)
                if hasattr(page, "wait_for_timeout"):
                    page.wait_for_timeout(2500)
                return True
    except Exception as e:
        logger.debug(f"Portal login button error: {e}")

    return False


def _handle_google_oauth_if_needed(page, user_id: Optional[str] = None, student_email: str = "") -> bool:
    """
    If the browser is on Google sign-in / account chooser, automatically select or fill student account.
    """
    current_url = getattr(page, "url", "") or ""
    if "accounts.google.com" not in current_url:
        return False

    if not student_email and user_id:
        try:
            db = SessionLocal()
            student_email = _get_student_portal_email(db, user_id)
            db.close()
        except Exception:
            student_email = ""

    try:
        # A. Account Chooser is shown
        selectors = [
            f"li:has-text('{student_email}')",
            f"div[data-identifier*='{student_email}']",
            f"[data-email*='{student_email}']",
            "li:has-text('@students.au.edu.pk')",
            "div[data-identifier*='@students.au.edu.pk']",
            "[data-email*='@students.au.edu.pk']",
            "li:has-text('@au.edu.pk')",
            "div[data-identifier*='@au.edu.pk']",
            "li:has-text('232530')",
            "div[data-identifier*='232530']",
        ]
        if student_email and "@" in student_email:
            roll_part = student_email.split("@")[0]
            selectors.append(f"li:has-text('{roll_part}')")
            selectors.append(f"div[data-identifier*='{roll_part}']")

        for sel in selectors:
            loc = page.locator(sel)
            if hasattr(loc, "first"):
                loc = loc.first
            if hasattr(loc, "is_visible") and loc.is_visible():
                logger.info(f"Auto-selected Google account: {sel}")
                loc.click(force=True)
                if hasattr(page, "wait_for_timeout"):
                    page.wait_for_timeout(3000)
                return True

        # B. Email input is shown (user not signed into Google in this profile)
        if student_email:
            email_input = page.locator("input[type='email']:visible, input[name='identifier']:visible").first
            if email_input.count() > 0 and email_input.is_visible():
                current_val = email_input.input_value()
                if not current_val:
                    logger.info(f"Auto-filling student email into Google sign-in: {student_email}")
                    email_input.fill(student_email)
                    if hasattr(page, "wait_for_timeout"):
                        page.wait_for_timeout(400)
                    next_btn = page.locator("#identifierNext, button:has-text('Next')").first
                    if next_btn.count() > 0 and next_btn.is_visible():
                        next_btn.click(force=True)
                    else:
                        page.keyboard.press("Enter")
                    if hasattr(page, "wait_for_timeout"):
                        page.wait_for_timeout(2500)
                    return True

        # C. Password input is shown and autofilled
        pass_input = page.locator("input[type='password']:visible, input[name='Passwd']:visible").first
        if pass_input.count() > 0 and pass_input.is_visible():
            if pass_input.input_value():
                pass_next = page.locator("#passwordNext, button:has-text('Next')").first
                if pass_next.count() > 0 and pass_next.is_visible():
                    logger.info("Auto-submitting autofilled password in Google sign-in")
                    pass_next.click(force=True)
                    if hasattr(page, "wait_for_timeout"):
                        page.wait_for_timeout(3000)
                    return True
    except Exception as e:
        logger.debug(f"Google OAuth auto-steps error: {e}")

    return False


def _run_portal_connection_automation(uid: str, portal_url: str):
    """
    Single-click maximum automation background worker:
    1. Connects to the active browser via CDP.
    2. Brings portal tab to front.
    3. Automates Google sign-in clicks and student email entry.
    4. Automatically detects when session is authenticated.
    5. Immediately marks session ACTIVE and triggers full portal sync in background!
    """
    port = _find_active_browser_port(uid)
    if not port:
        return

    portal_host = (urlsplit(portal_url).hostname or "").lower()
    db = SessionLocal()
    try:
        student_email = _get_student_portal_email(db, uid)
    finally:
        db.close()

    from playwright.sync_api import sync_playwright
    deadline = time.monotonic() + 90.0

    try:
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{port}", timeout=8000)
            context = browser.contexts[0] if browser.contexts else None
            if not context:
                return

            while time.monotonic() < deadline:
                pages = list(context.pages)
                authenticated = False

                for page in pages:
                    p_url = getattr(page, "url", "") or ""
                    p_host = (urlsplit(p_url).hostname or "").lower()

                    # 1. Check if authenticated on university portal
                    if p_host == portal_host and not _portal_page_needs_login(page, portal_host):
                        authenticated = True
                        break

                    # 2. If on portal login screen, auto-click Google sign in
                    if p_host == portal_host and _portal_page_needs_login(page, portal_host):
                        _handle_portal_login_page(page, portal_host)

                    # 3. If on Google OAuth, auto-select account or auto-type email
                    if "accounts.google.com" in p_url:
                        _handle_google_oauth_if_needed(page, uid, student_email)

                if authenticated:
                    logger.info(f"Portal session authenticated for user {uid}! Kicking off automated sync...")
                    sync_db = SessionLocal()
                    try:
                        _set_portal_setting(sync_db, uid, "portal_session_status", "ACTIVE", "University portal is connected")
                        if student_email:
                            _set_portal_setting(sync_db, uid, "university_portal_login_email", student_email, "Email used for university portal sign-in")
                        sync_db.commit()
                    finally:
                        sync_db.close()

                    # Trigger full portal sync job automatically
                    with _sync_jobs_lock:
                        active_id = _active_sync_jobs.get(uid)
                        if not active_id or _sync_jobs.get(active_id, {}).get("status") not in ("queued", "running"):
                            job_id = sha256(f"{uid}:{time.time_ns()}".encode()).hexdigest()[:20]
                            queued = {"status": "queued", "created_at": datetime.now(timezone.utc).isoformat()}
                            _sync_jobs[job_id] = queued
                            _active_sync_jobs[uid] = job_id
                            _persist_sync_job(uid, job_id, queued)
                            threading.Thread(target=_run_portal_sync_job, args=(uid, job_id), daemon=True).start()
                    break

                time.sleep(1.5)
    except Exception as e:
        logger.warning(f"Error during portal connection automation for {uid}: {e}")


@router.post("/open", response_model=dict)
async def open_portal_browser(background_tasks: BackgroundTasks, db: Session = Depends(get_db), user: dict = Depends(require_current_user)):
    uid = _user_id(user)
    url_setting = _portal_setting(db, uid, "university_portal_url")
    if not url_setting or not url_setting.value:
        raise HTTPException(status_code=409, detail="Save your university portal URL first.")

    url = _validate_portal_url(url_setting.value)
    browser_bin = _find_system_browser()
    process = _portal_processes.get(uid)

    active_port = _find_active_browser_port(uid)
    if active_port:
        _set_portal_setting(db, uid, "portal_session_status", "CONNECTING", "University portal sign-in is open")
        db.commit()

        # Seamlessly reuse the ALREADY RUNNING browser: open or focus portal tab!
        from playwright.sync_api import sync_playwright
        try:
            with sync_playwright() as p:
                _cleanup_untrusted_tabs_port(active_port)
                browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{active_port}", timeout=8000)
                context = browser.contexts[0] if browser.contexts else None
                if context:
                    portal_host = (urlsplit(url).hostname or "").lower()
                    target_page = None
                    for pg in context.pages:
                        cand_host = (urlsplit(pg.url or "").hostname or "").lower()
                        if cand_host == portal_host or "accounts.google.com" in (pg.url or ""):
                            target_page = pg
                            break
                    if target_page:
                        target_page.bring_to_front()
                    else:
                        pg = context.new_page()
                        pg.goto(url, wait_until="domcontentloaded", timeout=25000)
                        pg.bring_to_front()
        except Exception as e:
            logger.warning(f"Could not focus tab in running browser on port {active_port}: {e}")

        # Start automated login background worker
        background_tasks.add_task(_run_portal_connection_automation, uid, url)

        login_email_val = _portal_setting(db, uid, "university_portal_login_email")
        auth_method_val = _portal_setting(db, uid, "university_portal_auth_method")
        return {
            "opened": True,
            "reused_browser": True,
            "port": active_port,
            "title": "Google Chrome (Reused Active Window)",
            "url": url,
            "password_form_available": True,
            "google_sign_in_available": True,
            "is_direct_google_oauth": True,
            "login_email": login_email_val.value if login_email_val and login_email_val.value else "",
            "auth_method": auth_method_val.value if auth_method_val and auth_method_val.value else "google",
            "message": "Automating portal sign-in and sync in your active Chrome window...",
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

    # Use the persistent app profile; Chrome disables remote debugging for the default user profile.
    cmd = [
        browser_bin,
        f"--user-data-dir={_profile_dir(uid)}",
        f"--remote-debugging-port={USER_CDP_PORT}",
        "--remote-debugging-address=127.0.0.1",
        "--remote-allow-origins=*",
        "--restore-last-session",
        "--start-maximized",
        url,
    ]

    try:
        flags = (subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP) if os.name == "nt" else 0
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            creationflags=flags
        )
        _portal_processes[uid] = process
    except Exception as error:
        _set_portal_setting(db, uid, "portal_session_status", "ERROR", "Could not launch portal sign-in browser")
        db.commit()
        raise HTTPException(status_code=502, detail=f"Could not launch browser: {str(error)}") from error

    if not _wait_for_cdp(uid, timeout=10.0):
        try:
            process.terminate()
        except Exception:
            pass
        _portal_processes.pop(uid, None)
        _set_portal_setting(db, uid, "portal_session_status", "ERROR", "University browser remote debugging did not start")
        db.commit()
        raise HTTPException(status_code=502, detail="The sign-in browser opened, but its local connection did not start. Close other Uniflow portal windows and try again.")

    # Start automated login background worker
    background_tasks.add_task(_run_portal_connection_automation, uid, url)

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
        "message": "Automating portal sign-in and sync. Your saved session will be reused for future syncs.",
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


def _attendance_count(value: str):
    match = re.fullmatch(r"\s*(\d[\d,]*)(?:\.0+)?\s*", str(value or ""))
    return int(match.group(1).replace(",", "")) if match else None


def _attendance_rows(tables: list, text: str = ""):
    results = []
    seen_subjects = set()

    for table in tables:
        if not table:
            continue
        headers = [
            re.sub(r"[^a-z0-9%]+", " ", str(cell).strip().lower()).strip()
            for cell in table[0]
        ]

        def exact_column(names):
            return next((idx for idx, header in enumerate(headers) if header in names), -1)

        def fallback_column(terms, excluded=()):
            return next(
                (
                    idx for idx, header in enumerate(headers)
                    if any(term in header for term in terms)
                    and not any(term in header for term in excluded)
                ),
                -1,
            )

        subject_col = exact_column({"subject", "subject name", "course", "course name", "paper", "paper name"})
        if subject_col == -1:
            subject_col = fallback_column(("subject", "course", "paper", "module"))

        attended_col = exact_column({"att", "atts", "attended", "present", "total present", "lectures attended"})
        if attended_col == -1:
            attended_col = fallback_column(("attended", "present", "pres", "att"), ("hour", "hrs", "percentage", "percent", "%"))

        total_col = exact_column({"total", "total classes", "classes held", "total held", "lectures held"})
        if total_col == -1:
            total_col = fallback_column(("total", "held", "delivered", "lecture"), ("hour", "hrs", "credit"))

        absent_col = exact_column({"abs", "absent", "total absent", "lectures absent"})
        if absent_col == -1:
            absent_col = fallback_column(("absent", "abs", "leaves"), ("hour", "hrs", "percentage", "percent"))

        percent_col = fallback_column(("percentage", "percent", "%"))

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

            attended = _attendance_count(cells[attended_col]) if 0 <= attended_col < len(cells) else None
            total = _attendance_count(cells[total_col]) if 0 <= total_col < len(cells) else None
            absent = _attendance_count(cells[absent_col]) if 0 <= absent_col < len(cells) else None
            percentage = None

            if total is not None and attended is None and absent is not None and absent <= total:
                attended = total - absent
            if attended is not None and total is not None and total > 0 and attended <= total:
                percentage = round(attended * 100 / total, 2)

            if percentage is None and 0 <= percent_col < len(cells):
                pct_match = re.search(r"(\d{1,3}(?:\.\d+)?)", cells[percent_col])
                if pct_match:
                    parsed_percentage = float(pct_match.group(1))
                    if 0 <= parsed_percentage <= 100:
                        percentage = parsed_percentage

            if percentage is None:
                combined = " ".join(cells)
                fraction = re.search(r"(\d+)\s*/\s*(\d+)", combined)
                percent = re.search(r"(\d{1,3}(?:\.\d+)?)\s*%", combined)
                if fraction:
                    att, tot = int(fraction.group(1)), int(fraction.group(2))
                    if tot > 0 and att <= tot:
                        attended, total = att, tot
                        percentage = round(attended * 100 / total, 2) if total > 0 else None
                elif percent:
                    parsed_percentage = float(percent.group(1))
                    if 0 <= parsed_percentage <= 100:
                        percentage = parsed_percentage

            if subject and percentage is not None and subject.lower() not in seen_subjects:
                seen_subjects.add(subject.lower())
                results.append({
                    "subject": subject,
                    "attended": attended,
                    "total": total,
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
                        "attended": None,
                        "total": None,
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
        tt_entry = db.query(TimetableEntry).filter(
            (TimetableEntry.external_id == tt_ext_id) |
            (
                (func.lower(TimetableEntry.subject) == subj.lower()) &
                (TimetableEntry.weekday == weekday) &
                (TimetableEntry.start_time == st) &
                (TimetableEntry.end_time == et)
            )
        ).first()
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
    invalidate_attendance_summary_cache()
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

PORTAL_NAVIGATION_SCRIPT = """() => {
  const selector = "a[href], [role='tab'], [role='menuitem'], button, [onclick]";
  return Array.from(document.querySelectorAll(selector)).map((element, index) => {
    const href = element.getAttribute('href') || '';
    const onclick = element.getAttribute('onclick') || '';
    const role = (element.getAttribute('role') || '').toLowerCase();
    const text = (element.innerText || element.textContent || element.value ||
      element.getAttribute('aria-label') || element.getAttribute('title') || '')
      .trim().replace(/\\s+/g, ' ').slice(0, 120);
    return {
      index,
      tag: element.tagName.toLowerCase(),
      role,
      text,
      id: element.id || '',
      name: element.getAttribute('name') || '',
      href,
      onclick,
      in_navigation: !!element.closest("nav, [role='navigation'], .nav, .navbar, .sidebar, .menu"),
      is_hash_link: href.startsWith('#'),
      is_postback: /__doPostBack|WebForm_DoPostBackWithOptions/i.test(href + ' ' + onclick),
      visible: !!(element.offsetWidth || element.offsetHeight || element.getClientRects().length)
    };
  });
}"""


def _portal_navigation_controls(controls: list[dict], portal_host: str) -> list[dict]:
    """Select visible, safe-to-click academic tabs that do not already have a direct URL."""
    topics = re.compile(
        r"attendance|time\s*table|schedule|grade|transcript|result|academic|"
        r"registration|registered\s+courses?|enrol(?:l)?ment|course\s+history",
        re.I,
    )
    action = re.compile(r"^\s*(?:register|enroll|enrol|add|drop|submit|confirm)\b", re.I)
    selected = []
    for control in controls:
        if not control.get("visible"):
            continue
        text = str(control.get("text") or "").strip()
        href = str(control.get("href") or "").strip()
        onclick = str(control.get("onclick") or "")
        role = str(control.get("role") or "").lower()
        search_text = " ".join((text, str(control.get("id") or ""), str(control.get("name") or ""), href, onclick))
        if "/ors/" in search_text.lower() or "registration portal" in search_text.lower():
            continue
        if not topics.search(search_text):
            continue
        if action.search(text) and not re.match(r"^\s*registered\s+courses?\b", text, re.I):
            continue

        parsed_href = urlsplit(href)
        if parsed_href.scheme in ("http", "https"):
            if (parsed_href.hostname or "").lower() != portal_host:
                continue
            if portal_host == "portals.au.edu.pk" and not parsed_href.path.lower().startswith("/students/"):
                continue
        is_postback = bool(control.get("is_postback")) or bool(
            re.search(r"__doPostBack|WebForm_DoPostBackWithOptions", href + " " + onclick, re.I)
        )
        is_navigation = role in ("tab", "menuitem") or bool(control.get("in_navigation"))
        is_click_only = not href or bool(control.get("is_hash_link")) or href.lower().startswith("javascript:")
        if is_navigation and (is_click_only or is_postback):
            selected.append(control)
    return selected


def _is_academic_portal_link(href: str, text: str = "") -> bool:
    low = f"{href} {text}".lower()
    if "/ors/" in low or "registration portal" in low:
        return False
    return bool(re.search(
        r"attendance|timetable|time\s*table|schedule|grade|transcript|result|academic|"
        r"registered[\s_-]*courses?",
        low,
        re.I,
    ))


def _discover_portal_tab_pages(page, portal_host: str, root_url: str) -> tuple[list[dict], list[str]]:
    """Click portal-owned postback/tab controls and collect their page data and links."""
    controls = page.evaluate(PORTAL_NAVIGATION_SCRIPT)
    candidates = _portal_navigation_controls(controls, portal_host)[:20]
    reports = []
    discovered_urls = []
    locator_selector = "a[href], [role='tab'], [role='menuitem'], button, [onclick]"

    for index, control in enumerate(candidates):
        try:
            if index:
                page.goto(root_url, wait_until="domcontentloaded", timeout=20000)
                page.wait_for_timeout(500)
            if _portal_page_needs_login(page, portal_host):
                break

            locator = page.locator(locator_selector).nth(int(control["index"]))
            if not locator.is_visible():
                continue
            locator.click(timeout=4000)
            page.wait_for_timeout(1200)

            current_url = page.url or root_url
            if (urlsplit(current_url).hostname or "").lower() != portal_host:
                continue
            if _portal_page_needs_login(page, portal_host):
                break

            report = page.evaluate(DOM_EXTRACTION_SCRIPT)
            report["discovered_urls"] = page.evaluate("""() => Array.from(document.querySelectorAll('a[href]'))
              .map(a => ({href: a.href, text: (a.innerText || a.textContent || '').trim()}))
              .filter(a => /attendance|timetable|time\\s*table|schedule|grade|transcript|result|academic|registered[\\s_-]*courses?|registration|enrol(?:l)?ment/i.test(a.href + ' ' + a.text))
              .map(a => a.href)""")
            reports.append({"report": report, "current_url": current_url})
            discovered_urls.extend(report["discovered_urls"])
        except Exception as error:
            reports.append({"error": str(error), "current_url": page.url or root_url})

    return reports, discovered_urls


def _handle_google_oauth_if_needed_secondary(page, user_id: Optional[str] = None, student_email: str = "") -> bool:
    """Delegates to the primary Google OAuth handler."""
    return _handle_google_oauth_if_needed(page, user_id=user_id, student_email=student_email)


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
        active_port = _find_active_browser_port(user_id)
        if active_port:
            try:
                _cleanup_untrusted_tabs_port(active_port)
                browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{active_port}", timeout=10000)
                context = browser.contexts[0] if browser.contexts else None
            except Exception as error:
                logger.warning(f"Could not attach to active browser on port {active_port} for {user_id}: {error}")

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
            portal_host = (urlsplit(target_urls[0]).hostname or "").lower()
            page = None
            if context.pages:
                for p_candidate in context.pages:
                    cand_host = (urlsplit(p_candidate.url or "").hostname or "").lower()
                    if cand_host == portal_host and not _portal_page_needs_login(p_candidate, portal_host):
                        page = p_candidate
                        break
                if page is None:
                    for p_candidate in context.pages:
                        if not (p_candidate.url or "").startswith(("chrome://", "chrome-untrusted://")):
                            page = p_candidate
                            break
            if page is None:
                page = context.pages[0] if context.pages else context.new_page()

            # Navigate to base URL if not already on portal
            if not page.url or page.url == "about:blank" or portal_host not in (urlsplit(page.url).hostname or "").lower():
                page.goto(target_urls[0], wait_until="domcontentloaded", timeout=25000)
            page.wait_for_timeout(1000)

            if "accounts.google.com" in (page.url or ""):
                _handle_google_oauth_if_needed(page, user_id)
                page.wait_for_timeout(3000)

            if _portal_page_needs_login(page, portal_host):
                return {"status": "session_expired", "current_url": page.url, "detail": "University sign-in is required. Reconnect once to continue automatic sync."}

            discovered = page.evaluate("""() => Array.from(document.querySelectorAll('a[href]'))
              .map(a => ({href: a.href, text: (a.innerText || a.textContent || '').trim()}))
              .filter(a => !/\\/ors\\/|registration\\s*portal/i.test(a.href + ' ' + a.text) &&
                           /attendance|timetable|time\\s*table|schedule|grade|transcript|result|academic|registered[\\s_-]*courses?/i.test(a.href + ' ' + a.text))
              .map(a => a.href)""")
            tab_reports = []
            tab_discovered = []
            try:
                tab_reports, tab_discovered = _discover_portal_tab_pages(page, portal_host, page.url or target_urls[0])
            except Exception as error:
                tab_reports.append({"error": f"Could not inspect portal tabs: {error}", "current_url": page.url or target_urls[0]})

            urls = list(target_urls)
            if portal_host == "portals.au.edu.pk":
                for path in ("Reports/Attendance", "Reports/Timetable", "Reports/RegisteredCourses", "Reports/Grade"):
                    candidate = urlsplit(target_urls[0])
                    preset_url = f"{candidate.scheme}://{candidate.netloc}/students/{path}"
                    if preset_url not in urls:
                        urls.append(preset_url)
            for link in discovered:
                parsed = urlsplit(link)
                if parsed.scheme in ("http", "https") and (parsed.hostname or "").lower() == portal_host and link not in urls:
                    if portal_host == "portals.au.edu.pk" and not parsed.path.lower().startswith("/students/"):
                        continue
                    urls.append(link)
            for link in tab_discovered:
                parsed = urlsplit(link)
                if (parsed.scheme in ("http", "https") and (parsed.hostname or "").lower() == portal_host
                        and _is_academic_portal_link(link) and link not in urls):
                    if portal_host == "portals.au.edu.pk" and not parsed.path.lower().startswith("/students/"):
                        continue
                    urls.append(link)

            # Exclude the portal login entrypoint and any non-student sub-apps from the report scrape loop
            report_urls = []
            for u in urls:
                parsed_u = urlsplit(u)
                p_path = (parsed_u.path or "").rstrip("/")
                if p_path in ("/students", ""):
                    continue
                if portal_host == "portals.au.edu.pk" and not parsed_u.path.lower().startswith("/students/"):
                    continue
                if "/ors/" in u.lower():
                    continue
                if u not in report_urls:
                    report_urls.append(u)

            if not report_urls:
                report_urls = [u for u in urls if "/ors/" not in u.lower()]

            reports.extend(tab_reports)
            if portal_host not in (urlsplit(page.url or "").hostname or "").lower() or _portal_page_needs_login(page, portal_host):
                page.goto(target_urls[0], wait_until="domcontentloaded", timeout=20000)
                page.wait_for_timeout(500)
            if _portal_page_needs_login(page, portal_host):
                return {"status": "session_expired", "current_url": page.url, "detail": "University sign-in expired. Reconnect once to resume automatic sync."}

            for url in report_urls:
                try:
                    parsed_target = urlsplit(url)
                    target_path = parsed_target.path.split("/")[-1] if parsed_target.path else ""
                    clicked = False
                    if target_path:
                        try:
                            link_elem = page.locator(f"a[href*='{target_path}'], a:has-text('{target_path}')").first
                            if link_elem.is_visible():
                                link_elem.click()
                                page.wait_for_timeout(1500)
                                clicked = True
                        except Exception:
                            clicked = False
                    if not clicked and page.url != url:
                        page.goto(url, wait_until="domcontentloaded", timeout=20000)
                        page.wait_for_timeout(1000)

                    if "accounts.google.com" in (page.url or ""):
                        _handle_google_oauth_if_needed(page, user_id)
                        page.wait_for_timeout(3000)

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
            # When connected over CDP, DO NOT call browser.close() as that terminates the browser process!
            # Only close context if we launched our own headless persistent context
            if owns_context and context:
                try:
                    context.close()
                except Exception:
                    pass


def _portal_browser_authenticated(user_id: str, portal_url: str) -> bool:
    """Check the live sign-in window without changing its current page or closing the browser."""
    portal_host = (urlsplit(portal_url).hostname or "").lower()
    if not _cdp_is_available(user_id):
        return False
    port = _find_active_browser_port(user_id) or _cdp_port(user_id)

    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            _cleanup_untrusted_tabs_port(port)
            browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{port}", timeout=4000)
            pages = [page for context in browser.contexts for page in context.pages]
            for page in pages:
                page_host = (urlsplit(getattr(page, "url", "") or "").hostname or "").lower()
                if page_host == portal_host and not _portal_page_needs_login(page, portal_host):
                    return True
                if "accounts.google.com" in (getattr(page, "url", "") or ""):
                    try:
                        _handle_google_oauth_if_needed(page, user_id)
                        if hasattr(page, "wait_for_timeout"):
                            page.wait_for_timeout(2000)
                    except Exception:
                        pass
            return False
            # Notice: Never call browser.close() here as that terminates the user's running Chrome window!
    except Exception:
        pass

    # Fast-path fallback check via CDP JSON targets if Playwright sync connection times out
    try:
        req = urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=1.5)
        raw_tabs = json.loads(req.read().decode())
        for tab in raw_tabs:
            if tab.get("type") != "page":
                continue
            tab_url = tab.get("url") or ""
            tab_host = (urlsplit(tab_url).hostname or "").lower()
            if tab_host == portal_host:
                tab_path = urlsplit(tab_url).path.lower()
                if not any(auth_word in tab_path for auth_word in ("/login", "/signin", "/auth")):
                    return True
    except Exception:
        pass

    return False


@router.get("/connection-status", response_model=dict)
async def portal_connection_status(db: Session = Depends(get_db), user: dict = Depends(require_current_user)):
    uid = _user_id(user)
    portal_url = _portal_setting(db, uid, "university_portal_url")
    if not portal_url or not portal_url.value:
        raise HTTPException(status_code=409, detail="Save your university portal address first.")
    authenticated = await asyncio.to_thread(_portal_browser_authenticated, uid, portal_url.value)

    active_job_id = None
    with _sync_jobs_lock:
        cand_id = _active_sync_jobs.get(uid)
        if cand_id and _sync_jobs.get(cand_id, {}).get("status") in ("queued", "running", "success"):
            active_job_id = cand_id

    return {
        "status": "authenticated" if authenticated else "waiting",
        "job_id": active_job_id,
        "syncing": bool(active_job_id),
    }


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
    redis_lock_key = f"uniflow:lock:portal-sync:{sha256(uid.encode('utf-8')).hexdigest()}"
    redis_lock_owner = uuid.uuid4().hex
    redis_lock_acquired = False
    lock_id = int(sha256(f"portal-sync:{uid}".encode("utf-8")).hexdigest()[:15], 16)
    distributed_lock = False
    lock_connection = None
    try:
        redis_lock_unavailable = False
        if is_redis_configured():
            try:
                redis_lock_acquired = acquire_redis_lock(redis_lock_key, redis_lock_owner, 900)
            except UpstashRedisError as error:
                redis_lock_unavailable = True
                logger.warning("Upstash portal sync lock unavailable; falling back to PostgreSQL lock: %s", error)
            if not redis_lock_acquired and not redis_lock_unavailable:
                return {"status": "already_running", "message": "A portal sync is already running."}
        if not redis_lock_acquired and db.bind and db.bind.dialect.name == "postgresql":
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

        # Fast-path: If student has saved session cookies, try fast HTTP sync first (zero browser overhead)
        cookie_setting = _portal_setting(db, uid, "portal_session_cookies")
        if cookie_setting and cookie_setting.value:
            try:
                cookies = _parse_cookie_header(cookie_setting.value)
                if cookies:
                    logger.info("Attempting fast HTTP portal sync with saved session cookies for user %s", uid)
                    http_res = _fetch_and_sync_portal_http(db, uid, cookies, base.value)
                    if http_res.get("status") == "success":
                        return http_res
            except Exception as http_err:
                logger.warning("Fast HTTP portal sync failed or expired, falling back to browser: %s", http_err)

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
        if redis_lock_acquired:
            try:
                release_redis_lock(redis_lock_key, redis_lock_owner)
            except UpstashRedisError as error:
                logger.warning("Could not release Upstash portal sync lock; it will expire automatically: %s", error)
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
    db = SessionLocal()
    try:
        repo = PortalSyncJobRepository(db)
        repo.complete_job(job_id, error=None)  # Mark as running
        
        result = _sync_portal_for_user(uid)
        
        repo.complete_job(job_id, result=result, error=None)
    except Exception as error:
        repo = PortalSyncJobRepository(db)
        repo.complete_job(job_id, error=str(error))
    finally:
        db.close()


def _persist_sync_job(uid: str, job_id: str, result: dict):
    """Legacy function - kept for compatibility, now uses persistent repository"""
    db = SessionLocal()
    try:
        repo = PortalSyncJobRepository(db)
        if result.get("status") == "running":
            repo.complete_job(job_id, error=None)
        elif result.get("status") == "error":
            repo.complete_job(job_id, error=result.get("error"))
        else:
            repo.complete_job(job_id, result=result, error=None)
    finally:
        db.close()


@router.post("/sync", response_model=dict)
def queue_portal_sync(background_tasks: BackgroundTasks, db: Session = Depends(get_db), user: dict = Depends(require_current_user)):
    uid = _user_id(user)
    repo = PortalSyncJobRepository(db)
    
    # Check for active job
    active_job = repo.get_active_job(uid)
    if active_job:
        return {"status": "queued", "job_id": active_job.job_id, "message": "Your portal sync is already in progress."}
    
    # Create new job
    job_id = sha256(f"{uid}:{time.time_ns()}".encode()).hexdigest()[:20]
    repo.create(uid, job_id)
    db.commit()
    
    background_tasks.add_task(_run_portal_sync_job, uid, job_id)
    return {"status": "queued", "job_id": job_id, "message": "Sync started. Your saved portal data remains available while it refreshes."}


@router.get("/sync/{job_id}", response_model=dict)
def get_portal_sync_status(job_id: str, db: Session = Depends(get_db), user: dict = Depends(require_current_user)):
    repo = PortalSyncJobRepository(db)
    job = repo.get_by_job_id(job_id)
    
    if not job:
        raise HTTPException(status_code=404, detail="Sync job was not found or has expired.")
    
    result = {
        "job_id": job.job_id,
        "status": job.status,
        "sync_type": job.sync_type,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "error": job.error,
        "result": json.loads(job.result) if job.result else None,
        "retry_count": job.retry_count,
    }
    return result


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
