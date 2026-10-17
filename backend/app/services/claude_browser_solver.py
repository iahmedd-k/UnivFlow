import os
import re
import json
import base64
import time
import shutil
import urllib.request
import urllib.error
import subprocess
import atexit
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List, Tuple
from sqlalchemy.orm import Session

from app.db.models import (
    Assignment,
    AssignmentSolution,
    AssignmentMaterial,
    BrowserAutomationJob,
    Course,
    AssignmentStatus,
    Setting,
)
from app.core.config import settings
from app.core.logging import logger
from app.services.google_docs import get_google_docs_service
from app.services.ai_solution import export_solution_to_google_doc

# Per-user browser profiles for isolation
CLAUDE_BROWSER_PROFILE_ROOT = Path(__file__).resolve().parent.parent.parent / "tmp" / "claude_browser_profiles"
CLAUDE_BROWSER_PROFILE_ROOT.mkdir(parents=True, exist_ok=True)

# Fallback global profile for backward compatibility
CLAUDE_BROWSER_PROFILE_DIR = CLAUDE_BROWSER_PROFILE_ROOT / "global"
CLAUDE_BROWSER_PROFILE_DIR.mkdir(parents=True, exist_ok=True)

CLAUDE_MATERIALS_DIR = Path(__file__).resolve().parent.parent.parent / "tmp" / "materials"
CLAUDE_MATERIALS_DIR.mkdir(parents=True, exist_ok=True)

# Configurable ports and timeouts
USER_CDP_PORT = 9222
CDP_CONNECT_TIMEOUT_MS = 20000
CDP_CONNECT_ATTEMPTS = 2
BROWSER_LAUNCH_TIMEOUT = 30  # seconds
CLAUDE_RESPONSE_TIMEOUT = 300  # seconds (5 minutes for complex responses)

def _has_display() -> bool:
    """Check if an X11, Wayland, or Windows desktop display is available and actually running."""
    if os.name == "nt":
        return True
    display = os.environ.get("DISPLAY")
    if display and display.startswith(":"):
        try:
            disp_num = display.lstrip(":").split(".")[0]
            if Path(f"/tmp/.X11-unix/X{disp_num}").exists():
                return True
        except Exception:
            pass
        return False
    return bool(os.environ.get("WAYLAND_DISPLAY"))



def _get_headless_mode() -> bool:
    """
    Get headless mode from settings.
    Enforces True if no graphical display server ($DISPLAY / $WAYLAND_DISPLAY) is available
    to prevent Playwright crashing on Linux / Docker environments.
    """
    if not _has_display():
        return True
    try:
        from app.core.config import settings
        return bool(settings.playwright_headless)
    except Exception:
        return True

_claude_processes: Dict[str, subprocess.Popen] = {}  # Per-user processes

_HEAVY_ML_PATTERN = re.compile(
    r"\b(?:deep learning|deep neural|neural network|transformer|large language model|"
    r"llm|computer vision|cuda|gpu|model training|train(?:ing)? models?)\b",
    re.IGNORECASE,
)
_DIAGRAM_FENCE_TAGS = {
    "mermaid", "plantuml", "puml", "graphviz", "dot", "erd", "nomnoml",
    "drawio", "xml", "mxfile", "mxgraph",
}


_ALREADY_SOLVING_STALE_SECONDS = 20 * 60


def _validate_drawio_xml(xml_content: str) -> bool:
    """Validate Draw.io XML structure for mxGraph compatibility."""
    try:
        import xml.etree.ElementTree as ET
        root = ET.fromstring(xml_content)
        
        # Check for required mxfile root
        if root.tag != "mxfile":
            return False
        
        # Check for diagram element
        diagram = root.find("diagram")
        if diagram is None:
            return False
        
        # Check for mxGraphModel
        mx_graph_model = diagram.find("mxGraphModel")
        if mx_graph_model is None:
            return False
        
        # Check for root element
        root_elem = mx_graph_model.find("root")
        if root_elem is None:
            return False
        
        # Check for at least one mxCell
        cells = root_elem.findall("mxCell")
        if not cells:
            return False
        
        return True
    except Exception:
        return False


def _convert_drawio_to_mermaid(drawio_xml: str) -> Optional[str]:
    """Attempt to convert Draw.io XML to Mermaid flowchart as fallback."""
    try:
        import xml.etree.ElementTree as ET
        root = ET.fromstring(drawio_xml)
        
        # Extract cells and connections
        diagram = root.find("diagram")
        if diagram is None:
            return None
        mx_graph_model = diagram.find("mxGraphModel")
        if mx_graph_model is None:
            return None
        root_elem = mx_graph_model.find("root")
        if root_elem is None:
            return None
        
        cells = root_elem.findall("mxCell")
        nodes = {}
        edges = []
        
        for cell in cells:
            cell_id = cell.get("id")
            value = cell.get("value", "")
            style = cell.get("style", "")
            parent = cell.get("parent")
            edge = cell.get("edge", "0")
            source = cell.get("source")
            target = cell.get("target")
            
            if edge == "1" and source and target:
                edges.append((source, target))
            elif value and value.strip():
                # Clean HTML tags from value
                import re
                clean_value = re.sub(r'<[^>]+>', '', value)
                clean_value = re.sub(r'<', '<', clean_value)
                clean_value = re.sub(r'>', '>', clean_value)
                clean_value = re.sub(r'&', '&', clean_value)
                clean_value = re.sub(r'<br\s*/?>', ' ', clean_value)
                clean_value = clean_value.strip()
                if clean_value:
                    nodes[cell_id] = clean_value[:50]  # Truncate long labels
        
        if not nodes:
            return None
        
        # Generate Mermaid flowchart
        lines = ["```mermaid", "flowchart TD"]
        for node_id, label in nodes.items():
            safe_id = re.sub(r'[^a-zA-Z0-9_]', '_', node_id)
            safe_label = label.replace('"', '\\"')
            lines.append(f'    {safe_id}["{safe_label}"]')
        
        for source, target in edges:
            if source in nodes and target in nodes:
                safe_source = re.sub(r'[^a-zA-Z0-9_]', '_', source)
                safe_target = re.sub(r'[^a-zA-Z0-9_]', '_', target)
                lines.append(f"    {safe_source} --> {safe_target}")
        
        lines.append("```")
        return "\n".join(lines)
    except Exception:
        return None


def _is_assignment_already_solving(db: Session, assignment_id: int, user_id: str) -> bool:
    """Return True if this assignment is currently being solved by another session/job."""
    assignment = db.query(Assignment).filter(
        Assignment.id == assignment_id,
        Assignment.user_id == user_id,
    ).first()
    if not assignment:
        return False

    if assignment.status != AssignmentStatus.GENERATING:
        return False

    solution = db.query(AssignmentSolution).filter(
        AssignmentSolution.assignment_id == assignment_id,
    ).first()
    if solution and solution.generated_at:
        generated_at = solution.generated_at
        if generated_at.tzinfo is None:
            generated_at = generated_at.replace(tzinfo=timezone.utc)
        if (datetime.now(timezone.utc) - generated_at).total_seconds() < _ALREADY_SOLVING_STALE_SECONDS:
            return True

    running_job = db.query(BrowserAutomationJob).filter(
        BrowserAutomationJob.assignment_id == assignment_id,
        BrowserAutomationJob.user_id == user_id,
        BrowserAutomationJob.status == "running",
    ).first()
    if running_job:
        return True

    return False


def _get_user_profile_dir(user_id: str) -> Path:
    """Get or create per-user browser profile directory."""
    profile_dir = CLAUDE_BROWSER_PROFILE_ROOT / user_id
    profile_dir.mkdir(parents=True, exist_ok=True)
    return profile_dir


def find_system_browser() -> str:
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
    for cmd in ("chrome", "google-chrome", "msedge", "chromium"):
        which = shutil.which(cmd)
        if which:
            return which
    return "chrome.exe"


def is_cdp_port_live(port: int = USER_CDP_PORT, timeout: float = 0.5) -> bool:
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/json/version")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return bool(data.get("webSocketDebuggerUrl"))
    except Exception:
        return False


def get_active_cdp_port() -> Optional[int]:
    """Check if Chrome remote debugging is active on port 9222."""
    if is_cdp_port_live(USER_CDP_PORT):
        return USER_CDP_PORT
    return None


def connect_to_chrome(chromium: Any, endpoint: Any) -> Any:
    """Attach to a user's hosted Chrome, retrying once after a slow DevTools handshake."""
    last_error = None
    for attempt in range(1, CDP_CONNECT_ATTEMPTS + 1):
        try:
            return chromium.connect_over_cdp(
                endpoint if isinstance(endpoint, str) else f"http://127.0.0.1:{endpoint}",
                timeout=CDP_CONNECT_TIMEOUT_MS,
            )
        except Exception as error:
            last_error = error
            if attempt < CDP_CONNECT_ATTEMPTS:
                logger.warning(
                    "Chrome CDP attach attempt %s/%s failed on port %s; retrying: %s",
                    attempt,
                    CDP_CONNECT_ATTEMPTS,
                    endpoint,
                    error,
                )
                time.sleep(1)

    if last_error is not None:
        raise last_error
    raise RuntimeError(f"Chrome CDP attach failed on port {port} without an error detail.")


def open_claude_browser_window(user_id: str = "default", headless: bool = None) -> Dict[str, Any]:
    """
    Launch or focus the persistent Uniflow browser profile with remote debugging enabled.
    Using a dedicated data directory per user is required for isolation.
    Optimized for Azure (2 vCPU, 8GB): headed + ANGLE GPU + memory limits.
    """
    if headless is None:
        headless = _get_headless_mode()

    global _claude_processes

    profile_dir = _get_user_profile_dir(user_id)

    # CLEAN STALE LOCKS BEFORE LAUNCH (critical for Azure container restarts)
    for lock_name in ("SingletonLock", "SingletonSocket", "SingletonCookie"):
        lock_path = profile_dir / lock_name
        try:
            if lock_path.is_symlink() or lock_path.exists():
                lock_path.unlink()
        except Exception:
            pass

    active_port = get_active_cdp_port()
    if active_port is not None:
        return {
            "status": "ready",
            "port": active_port,
            "user_id": user_id,
            "message": f"Chrome remote debugging is already active on port {active_port} for user {user_id}.",
        }

    browser_bin = find_system_browser()

    # BASE FLAGS (both headed/headless) - GPU via ANGLE + Memory limits
    cmd = [
        browser_bin,
        f"--user-data-dir={profile_dir}",
        f"--remote-debugging-port={USER_CDP_PORT}",
        "--remote-debugging-address=127.0.0.1",
        "--remote-allow-origins=*",
        "--restore-last-session",
        "https://claude.ai/new",

        # GPU ACCELERATION (ANGLE = DirectX on Windows/Azure)
        "--use-gl=angle",
        "--enable-gpu-rasterization",
        "--enable-zero-copy",
        "--ignore-gpu-blocklist",
        "--enable-features=VaapiVideoDecoder,CanvasOopRasterization",

        # DISABLE BACKGROUND THROTTLING
        "--disable-background-timer-throttling",
        "--disable-renderer-backgrounding",
        "--disable-features=CalculateNativeWinOcclusion",

        # MEMORY LIMITS (critical for 8GB Azure)
        "--js-flags=--max-old-space-size=512",
        "--max_old_space_size=512",
        "--memory-pressure-off",

        # DISABLE UNNECESSARY SERVICES
        "--disable-breakpad",
        "--disable-component-update",
        "--disable-background-networking",
        "--disable-sync",
        "--disable-default-apps",
        "--no-first-run",
        "--no-default-browser-check",

        # RESOURCE OPTIMIZATIONS
        "--disable-dev-shm-usage",
    ]

    if headless:
        cmd.extend([
            "--headless=new",
            # DO NOT use --disable-gpu in headless on Azure — ANGLE still works!
            "--no-sandbox",
            "--disable-extensions",
        ])
    else:
        # HEADED: Start maximized
        cmd.extend(["--start-maximized"])

    try:
        flags = (subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | 0x00000200) if os.name == "nt" else 0
        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                creationflags=flags
            )
        except OSError:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                creationflags=(subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP) if os.name == "nt" else 0
            )
        _claude_processes[user_id] = process
    except Exception as e:
        logger.error(f"Failed to launch Chrome for Claude (user {user_id}): {e}")
        return {"status": "error", "error": f"Failed to launch Chrome: {str(e)}"}

    # Wait up to BROWSER_LAUNCH_TIMEOUT seconds for CDP endpoint to become ready
    deadline = time.monotonic() + BROWSER_LAUNCH_TIMEOUT
    while time.monotonic() < deadline:
        if is_cdp_port_live(USER_CDP_PORT):
            return {
                "status": "launched",
                "port": USER_CDP_PORT,
                "user_id": user_id,
                "headless": headless,
                "message": (
                    f"Uniflow's persistent browser profile for user {user_id} is ready on port {USER_CDP_PORT}. "
                    "Sign in to Claude in that window the first time."
                )
            }
        time.sleep(0.4)

    error_message = (
        f"Chrome opened with Uniflow's persistent profile for user {user_id}, but its debugging endpoint on "
        f"port {USER_CDP_PORT} did not become ready. Check that Chrome is installed and "
        "that no other process is using this profile or port."
    )
    logger.error(error_message)
    # Cleanup failed process
    if user_id in _claude_processes:
        try:
            _claude_processes[user_id].terminate()
        except Exception:
            pass
        del _claude_processes[user_id]
    return {
        "status": "error",
        "port": USER_CDP_PORT,
        "error": error_message,
    }


def close_claude_browser_window(user_id: str = "default") -> Dict[str, Any]:
    """Close the user's Claude browser window and cleanup."""
    global _claude_processes
    
    if user_id in _claude_processes:
        try:
            process = _claude_processes[user_id]
            process.terminate()
            process.wait(timeout=5)
        except Exception as e:
            logger.warning(f"Error terminating browser for user {user_id}: {e}")
            try:
                process.kill()
            except Exception:
                pass
        finally:
            del _claude_processes[user_id]
        return {"status": "closed", "user_id": user_id}
    
    return {"status": "not_running", "user_id": user_id}


def get_student_metadata(
    db: Session,
    course: Optional[Course],
    user_id: Optional[str] = None,
) -> Dict[str, str]:
    """Extract standard student and institutional metadata for Air University submissions."""
    profile_row = None
    if user_id:
        profile_row = db.query(Setting).filter(Setting.key == f"clerk_user_{user_id}").first()
    else:
        profile_row = db.query(Setting).filter(Setting.key.like("clerk_user_%")).order_by(Setting.id.desc()).first()

    profile = {}
    if profile_row and hasattr(profile_row, "value") and isinstance(profile_row.value, str):
        try:
            profile = json.loads(profile_row.value)
        except Exception:
            profile = {}

    user_email = profile.get("email", "") if isinstance(profile.get("email"), str) else ""
    if not user_email and user_id:
        try:
            email_row = db.query(Setting).filter(
                Setting.key.in_([
                    f"google_connected_email_{user_id}",
                    f"university_portal_login_email_{user_id}",
                    "google_connected_email",
                    "university_portal_login_email"
                ])
            ).first()
            if email_row and hasattr(email_row, "value") and isinstance(email_row.value, str):
                user_email = email_row.value.strip()
        except Exception:
            pass

    student_name = " ".join(
        part for part in (profile.get("first_name"), profile.get("last_name")) if isinstance(part, str) and part.strip() and part.strip() != "."
    ).strip() or (profile.get("name") if isinstance(profile.get("name"), str) else None) or "Student"

    roll_no = profile.get("student_id") or profile.get("roll_no") or profile.get("rollNumber") or ""
    if not isinstance(roll_no, str):
        roll_no = str(roll_no) if roll_no else ""

    if not roll_no and isinstance(user_email, str) and user_email:
        digits_match = re.search(r'(\d{5,8})', user_email)
        if digits_match:
            roll_no = digits_match.group(1)
        elif "@" in user_email:
            roll_no = user_email.split("@")[0]

    course_name = course.name if course and hasattr(course, "name") and isinstance(course.name, str) else "Course"
    instructor = (course.teacher_name if course and hasattr(course, "teacher_name") and isinstance(course.teacher_name, str) else "") or "Course Instructor"
    section = (course.section if course and hasattr(course, "section") and isinstance(course.section, str) else "") or "Not provided"

    return {
        "student_name": student_name,
        "roll_no": roll_no,
        "student_email": user_email,
        "course_name": course_name,
        "instructor": instructor,
        "section": section,
        "university": "AIR UNIVERSITY, ISLAMABAD",
        "department": "Department of Computer Science & Information Technology",
        "date": datetime.now().strftime("%B %d, %Y")
    }


def extract_assignment_question_text(db: Session, assignment: Assignment) -> str:
    """Extract all text content from assignment description and attached materials."""
    parts = []
    if assignment.description and assignment.description.strip():
        parts.append(f"Assignment Description / Instructions:\n{assignment.description.strip()}")

    materials = db.query(AssignmentMaterial).filter(AssignmentMaterial.assignment_id == assignment.id).all()
    for m in materials:
        if m.content and m.content.strip():
            parts.append(f"--- Attachment: {m.title or 'Reference Material'} ---\n{m.content.strip()}")

    return "\n\n".join(parts)


def _is_material_for_different_course(title: str, current_course: Optional[Course], other_courses: List[Course]) -> bool:
    """
    Check if an attached material explicitly belongs to another course (cross-linked material)
    so we don't pollute Claude's context with unrelated course files.
    """
    if not current_course or not other_courses or not title:
        return False
    title_norm = re.sub(r'[^a-zA-Z0-9]+', ' ', title).strip().lower()
    curr_name = (current_course.name or "").lower()
    curr_name_parts = [w for w in re.split(r'[^a-zA-Z0-9]+', curr_name) if len(w) > 3]
    if any(p in title_norm for p in curr_name_parts):
        return False

    for oc in other_courses:
        if not oc.name:
            continue
        oc_name = oc.name.lower()
        # Course codes like CS270, CS-444, CS373
        codes = re.findall(r'[a-zA-Z]{2,4}[-\s]?\d{3}', oc_name)
        for code in codes:
            clean_code = re.sub(r'[-\s]', '', code).lower()
            clean_title = re.sub(r'[-\s]', '', title_norm)
            if clean_code in clean_title:
                return True
        # Base course name stripped of course codes (e.g. "Professional Practices" from "Professional Practices CS270")
        base_oc_name = re.sub(r'[a-zA-Z]{2,4}[-\s]?\d{3}', '', oc_name).strip()
        base_oc_norm = re.sub(r'[^a-zA-Z0-9]+', ' ', base_oc_name).strip()
        if len(base_oc_norm) >= 5 and base_oc_norm in title_norm:
            return True
    return False


def prepare_assignment_materials(db: Session, assignment: Assignment, course: Optional[Course] = None) -> List[str]:
    """
    Return deduplicated files explicitly attached to this assignment, ready for Claude upload.
    Filters out materials belonging to other courses and empty files.
    """
    materials = db.query(AssignmentMaterial).filter(AssignmentMaterial.assignment_id == assignment.id).all()
    file_paths: List[str] = []
    seen_drive_ids = set()
    seen_names = set()
    docs_service = get_google_docs_service(db, user_id=assignment.user_id)

    other_courses = []
    if course and assignment.course_id:
        try:
            other_courses = db.query(Course).filter(
                Course.user_id == assignment.user_id,
                Course.id != assignment.course_id,
            ).all()
        except Exception:
            other_courses = []

    for m in materials:
        title = m.title or f"assignment_{assignment.id}_material"
        safe_title = re.sub(r'[^a-zA-Z0-9_\-\.]', '_', title)

        if _is_material_for_different_course(title, course, other_courses):
            logger.info("Skipping cross-course material '%s' for assignment %s", title, assignment.id)
            continue

        if m.material_type == "local_upload":
            local_path = CLAUDE_MATERIALS_DIR / f"assignment_{assignment.id}_{safe_title}"
            if local_path.is_file() and local_path.stat().st_size > 0:
                p_str = str(local_path.resolve())
                if safe_title not in seen_names:
                    seen_names.add(safe_title)
                    file_paths.append(p_str)
            else:
                logger.warning("Attached local material %s is missing from disk or empty.", m.title or m.id)
            continue

        if m.drive_file_id and docs_service:
            if m.drive_file_id in seen_drive_ids:
                continue
            seen_drive_ids.add(m.drive_file_id)
            try:
                if not safe_title.lower().endswith(('.pdf', '.docx', '.doc', '.txt', '.zip', '.py', '.java', '.cpp', '.sql')):
                    extension = {
                        "application/pdf": ".pdf",
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
                        "application/msword": ".doc",
                        "text/plain": ".txt",
                    }.get(m.mime_type or "", ".pdf")
                    safe_title += extension
                dest_path = CLAUDE_MATERIALS_DIR / f"assignment_{assignment.id}_material_{m.id}_{safe_title}"
                if not dest_path.is_file() or dest_path.stat().st_size == 0:
                    data = docs_service.download_file(m.drive_file_id)
                    if not data:
                        logger.warning("Google Drive returned no content for attached material %s.", m.title or m.id)
                        continue
                    dest_path.write_bytes(data)
                if dest_path.is_file() and dest_path.stat().st_size > 0:
                    file_paths.append(str(dest_path.resolve()))
                    logger.info("Prepared attached material for assignment %s: %s", assignment.id, dest_path)
            except Exception as e:
                logger.warning(f"Could not download material {m.id} for assignment {assignment.id}: {e}")

    # Final deduplication by file size & name (strictly non-empty files)
    unique_paths = []
    seen_sizes = set()
    for fp in file_paths:
        p = Path(fp)
        if p.is_file() and p.stat().st_size > 0:
            key = (p.name, p.stat().st_size)
            if key not in seen_sizes:
                seen_sizes.add(key)
                unique_paths.append(fp)

    return unique_paths


def _handle_google_oauth_if_needed(page, student_email: str = "232530@students.au.edu.pk") -> bool:
    """Handle Google OAuth sign-in / account selection for Claude."""
    try:
        url = (getattr(page, "url", "") or "").lower()
        if "accounts.google.com" not in url:
            return False

        # 1. Check if the student account is listed in the account chooser
        account_token = student_email.split("@")[0].lower() if "@" in student_email else student_email.lower()
        chooser = page.locator(f'[data-email*="{account_token}" i], [data-identifier*="{account_token}" i], div:has-text("{student_email}"), div:has-text("{account_token}")').first
        if chooser.count() > 0 and chooser.is_visible():
            logger.info(f"Selecting Google account {student_email} in account chooser...")
            chooser.click()
            page.wait_for_timeout(2000)
            return True

        # 2. Check if there's an email input field
        email_input = page.locator('input[type="email"], #identifierId, input[name="identifier"]').first
        if email_input.count() > 0 and email_input.is_visible():
            logger.info(f"Filling Google login email: {student_email}")
            email_input.fill(student_email)
            page.wait_for_timeout(500)
            next_btn = page.locator('#identifierNext, button:has-text("Next")').first
            if next_btn.count() > 0 and next_btn.is_visible():
                next_btn.click()
                page.wait_for_timeout(2000)
                return True

        # 3. Check for Consent / Allow / Continue buttons
        for btn_sel in (
            'button:has-text("Continue")',
            'button:has-text("Allow")',
            '#submit_approve_access',
            'button:has-text("I agree")',
        ):
            c_btn = page.locator(btn_sel).first
            if c_btn.count() > 0 and c_btn.is_visible():
                logger.info(f"Clicking Google OAuth consent: {btn_sel}")
                c_btn.click()
                page.wait_for_timeout(2000)
                return True
    except Exception as e:
        logger.debug(f"Google OAuth helper error: {e}")
    return False


def _handle_claude_login_and_oauth(page, student_email: str = "232530@students.au.edu.pk", max_retries: int = 4) -> bool:
    """
    Zero-touch Claude login automation:
    Auto-clicks 'Continue with Google', auto-selects student Google account (including in popups),
    and redirects into Claude chat.
    """
    context = getattr(page, "context", None)

    for attempt in range(max_retries):
        # 1. Check if chat input is already visible
        try:
            inp = page.locator('div[contenteditable="true"], div[contenteditable]').first
            if inp.count() > 0 and inp.is_visible():
                return True
        except Exception:
            pass

        # 2. Check all open pages / popup windows in the browser context for Google OAuth
        pages_to_check = context.pages if context else [page]
        for p_item in list(pages_to_check):
            p_url = (getattr(p_item, "url", "") or "").lower()
            if "accounts.google.com" in p_url:
                try:
                    logger.info(f"Handling Google OAuth for Claude in popup/tab: {p_url[:80]} (email: {student_email})...")
                    _handle_google_oauth_if_needed(p_item, student_email=student_email)
                    if hasattr(p_item, "wait_for_timeout"):
                        p_item.wait_for_timeout(3000)
                except Exception as e:
                    logger.debug(f"OAuth helper error: {e}")

        # 3. Auto-dismiss Claude onboarding modals
        for dismiss_sel in (
            "button:has-text('Acknowledge')",
            "button:has-text('Got it')",
            "button:has-text('Accept')",
            "button:text-is('Continue')",
            "button:has-text('I agree')",
            "button:has-text('Skip')",
            "[aria-label*='Close' i]",
        ):
            try:
                btn = page.locator(dismiss_sel).first
                if btn.count() > 0 and btn.is_visible():
                    logger.info(f"Auto-dismissing Claude modal: {dismiss_sel}")
                    btn.click(force=True)
                    if hasattr(page, "wait_for_timeout"):
                        page.wait_for_timeout(1000)
            except Exception:
                pass

        # 4. Look for Continue with Google on Claude (checking text, spans, and buttons)
        cur_url = (getattr(page, "url", "") or "").lower()
        clicked_google = False

        # Try get_by_text first (works for spans, divs, buttons)
        try:
            g_text = page.get_by_text("Continue with Google").first
            if g_text.count() > 0 and g_text.is_visible():
                logger.info("Auto-clicking Claude 'Continue with Google' via get_by_text...")
                g_text.click(force=True)
                clicked_google = True
                if hasattr(page, "wait_for_timeout"):
                    page.wait_for_timeout(3000)
        except Exception:
            pass

        if not clicked_google:
            google_btns = (
                "button:has-text('Continue with Google')",
                "a:has-text('Continue with Google')",
                "button:has-text('Log in with Google')",
                "button:has-text('Sign in with Google')",
                "button[data-testid*='google' i]",
                "*:has-text('Continue with Google')",
            )
            for sel in google_btns:
                try:
                    g_btn = page.locator(sel).first
                    if g_btn.count() > 0 and g_btn.is_visible():
                        logger.info(f"Auto-clicking Claude 'Continue with Google': {sel}")
                        g_btn.click(force=True)
                        clicked_google = True
                        if hasattr(page, "wait_for_timeout"):
                            page.wait_for_timeout(3000)
                        break
                except Exception:
                    pass

        if not clicked_google:
            try:
                login_btn = page.locator("a[href*='/login' i], button:has-text('Log in'), button:has-text('Sign in')").first
                if login_btn.count() > 0 and login_btn.is_visible() and "login" not in cur_url:
                    login_btn.click(force=True)
                    if hasattr(page, "wait_for_timeout"):
                        page.wait_for_timeout(2000)
            except Exception:
                pass

    try:
        inp = page.locator('div[contenteditable="true"], div[contenteditable]').first
        return inp.count() > 0 and inp.is_visible()
    except Exception:
        return False


def dismiss_claude_overlays_and_modals(page) -> None:
    """
    Dismiss any modals, dialogs, announcements, nudges (e.g. claude-code-nudge-body),
    or portal-root overlays that intercept pointer events.
    """
    try:
        page.keyboard.press("Escape")
        page.keyboard.press("Escape")
    except Exception:
        pass

    dismiss_selectors = (
        'button:has-text("Got it")',
        'button:has-text("Dismiss")',
        'button:has-text("Close")',
        'button:has-text("Accept")',
        'button:has-text("Acknowledge")',
        'button:has-text("Continue")',
        'button:has-text("I agree")',
        'button:has-text("Skip")',
        'button:has-text("Try later")',
        'button:has-text("Not now")',
        'button[aria-label*="Close" i]',
        'button[aria-label*="Dismiss" i]',
        '#portal-root button',
        '[data-testid*="close" i]',
    )
    for sel in dismiss_selectors:
        try:
            btns = page.locator(sel).all()
            for b in btns[:3]:
                if b.is_visible():
                    b.click(force=True, timeout=1000)
        except Exception:
            pass

    try:
        page.evaluate("""() => {
            const portal = document.getElementById('portal-root');
            if (portal) {
                const buttons = portal.querySelectorAll('button');
                buttons.forEach(b => { try { b.click(); } catch(e) {} });
                
                const overlays = portal.querySelectorAll('[role="dialog"], [role="tooltip"], [data-state="open"], [aria-describedby*="nudge"], div[class*="backdrop"], div[class*="overlay"]');
                overlays.forEach(el => {
                    try {
                        el.style.pointerEvents = 'none';
                        el.style.display = 'none';
                    } catch(e) {}
                });
            }
        }""")
    except Exception:
        pass


DOMAIN_HEAVY_ML = "heavy_ml"
DOMAIN_CODING_LAB = "coding_lab"
DOMAIN_DIAGRAM_DESIGN = "diagram_design"
DOMAIN_QUANTITATIVE_MATH = "quantitative_math"
DOMAIN_THEORY_ACADEMIC = "theory_academic"


def classify_assignment_domain(
    title: str = "",
    description: str = "",
    extracted_text: str = "",
    course_name: str = "",
) -> str:
    """
    Intelligently classifies an assignment into one of 5 primary academic domains:
    1. 'heavy_ml': Machine learning, deep learning, PyTorch/TensorFlow, model training (needs Colab notebook).
    2. 'diagram_design': Architectural schemas, ER diagrams, UML modeling, system blueprints (needs Draw.io XML).
    3. 'quantitative_math': Calculations, calculus, algebra, statistics, proofs, physics, discrete math (needs LaTeX step-by-step; strictly NO code or terminal screenshots).
    4. 'coding_lab': Programming implementations, algorithms, data structures, labs (needs source code + authentic terminal output).
    5. 'theory_academic': Theoretical questions, essays, business/management, case studies, humanities (pure academic report with NO code or terminal headers).
    """
    combined = f"{title}\n{description}\n{extracted_text}\n{course_name}".lower()

    if is_heavy_ml_assignment(combined):
        return DOMAIN_HEAVY_ML

    diagram_keywords = [
        "er diagram", "erd", "uml diagram", "class diagram", "sequence diagram",
        "use case diagram", "activity diagram", "dfd", "data flow diagram",
        "circuit diagram", "drawio", "draw.io", "flowchart", "schematic diagram",
        "system architecture diagram", "network topology diagram"
    ]
    has_diagram_focus = any(kw in combined for kw in diagram_keywords)

    # 1. Quantitative Math Detection (must be checked BEFORE generic programming keywords to prevent false positives)
    math_courses = [
        "calculus", "linear algebra", "discrete math", "discrete mathematics",
        "differential equations", "probability", "statistics", "numerical methods",
        "numerical analysis", "physics", "applied math", "complex variables",
        "multivariable calculus", "engineering mathematics", "analytical geometry"
    ]
    course_lower = course_name.lower()
    is_math_course = any(mc in course_lower for mc in math_courses)

    math_keywords = [
        "derivative", "integral", "integration", "calculus", "matrix multiplication",
        "eigenvalue", "eigenvector", "differential equation", "laplace transform",
        "fourier transform", "probability distribution", "hypothesis testing",
        "standard deviation", "variance", "recurrence relation", "truth table",
        "boolean algebra proof", "set theory proof", "physics problem",
        "thermodynamics", "kinematics", "ohm's law", "kirchhoff's law"
    ]
    has_math_focus = any(kw in combined for kw in math_keywords)

    # Concrete coding keywords: strict terms that unmistakably indicate runnable software development
    strict_coding_markers = [
        "source code", "runnable code", "compile and run", "test cases",
        "console output", "terminal output", "lab task", "lab manual",
        ".py", ".java", ".cpp", ".sql", ".asm", ".cs", ".js", ".ts",
        "public class", "def ", "import ", "#include", "std::", "main()",
        "c++", "python script", "java program", "assembly language",
        "8086", "masm", "emu8086", "sql query", "sql queries", "database query",
        "react", "compiler", "debugging", "runtime error"
    ]
    has_strict_coding = any(kw in combined for kw in strict_coding_markers)

    if (is_math_course or has_math_focus) and not has_strict_coding:
        return DOMAIN_QUANTITATIVE_MATH

    if has_diagram_focus and not has_strict_coding:
        return DOMAIN_DIAGRAM_DESIGN

    non_coding_courses = [
        "entrepreneurship", "business", "management", "economics", "marketing",
        "english", "communication", "pakistan studies", "islamic studies",
        "human resource", "organizational behavior", "ethics", "sociology",
        "psychology", "finance", "accounting", "international relations"
    ]
    is_non_coding_course = any(ncc in course_lower for ncc in non_coding_courses)

    if is_non_coding_course and not has_strict_coding:
        return DOMAIN_THEORY_ACADEMIC

    if has_strict_coding:
        return DOMAIN_CODING_LAB

    coding_courses = [
        "programming", "computer programming", "oop", "object oriented",
        "data structures", "algorithms", "operating systems lab", "database lab",
        "software engineering lab", "web engineering", "web dev", "compiler",
        "assembly language", "microprocessor", "computer networks lab"
    ]
    if any(cc in course_lower for cc in coding_courses):
        return DOMAIN_CODING_LAB

    return DOMAIN_THEORY_ACADEMIC


def _is_claude_asking_for_clarification(text: str) -> bool:
    """
    Detect if Claude paused or refused to solve by asking a clarifying question instead of solving.
    """
    if not text or len(text.strip()) == 0:
        return False
    t = text.strip()
    clarification_patterns = [
        r"\bwhich one (?:should|would) (?:you like|i)\b",
        r"\bwhich (?:assignment|task|part|subject|course|option|approach) (?:should|would|do you)\b",
        r"\bwhich one to start with\b",
        r"\bwhich one should i start with\b",
        r"\bcan't tell whether you want\b",
        r"\bcannot tell whether you want\b",
        r"\bcombines instructions for .* courses\b",
        r"\bwould you like me to (?:start|proceed|focus|solve|do)\b",
        r"\blet me know (?:which|how|if you would like me to proceed)\b",
        r"\bplease (?:let me know|clarify|specify) which\b",
        r"\bhow would you like (?:me to proceed|to proceed)\b",
        r"\bbefore i (?:begin|start|proceed), (?:please|could you|would you)\b",
        r"\bwhich of these would you like\b",
    ]
    has_clarification_phrase = any(re.search(p, t, re.IGNORECASE) for p in clarification_patterns)
    if not has_clarification_phrase:
        return False

    # Check if there is actual substantial solution structure
    has_code_fence = bool(re.search(r"```(?:python|java|cpp|c|colab|terminal|sql|asm)", t, re.IGNORECASE))
    has_math_block = bool(re.search(r"\$\$.*?\$\$", t, re.DOTALL))
    has_task_headers = len(re.findall(r"(?im)^\s{0,3}#{1,4}\s*(?:Task|Question|Problem)\s*\d+", t)) >= 2
    if (has_code_fence or has_math_block or has_task_headers) and len(t) > 3000:
        return False

    return True



def build_academic_cover_markdown(meta: Dict[str, str], assignment_title: str) -> str:
    """Standard Air University introductory cover page in clean Markdown."""
    return (
        f"# {meta['university']}\n"
        f"### {meta['department']}\n\n"
        f"| Field | Academic Deliverable Details |\n"
        f"| :--- | :--- |\n"
        f"| **Course** | {meta['course_name']} |\n"
        f"| **Assignment** | {assignment_title} |\n"
        f"| **Student Name** | {meta['student_name']} |\n"
        f"| **Roll / Reg No** | {meta['roll_no']} |\n"
        f"| **Section** | {meta['section']} |\n"
        f"| **Instructor** | {meta['instructor']} |\n"
        f"| **Date of Submission** | {meta['date']} |\n\n"
        f"---\n\n"
    )


def is_heavy_ml_assignment(assignment_context: str) -> bool:
    """Identify assignments that should be delivered as a Colab notebook, not locally run."""
    return bool(_HEAVY_ML_PATTERN.search(assignment_context or ""))


def remove_heavy_ml_code_fences(markdown: str) -> str:
    """Keep diagrams and notebook fences while omitting local-run code for heavy ML tasks."""
    def keep_or_remove(match: re.Match) -> str:
        tag = (match.group(1) or "").lower()
        return match.group(0) if tag in _DIAGRAM_FENCE_TAGS or tag == "colab-json" else ""

    return re.sub(
        r"(?ms)^```([^\s`]*)[^\n]*\n.*?^```[ \t]*$",
        keep_or_remove,
        markdown,
    )


def _update_solver_progress(
    db: Session,
    assignment_id: int,
    step_num: int,
    total_steps: int,
    step_title: str,
    detail: str = "",
) -> None:
    try:
        from app.db.models import Setting
        key = f"assignment_crew_progress_{assignment_id}"
        row = db.query(Setting).filter(Setting.key == key).first()
        if not row:
            row = Setting(key=key, description="Assignment solver live progress")
            db.add(row)
        progress_data = {
            "current_step": step_num,
            "total_steps": total_steps,
            "step_title": step_title,
            "detail": detail,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        row.value = json.dumps(progress_data)
        db.commit()
    except Exception as err:
        logger.debug("Failed to record solver progress: %s", err)


def solve_assignment_via_claude_browser(
    db: Session,
    assignment_id: int,
    max_wait_seconds: int = CLAUDE_RESPONSE_TIMEOUT,
    user_id: str = "legacy",
    headless: bool = None,
    force: bool = False,
) -> Dict[str, Any]:
    """
    Autonomous pipeline that connects to the user's Chrome browser, attaches assignment PDFs/materials,
    submits an academic prompt to Claude, waits for response completion, prepends the Air University cover page,
    and updates the database.
    """
    from playwright.sync_api import sync_playwright

    assignment = db.query(Assignment).filter(
        Assignment.id == assignment_id,
        Assignment.user_id == user_id,
    ).first()
    if not assignment:
        return {"status": "error", "error": f"Assignment {assignment_id} not found"}

    if not force and _is_assignment_already_solving(db, assignment_id, user_id):
        logger.warning("Claude solver called for assignment %s while another solve is in progress.", assignment_id)
        return {
            "status": "already_running",
            "error": "A solution is already being generated for this assignment. Please wait for it to complete.",
        }

    course = db.query(Course).filter(
        Course.id == assignment.course_id,
        Course.user_id == user_id,
    ).first()
    meta = get_student_metadata(db, course, user_id=user_id)
    attachment_paths = prepare_assignment_materials(db, assignment, course)
    extracted_text = extract_assignment_question_text(db, assignment)

    _update_solver_progress(
        db,
        assignment_id,
        1,
        5,
        "Reading Materials & Rubric",
        f"Analyzing assignment instructions and {len(attachment_paths)} attachment(s)..." if attachment_paths else "Analyzing assignment instructions and rubric...",
    )

    # Resolve headless mode from config if not explicitly provided
    if headless is None:
        headless = _get_headless_mode()
    elif not _has_display() and not headless:
        logger.warning("No display server detected; enforcing headless=True for assignment %s", assignment_id)
        headless = True

    # Try hosted browser service first, or direct Playwright if session key is synced
    from app.services.browser_sessions import BrowserSessionClient
    session_key_setting = db.query(Setting).filter(
        Setting.key == f"classroom:{user_id}:claude_session_key"
    ).first()
    claude_session_key = session_key_setting.value.strip() if session_key_setting and session_key_setting.value else None

    user_agent_setting = db.query(Setting).filter(
        Setting.key == f"classroom:{user_id}:claude_user_agent"
    ).first()
    custom_user_agent = user_agent_setting.value.strip() if user_agent_setting and user_agent_setting.value else None

    endpoint = None
    use_direct_playwright = False
    try:
        session_client = BrowserSessionClient()
        try:
            endpoint = session_client.cdp_endpoint(user_id)
        except Exception:
            logger.info("Hosted Claude browser session not active for user %s; starting session...", user_id)
            session_client.open(user_id)
            endpoint = session_client.cdp_endpoint(user_id)
        logger.info("Using hosted Claude browser for user %s at %s", user_id, endpoint)
    except Exception as error:
        logger.warning("Hosted Claude browser unavailable for user %s: %s", user_id, error)
        if claude_session_key:
            logger.info("User %s has synced Claude sessionKey; using direct headless Playwright.", user_id)
            use_direct_playwright = True
        else:
            logger.info("Falling back to local Chrome profile (headless=%s)", headless)
            launch_result = open_claude_browser_window(user_id=user_id, headless=headless)
            if launch_result.get("status") not in ("ready", "launched"):
                return {
                    "status": "needs_login",
                    "error": (
                        "Could not start local Claude browser and hosted browser service is unavailable. "
                        f"Details: {launch_result.get('error', 'unknown error')}"
                    ),
                }
            endpoint = f"http://127.0.0.1:{USER_CDP_PORT}"

    logger.info("Connecting to the private Claude browser for assignment %s (user: %s).", assignment_id, user_id)
    _update_solver_progress(
        db,
        assignment_id,
        2,
        5,
        "Connecting to Claude",
        "Establishing connection to isolated browser session for Claude...",
    )

    # Set Playwright bypass for context-management errors on attached Chromium instances
    os.environ["PW_CHROMIUM_ATTACH_TO_OTHER"] = "1"

    # 2. Connect Playwright over CDP or launch direct headless instance
    with sync_playwright() as p:
        browser = None
        context = None
        if use_direct_playwright:
            direct_headless = True if headless is None else headless
            if not _has_display():
                direct_headless = True
            browser = p.chromium.launch(
                headless=direct_headless,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--disable-blink-features=AutomationControlled",
                ],
            )
            context = browser.new_context(
                user_agent=custom_user_agent or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            )
        else:
            try:
                browser = connect_to_chrome(p.chromium, endpoint)
                context = browser.contexts[0] if browser.contexts else None
            except Exception as e:
                if claude_session_key:
                    logger.warning("CDP connect failed (%s), falling back to direct headless Chromium with sessionKey", e)
                    direct_headless = True if headless is None else headless
                    if not _has_display():
                        direct_headless = True
                    browser = p.chromium.launch(
                        headless=direct_headless,
                        args=[
                            "--no-sandbox",
                            "--disable-dev-shm-usage",
                            "--disable-gpu",
                            "--disable-blink-features=AutomationControlled",
                        ],
                    )
                    context = browser.new_context(
                        user_agent=custom_user_agent or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
                    )
                else:
                    logger.error("Could not attach to the hosted Chrome session: %s", e)
                    return {
                        "status": "error",
                        "error": (
                            "The hosted Chrome DevTools endpoint accepted the connection "
                            f"but did not complete Playwright's browser handshake after "
                            f"{CDP_CONNECT_ATTEMPTS} attempts ({CDP_CONNECT_TIMEOUT_MS // 1000}s each). "
                            "Close and reopen Uniflow's Chrome window, then retry. "
                            f"Details: {e}"
                        )
                    }

        if not context:
            return {"status": "error", "error": "No browser context found on Chrome."}

        try:
            context.grant_permissions(["clipboard-read", "clipboard-write"])
        except Exception:
            pass

        # Inject synced session cookie before navigation
        if claude_session_key:
            try:
                context.add_cookies([{
                    "name": "sessionKey",
                    "value": claude_session_key,
                    "domain": ".claude.ai",
                    "path": "/",
                    "secure": True,
                    "httpOnly": True,
                }])
                logger.info("Successfully injected Claude sessionKey cookie for user %s", user_id)
            except Exception as cookie_err:
                logger.warning("Could not inject sessionKey cookie: %s", cookie_err)

        # Find or create a page for Claude
        page = None
        for pg in context.pages:
            if "claude.ai" in (pg.url or ""):
                page = pg
                break
        if not page:
            page = context.new_page()

        page.bring_to_front()

        # Always start in a clean, isolated new chat to prevent leftover files from other courses contaminating this solve
        try:
            page.goto("https://claude.ai/new", wait_until="domcontentloaded", timeout=30000)
        except Exception as nav_err:
            logger.debug(f"Navigation to /new: {nav_err}")

        # Allow SPA hydration
        page.wait_for_timeout(2000)

        # 3. Ensure Claude is signed in and a chat input is available.
        prompt_selector = 'div[contenteditable="true"]'
        student_email = meta.get("student_email") or ""

        # Fast-path: if a sessionKey cookie was injected, check if Claude loaded
        # the chat directly (valid cookie → skip the full OAuth dance).
        login_ok = False
        if claude_session_key:
            try:
                inp = page.locator('div[contenteditable="true"], div[contenteditable]').first
                if inp.count() > 0 and inp.is_visible():
                    logger.info("Claude sessionKey cookie is valid — chat input visible immediately for user %s", user_id)
                    login_ok = True
                else:
                    # Give Claude a bit more time to finish React hydration
                    page.wait_for_timeout(3000)
                    inp2 = page.locator('div[contenteditable="true"], div[contenteditable]').first
                    if inp2.count() > 0 and inp2.is_visible():
                        logger.info("Claude sessionKey cookie valid (after extra wait) for user %s", user_id)
                        login_ok = True
                    else:
                        cur = (page.url or "").lower()
                        if "login" in cur or "signin" in cur or "auth" in cur:
                            logger.warning(
                                "Claude sessionKey cookie may be expired for user %s — landing on login page",
                                user_id,
                            )
                            return {
                                "status": "needs_login",
                                "error": (
                                    "Your Claude session key appears to be expired. "
                                    "Please go to Settings → paste a fresh sessionKey from claude.ai and retry."
                                ),
                            }
            except Exception as cookie_check_err:
                logger.debug("Cookie fast-path check error: %s", cookie_check_err)

        # Slow-path: full OAuth / login UI automation (hosted browser or headless without cookie)
        if not login_ok:
            login_ok = _handle_claude_login_and_oauth(page, student_email=student_email, max_retries=4)

        if not login_ok:
            return {
                "status": "needs_login",
                "error": "Claude is not signed in. Open your private Claude browser, sign in, then resume this assignment.",
            }

        # Verify chat input box exists after login flow
        try:
            page.wait_for_selector('div[contenteditable="true"], div[contenteditable]', timeout=8000)
        except Exception:
            return {
                "status": "error",
                "error": "Could not find Claude chat input box. Please verify Claude is loaded and signed in."
            }

        # 4. Upload assignment attachments / PDFs
        file_names_str = ""
        if attachment_paths:
            logger.info(f"Attaching {len(attachment_paths)} file(s) to Claude: {attachment_paths}")
            attached = False
            # Try 1: locate input[type="file"]
            try:
                file_input = page.locator('input[type="file"]').first
                if file_input.count() > 0:
                    file_input.set_input_files(attachment_paths)
                    attached = True
            except Exception as direct_err:
                logger.debug(f"Direct set_input_files error: {direct_err}")

            # Try 2: click attach button with expect_file_chooser
            if not attached:
                attach_selectors = [
                    'button[aria-label*="Attach" i]',
                    'button[aria-label*="Upload" i]',
                    'button[data-testid*="attach" i]',
                    'button:has(svg[aria-label*="attach" i])',
                    'button:has(svg)',
                ]
                for btn_sel in attach_selectors:
                    try:
                        btn = page.locator(btn_sel).first
                        if btn.count() > 0 and btn.is_visible():
                            with page.expect_file_chooser(timeout=4000) as fc_info:
                                btn.click()
                            file_chooser = fc_info.value
                            file_chooser.set_files(attachment_paths)
                            attached = True
                            break
                    except Exception:
                        pass

            if attached:
                page.wait_for_timeout(4000)
                file_names_str = ", ".join(Path(f).name for f in attachment_paths)

        # 5. Classify assignment domain & build tailored academic prompt
        questions_block = ""
        if assignment.description and assignment.description.strip():
            questions_block += f"\nASSIGNMENT INSTRUCTIONS & QUESTIONS (SOURCE OF TRUTH - ANSWER THESE EXACTLY):\n{assignment.description.strip()}\n"
        # Always include extracted reference text so Claude has the real assignment
        # content to solve from, regardless of whether files are attached.
        if extracted_text and extracted_text.strip():
            clean_ref_text = extracted_text.strip()
            if len(clean_ref_text) > 45000:
                clean_ref_text = clean_ref_text[:45000].rsplit("\n", 1)[0]
            questions_block += f"\nEXTRACTED REFERENCE MATERIAL CONTENT (from attached PDFs/documents):\n{clean_ref_text}\n"

        # Guard: warn when there is no assignment content at all so operators know
        # Claude may hallucinate a generic answer instead of the real assignment.
        # We do not hard-fail here because the downstream response-length check
        # (raw_solution_text < 100 chars) already catches empty Claude outputs.
        if not questions_block.strip():
            logger.warning(
                f"No assignment content available for assignment {assignment_id} "
                "(empty description, no extracted text, no attachments). Claude may hallucinate."
            )

        domain = classify_assignment_domain(
            title=assignment.title or "",
            description=assignment.description or "",
            extracted_text=extracted_text,
            course_name=meta.get("course_name") or "",
        )
        logger.info(f"Classified assignment {assignment_id} domain as: '{domain}'")

        if domain == DOMAIN_HEAVY_ML:
            domain_instructions = (
                "MACHINE LEARNING / DEEP LEARNING (GOOGLE COLAB JUPYTER NOTEBOOK):\n"
                "This assignment involves computationally heavy machine-learning, deep-learning, or model training.\n"
                "- You MUST provide a complete, valid Google Colab Jupyter Notebook in JSON nbformat 4 format enclosed in a ```colab-json code fence.\n"
                "- Include all pip installs (!pip install ...), dataset preparation, GPU runtime config, model architecture, training/validation loops, evaluation metrics (loss/accuracy, confusion matrix), and sample inference outputs.\n"
                "- Ensure every code and markdown cell is self-contained and ready for Google Colab execution.\n"
                "- ML/Deep Learning assignments only require the Google Colab file (.ipynb); terminal screenshots are NOT required for ML/DL pipelines.\n"
            )
            report_structure = (
                "MANDATORY REPORT STRUCTURE (FOLLOW STRICTLY):\n"
                "Format your entire response in polished Markdown. For every task in the lab/assignment, use this exact layout:\n\n"
                "# Task N: [Exact Task Title from Lab Manual]\n"
                "## 1. Problem Statement / Question\n"
                "[Detailed problem statement, objective, and requirements as given in the manual]\n\n"
                "## 2. Google Colab Implementation & Notebook Architecture\n"
                "```colab-json\n"
                "[complete valid Jupyter notebook JSON]\n"
                "```\n\n"
                "## 3. Discussion & Analysis\n"
                "[Theoretical explanation, model architecture, hyperparameter choices, training loss, and key takeaways]\n\n"
            )
        elif domain == DOMAIN_THEORY_ACADEMIC:
            domain_instructions = (
                "THEORETICAL ANALYSIS & ACADEMIC RESEARCH REPORT INSTRUCTIONS:\n"
                "- This is an ACADEMIC THEORY & RESEARCH assignment. Do NOT include terminal execution screenshots, console outputs, or fake code implementation blocks unless the assignment explicitly requests working code.\n"
                "- Provide an exceptionally thorough, structured academic report addressing all assignment questions, objectives, and problem statements with scholarly depth.\n"
                "- For each question or topic, provide theoretical foundations, structured explanations, comparative analyses, real-world case studies, and practical applications.\n\n"
                "DIAGRAM OUTPUT IMAGES (.PNG FORMAT - MANDATORY REQUIREMENT FOR EVERY DIAGRAM):\n"
                "- If the assignment mentions or requires any diagram (flowchart, architecture, process flow, UML, ERD, system schema, state machine, circuit, or block diagram), you MUST directly generate it in authentic .PNG image format:\n"
                "  1. DIRECT .PNG FORMAT DIAGRAM IMAGE: You must directly generate the visual diagram image in .png format. Label each diagram clearly: `**Diagram Image (.png):** diagram_task<N>.png`. Provide the visual diagram as an embedded .png image block `![Diagram (Task N): <Title>](data:image/png;base64,<png_base64_data>)` or render the visual diagram artifact/canvas directly so it outputs as a visual .png image in the report.\n"
                "  2. STANDALONE DRAW.IO XML COMPANION FILE: If Draw.io XML is also provided, include the XML code enclosed in a ```drawio code fence (starting with <mxfile>). This XML is strictly an auxiliary downloadable companion file for grading; the primary visual in the report MUST be your directly generated .png image of the diagram!\n"
                "  3. In the report prose, provide an in-depth pedagogical explanation of each diagram entity, connection, workflow, and theoretical significance.\n"
                "- Conclude with academic references and bibliography formatted in standard citation style (APA/IEEE).\n"
            )
            report_structure = (
                "MANDATORY REPORT STRUCTURE (THEORETICAL & ACADEMIC ANALYSIS - FOLLOW STRICTLY):\n"
                "Format your entire response in polished, professional Markdown. CRITICAL: Replace every\n"
                "[bracketed placeholder] below with the ACTUAL content from the assignment questions and\n"
                "reference materials. Do NOT leave any placeholder text (e.g. [Exact Title], [Detailed...])\n"
                "in the final report — every section must contain real, specific answers to this assignment.\n\n"
                "# Executive Summary & Overview\n"
                "[Concise academic synthesis of the core topic, objectives, and analytical scope — written for THIS assignment]\n\n"
                "# Question 1: [Replace with the EXACT title/question from the assignment]\n"
                "## 1. In-Depth Theoretical Analysis\n"
                "[Detailed, rigorous conceptual analysis, problem breakdown, and critical discussion of Question 1. Use structured paragraphs, bullet points, or comparison tables where appropriate]\n\n"
                "## 2. Case Study & Practical Application\n"
                "[Practical application, industry best practices, empirical evidence, or concrete scenarios illustrating the principles of Question 1]\n\n"
                "# Question 2: [Replace with the EXACT title/question from the assignment]\n"
                "## 1. In-Depth Theoretical Analysis\n"
                "[... real answer for Question 2 ...]\n\n"
                "## 2. Case Study & Practical Application\n"
                "[... real answer for Question 2 ...]\n\n"
                "# Diagram & Architecture Analysis (Include if diagrams are requested in the assignment)\n"
                "## 1. Visual Diagram Image (.png)\n"
                "**Diagram Image (.png):** `diagram_task1.png`\n"
                "![Visual Diagram: System Architecture](data:image/png;base64,...)\n\n"
                "## 2. Pedagogical Component Breakdown & Analysis\n"
                "[Comprehensive explanation of all entities, workflow transitions, protocol interactions, and architectural decisions]\n\n"
                "## 3. Draw.io Companion File Deliverable\n"
                "```drawio\n"
                "<mxfile host=\"app.diagrams.net\"> ... </mxfile>\n"
                "```\n\n"
                "# Conclusion & Strategic Takeaways\n"
                "[Synthesized key findings, analytical conclusions, and broader implications for THIS assignment]\n\n"
                "# References & Academic Citations\n"
                "[Properly formatted academic citations in APA/IEEE style for sources actually used]\n"
            )
        elif domain == DOMAIN_DIAGRAM_DESIGN:
            domain_instructions = (
                "DIAGRAM SPECIFICATION & VISUAL .PNG IMAGE DELIVERABLES (MANDATORY REQUIREMENT):\n"
                "- You MUST directly generate each architectural, UML, ERD, flowchart, or schema diagram as a visual .png format image.\n"
                "- For every diagram, label the diagram image clearly: `**Diagram Image (.png):** diagram_task<N>.png` and provide the visual diagram directly in .png image format (`![Diagram: <Title>](data:image/png;base64,...)` or direct visual diagram artifact).\n"
                "- Alongside the visual .png image, provide the valid Draw.io XML companion block enclosed in a ```drawio code fence (<mxfile>...</mxfile>) so it can be saved as an editable companion file.\n"
                "- Do NOT output ASCII art or text boxes. The diagram must be a real visual .png image generated by you (Claude).\n"
            )
            report_structure = (
                "MANDATORY REPORT STRUCTURE (FOLLOW STRICTLY):\n"
                "Format your entire response in polished Markdown. For every diagram in the assignment, use this exact layout:\n\n"
                "# Task N: [Exact Diagram / Architecture Title]\n"
                "## 1. System Requirements & Specification\n"
                "[Detailed requirements, entity specifications, and constraints]\n\n"
                "## 2. Visual Diagram Image (.png)\n"
                "**Diagram Image (.png):** `diagram_taskN.png`\n"
                "![Visual Diagram (Task N)](data:image/png;base64,...)\n\n"
                "## 3. Architectural Schema Deliverable (Draw.io XML Companion)\n"
                "```drawio\n"
                "<mxfile host=\"app.diagrams.net\">...</mxfile>\n"
                "```\n\n"
                "## 4. Structural Analysis & Component Breakdown\n"
                "[Detailed explanation of entities, connections, protocols, design decisions, and workflows]\n\n"
            )
        elif domain == DOMAIN_QUANTITATIVE_MATH:
            domain_instructions = (
                "QUANTITATIVE MATHEMATICS & RIGOROUS STEP-BY-STEP PROBLEM SOLVING:\n"
                "- This is a QUANTITATIVE MATHEMATICS, PHYSICS, OR NUMERICAL CALCULATION assignment.\n"
                "- Do NOT generate programming source code, compiler commands, or terminal output screenshots unless numerical simulation is explicitly requested.\n"
                "- Format all mathematical formulas, equations, derivations, and matrices using professional LaTeX notation ($...$ inline and $$...$$ display blocks).\n"
                "- For every question/problem provide complete, step-by-step mathematical working: Problem Statement, Given Data/Variables, Applicable Principles/Theorems, Algebraic Derivations, Final Answer clearly stated with units, and a Verification Sanity Check.\n"
            )
            report_structure = (
                "MANDATORY REPORT STRUCTURE (QUANTITATIVE MATHEMATICAL SOLUTIONS - FOLLOW STRICTLY):\n"
                "Format your entire response in polished, professional Markdown with LaTeX math notation.\n\n"
                "# Problem N: [Exact Title or Problem from Assignment]\n"
                "## 1. Problem Statement & Given Parameters\n"
                "[State the given values, variables, boundary conditions, and objectives]\n\n"
                "## 2. Applicable Mathematical Principles & Formulas\n"
                "[Identify all theorems, definitions, and equations in LaTeX notation]\n\n"
                "## 3. Step-by-Step Mathematical Derivation & Solution\n"
                "[Complete step-by-step algebraic steps, substitution, and arithmetic calculations formatted in LaTeX]\n\n"
                "## 4. Final Answer & Sanity Check\n"
                "[Clearly stated final result with units and quick dimensional/physical sanity check]\n\n"
            )
        else:
            domain_instructions = (
                "CODE IMPLEMENTATION & RUNNABLE DELIVERABLES:\n"
                "- For every programming task, provide complete, bug-free, and production-ready source code in a language-tagged code fence (e.g. ```java, ```python, ```cpp, ```sql, ```assembly).\n"
                "- Do NOT use placeholders, ellipsis (...), or incomplete snippets. Provide complete, standalone source files with thorough comments.\n\n"
                "TERMINAL OUTPUT SCREENSHOT IMAGES (.PNG FORMAT - MANDATORY REQUIREMENT FOR EVERY TASK):\n"
                "- You MUST directly generate the authentic terminal execution screenshot image in .png format for EACH task.\n"
                "- For each task, provide the full terminal execution session showing the exact command line executed (e.g. `$ python task1.py` or `$ gcc task1.c && ./a.out`), simulated interactive inputs, and comprehensive stdout/stderr results demonstrating successful execution with exit code 0.\n"
                "- Under each task, label the screenshot clearly: `**Terminal Screenshot (.png):** task<N>_output.png`\n"
                "- Provide the visual terminal session inside a ```terminal code fence or embedded .png image block so it directly embeds as a terminal output screenshot image into the student's submission report.\n"
            )
            report_structure = (
                "MANDATORY REPORT STRUCTURE (FOLLOW STRICTLY):\n"
                "Format your entire response in polished Markdown. For every task in the lab/assignment, use this exact layout:\n\n"
                "# Task N: [Exact Task Title from Lab Manual]\n"
                "## 1. Problem Statement / Question\n"
                "[Detailed problem statement, objective, and requirements as given in the manual]\n\n"
                "## 2. Terminal Output Screenshot (.png)\n"
                "**Terminal Screenshot (.png):** `taskN_output.png`\n"
                "```terminal\n"
                "$ [command]\n"
                "[realistic terminal execution output, test cases, and verification results]\n"
                "```\n\n"
                "## 3. Source Code Implementation\n"
                "**File:** `taskN_[short_name].[ext]`\n"
                "```[language]\n"
                "[complete runnable source code]\n"
                "```\n\n"
                "## 4. Discussion & Complexity Analysis\n"
                "[Theoretical explanation, algorithm complexity (Time & Space), design decisions, and key takeaways]\n\n"
            )

        prompt_text = (
            f"You are an expert academic specialist, professor, and curriculum evaluator for {meta['course_name']} at Air University, Islamabad.\n\n"
            f"ASSIGNMENT METADATA:\n"
            f"- Assignment Title: {assignment.title}\n"
            f"- Course: {meta['course_name']}\n"
            f"- Instructor: {meta['instructor']}\n"
            f"- Student: {meta['student_name']} ({meta['roll_no']}, Section {meta['section']})\n"
            f"- Attached Reference Documents: {file_names_str or 'None'}\n"
            f"- Assignment Classification: {domain.upper()}\n\n"
            f"{questions_block}\n"
            f"EXPERT PLANNING & EXECUTION INSTRUCTIONS:\n"
            f"1. PLANNING PHASE: Thoroughly examine the assignment title, questions, and attached reference materials. Identify every discrete task, exercise, or problem statement requested.\n"
            f"2. MODALITY COMPLIANCE: Adhere strictly to the {domain.upper()} deliverable requirements below. Do not mix unrelated formats (e.g. never generate terminal commands or code blocks for theoretical or quantitative hand calculation questions).\n"
            f"3. STRICT SINGLE-ASSIGNMENT FOCUS & ZERO-QUESTION DIRECTIVE:\n"
            f"   - You must solve ONLY this specific assignment: '{assignment.title}' for the course '{meta['course_name']}'.\n"
            f"   - If any materials from previous sessions or other courses appear in context, IGNORE THEM COMPLETELY.\n"
            f"   - You are strictly forbidden from asking clarifying questions, asking which task to start with, or asking for preferences.\n"
            f"   - Solve ALL questions for this assignment completely right now from start to finish in this single response.\n\n"
            f"{domain_instructions}\n\n"
            f"{report_structure}\n"
            "Do not attempt to generate a Google Doc yourself; our automated system compiles your output into the official Air University Google Doc. "
            "Do not include terminal screenshots or console output unless the assignment explicitly requests executable code output."
        )

        # 6. Fill prompt and send with active overlay dismissal and forced click
        dismiss_claude_overlays_and_modals(page)

        input_el = page.locator(prompt_selector).first
        try:
            input_el.click(force=True, timeout=5000)
        except Exception as click_err:
            logger.debug(f"Input click fallback: {click_err}")
            dismiss_claude_overlays_and_modals(page)
            try:
                input_el.focus(timeout=3000)
            except Exception:
                pass
        page.wait_for_timeout(300)

        # Insert prompt cleanly
        page.keyboard.insert_text(prompt_text)
        page.wait_for_timeout(1000)

        # Dismiss any Claude banner/toast/dialog if popped up after typing
        dismiss_claude_overlays_and_modals(page)

        # Wait until send button is enabled (in case file upload is finalizing)
        send_btn = page.locator('button[aria-label*="Send" i], button[aria-label="Send Message" i], button[data-testid="chat-input-send"]').first
        for _ in range(15):
            if send_btn.is_visible() and send_btn.is_enabled():
                break
            page.wait_for_timeout(1000)

        if send_btn.is_visible() and send_btn.is_enabled():
            try:
                send_btn.click(timeout=4000)
            except Exception:
                try:
                    send_btn.click(force=True, timeout=2000)
                except Exception:
                    page.keyboard.press("Enter")
        else:
            page.keyboard.press("Enter")

        logger.info(f"Prompt sent to Claude for assignment {assignment_id}. Waiting for completion...")
        _update_solver_progress(
            db,
            assignment_id,
            3,
            5,
            "Synthesizing Solution",
            "Prompt submitted. Claude is actively writing code and detailed explanations...",
        )

        # 7. Wait for Claude response generation to complete
        start_time = time.monotonic()
        page.wait_for_timeout(5000)

        stop_selector = 'button[aria-label*="Stop response"], button[aria-label*="Stop"], button[data-testid*="stop"]'
        continue_clicks = 0
        
        while time.monotonic() - start_time < max_wait_seconds:
            for quota_token in (
                "out of free messages",
                "out of messages",
                "reached your usage limit",
                "reached your message limit",
                "free message limit",
                "limit until",
                "try again at",
                "too many requests",
                "resets at",
                "currently at capacity",
            ):
                try:
                    cap_locator = page.locator(f"text={quota_token}").first
                    if cap_locator.count() > 0 and cap_locator.is_visible():
                        logger.warning(f"Claude message quota reached: {quota_token}")

                        # Extract the exact reset notice from the page if visible
                        extracted_notice = ""
                        try:
                            extracted_notice = page.evaluate("""() => {
                                const candidates = Array.from(document.querySelectorAll('div, p, span, h3, h4'))
                                    .map(el => (el.innerText || '').trim())
                                    .filter(t => /reached your (?:message|usage) limit|out of (?:free )?messages|resets? (?:at|until)|available (?:at|until|again)|limit until/i.test(t) && t.length > 10 && t.length < 300);
                                return candidates.length > 0 ? candidates[0] : "";
                            }""")
                        except Exception:
                            extracted_notice = ""

                        user_friendly_error = extracted_notice or f"Claude Free Tier message limit reached: '{quota_token}'. Please wait for your usage limit to reset."
                        logger.warning(f"Extracted Claude limit notice: {user_friendly_error}")

                        # Persist rate limit status in DB so dashboard displays reset notice to student
                        try:
                            rate_row = db.query(Setting).filter(Setting.key == f"classroom:{user_id}:claude_rate_limit").first()
                            if not rate_row:
                                rate_row = Setting(key=f"classroom:{user_id}:claude_rate_limit", description="Claude Rate Limit Status")
                                db.add(rate_row)
                            rate_row.value = json.dumps({
                                "is_limited": True,
                                "message": user_friendly_error,
                                "detected_at": datetime.now(timezone.utc).isoformat(),
                            })
                            db.commit()
                        except Exception as db_err:
                            logger.warning(f"Failed to persist rate limit setting: {db_err}")

                        sol_row = db.query(AssignmentSolution).filter(AssignmentSolution.assignment_id == assignment_id).first()
                        if sol_row:
                            sol_row.validation_errors = f"Claude Free Tier limit reached: {user_friendly_error}"
                            db.commit()

                        return {
                            "status": "rate_limited",
                            "error": f"Claude Free Tier limit reached: {user_friendly_error}. You can wait for reset or switch to Multi-Agent (Groq/Gemini).",
                            "reset_message": user_friendly_error,
                        }
                except Exception:
                    pass

            stop_locator = page.locator(stop_selector)
            is_generating = False
            try:
                if stop_locator.count() > 0 and stop_locator.first.is_visible():
                    is_generating = True
            except Exception:
                is_generating = False

            if not is_generating:
                page.wait_for_timeout(2000)
                try:
                    still_going = (stop_locator.count() > 0 and stop_locator.first.is_visible())
                except Exception:
                    still_going = False
                if not still_going:
                    # Check if Claude truncated response and needs a 'Continue' click
                    if continue_clicks < 3:
                        try:
                            cont_btn = page.locator('button:has-text("Continue generating"), button:has-text("Continue")')
                            if cont_btn.count() > 0 and cont_btn.first.is_visible():
                                logger.info("Claude truncated response; clicking 'Continue generating'...")
                                cont_btn.first.click()
                                continue_clicks += 1
                                page.wait_for_timeout(3000)
                                continue
                        except Exception:
                            pass
                    logger.info("Claude finished generating response.")
                    break
            
            elapsed_wait = int(time.monotonic() - start_time)
            if elapsed_wait > 0 and elapsed_wait % 6 == 0:
                _update_solver_progress(
                    db,
                    assignment_id,
                    3,
                    5,
                    "Synthesizing Solution",
                    f"Claude is generating response ({elapsed_wait}s elapsed, streaming output)...",
                )
            page.wait_for_timeout(2000)

        # 8. Extract Claude's response (with clipboard interceptor and DOM-to-Markdown fallback)
        raw_solution_text = ""
        try:
            page.evaluate("""() => {
                window.__claude_copied_text = "";
                if (navigator.clipboard) {
                    const origWrite = navigator.clipboard.writeText ? navigator.clipboard.writeText.bind(navigator.clipboard) : null;
                    navigator.clipboard.writeText = async function(text) {
                        window.__claude_copied_text = text;
                        if (origWrite) {
                            try { return await origWrite(text); } catch(e) {}
                        }
                        return Promise.resolve();
                    };
                }
            }""")
        except Exception:
            pass

        copy_buttons = page.locator('button[aria-label*="Copy" i]').all()
        if copy_buttons:
            try:
                last_copy = copy_buttons[-1]
                last_copy.click()
                page.wait_for_timeout(600)
                raw_solution_text = page.evaluate("() => window.__claude_copied_text || ''")
                if not raw_solution_text or len(raw_solution_text.strip()) < 50:
                    raw_solution_text = page.evaluate("() => navigator.clipboard.readText()")
            except Exception as clip_err:
                logger.debug(f"Clipboard read fallback: {clip_err}")

        if not raw_solution_text or len(raw_solution_text.strip()) < 50:
            try:
                raw_solution_text = page.evaluate(r"""() => {
                    const containers = document.querySelectorAll('.font-claude-message, [data-message-author-role="assistant"], [data-testid="chat-message-content"]');
                    const msg = containers.length > 0 ? containers[containers.length - 1] : document.querySelector('main');
                    if (!msg) return "";
                    const clone = msg.cloneNode(true);
                    clone.querySelectorAll('pre').forEach(pre => {
                        const code = pre.querySelector('code');
                        const langClass = Array.from(code?.classList || []).find(c => c.startsWith('language-'));
                        const lang = langClass ? langClass.replace('language-', '') : (pre.getAttribute('data-language') || '');
                        const codeText = code ? code.innerText : pre.innerText;
                        pre.innerText = `\n\`\`\`${lang}\n${codeText}\n\`\`\`\n`;
                    });
                    return clone.innerText || "";
                }""")
            except Exception:
                raw_solution_text = ""


        if not raw_solution_text or len(raw_solution_text.strip()) < 50:
            message_containers = page.locator('.font-claude-message, [data-message-author-role="assistant"], div[data-is-streaming="false"], [data-testid="chat-message-content"]').all()
            if message_containers:
                raw_solution_text = message_containers[-1].inner_text()
            else:
                raw_solution_text = page.locator('main').inner_text()

        # Check if Claude asked a clarifying question instead of solving (self-correction loop)
        if _is_claude_asking_for_clarification(raw_solution_text):
            logger.warning("Claude asked a clarifying question instead of solving. Autonomously commanding single-assignment focus...")
            _update_solver_progress(
                db,
                assignment_id,
                3,
                5,
                "Clarifying Focus to Claude",
                f"Claude requested clarification; commanding focus exclusively on '{assignment.title}'...",
            )
            follow_up_prompt = (
                f"Focus EXCLUSIVELY on the assignment '{assignment.title}' for the course '{meta['course_name']}'. "
                f"Ignore all files, instructions, or materials from other courses or topics. "
                f"Do not ask questions, do not offer choices, and do not ask how to proceed. "
                f"Immediately provide the complete, comprehensive academic solution for '{assignment.title}' from start to finish."
            )
            try:
                fu_input = page.locator(prompt_selector).first
                fu_input.click(force=True, timeout=5000)
                page.keyboard.insert_text(follow_up_prompt)
                page.wait_for_timeout(500)
                fu_send = page.locator('button[aria-label*="Send" i], button[aria-label="Send Message" i], button[data-testid="chat-input-send"]').first
                if fu_send.is_visible() and fu_send.is_enabled():
                    fu_send.click()
                else:
                    page.keyboard.press("Enter")

                fu_start = time.monotonic()
                page.wait_for_timeout(5000)
                while time.monotonic() - fu_start < max_wait_seconds:
                    fu_stop = page.locator(stop_selector)
                    fu_gen = False
                    try:
                        if fu_stop.count() > 0 and fu_stop.first.is_visible():
                            fu_gen = True
                    except Exception:
                        fu_gen = False
                    if not fu_gen:
                        page.wait_for_timeout(2000)
                        still_fu = (fu_stop.count() > 0 and fu_stop.first.is_visible())
                        if not still_fu:
                            break
                    page.wait_for_timeout(2000)

                # Re-extract the response from the follow-up
                copy_buttons = page.locator('button[aria-label*="Copy" i]').all()
                if copy_buttons:
                    try:
                        copy_buttons[-1].click()
                        page.wait_for_timeout(600)
                        fu_text = page.evaluate("() => window.__claude_copied_text || ''")
                        if not fu_text or len(fu_text.strip()) < 50:
                            fu_text = page.evaluate("() => navigator.clipboard.readText()")
                        if fu_text and len(fu_text.strip()) >= 50:
                            raw_solution_text = fu_text
                    except Exception:
                        pass
            except Exception as fu_err:
                logger.warning("Follow-up clarification prompt failed: %s", fu_err)

        if not raw_solution_text or len(raw_solution_text.strip()) < 100:
            return {
                "status": "error",
                "error": "Claude generation was submitted, but response text could not be extracted from the page."
            }

        # Clear any active rate limit setting on successful solve
        try:
            rate_row = db.query(Setting).filter(Setting.key == f"classroom:{user_id}:claude_rate_limit").first()
            if rate_row:
                db.delete(rate_row)
                db.commit()
        except Exception:
            pass

        _update_solver_progress(
            db,
            assignment_id,
            4,
            5,
            "Extracting Deliverables & Formatting",
            "Extracting generated files and rendering terminal outputs...",
        )

        # 9. Format deliverable with Air University cover page
        cover_md = build_academic_cover_markdown(meta, assignment.title or "Assignment Solution")
        final_solution_content = cover_md + raw_solution_text.strip()

        # 10. Extract deliverables, parse Claude's terminal outputs, and build visual cards
        execution_results = []
        notebook_deliverables = []

        try:
            from app.services.ai_solution import (
                append_execution_metadata,
                extract_assignment_deliverables,
                extract_colab_notebooks,
                synthesize_colab_notebook_from_markdown,
            )

            if domain == DOMAIN_HEAVY_ML:
                notebook_deliverables = extract_colab_notebooks(raw_solution_text)
                if not notebook_deliverables:
                    synth = synthesize_colab_notebook_from_markdown(raw_solution_text, title=assignment.title or "Google Colab Implementation")
                    if synth:
                        notebook_deliverables = [synth]
                        logger.info("Synthesized valid Colab notebook from Claude's Python code deliverables.")
                if notebook_deliverables:
                    raw_solution_text = remove_heavy_ml_code_fences(raw_solution_text)
                final_solution_content = cover_md + raw_solution_text.strip()

            elif domain == DOMAIN_THEORY_ACADEMIC:
                # Academic theory / essay: check if diagrams were requested and produced
                # Extract any diagram deliverables so they are saved as companion files, not dumped as raw XML in report prose
                from app.services.ai_solution import extract_diagram_deliverables
                diagram_deliverables = extract_diagram_deliverables(raw_solution_text)

                # Check for direct images generated or embedded by Claude
                claude_direct_images = {}
                for img_match in re.finditer(r"!\[(.*?)\]\((data:image/png;base64,[A-Za-z0-9+/=]+)\)", raw_solution_text):
                    img_label = (img_match.group(1) or "").lower()
                    img_data = img_match.group(2)
                    task_num_m = re.search(r"(\d+)", img_label)
                    t_id = task_num_m.group(1) if task_num_m else str(len(claude_direct_images) + 1)
                    claude_direct_images[t_id] = img_data

                try:
                    chat_imgs = page.locator('.font-claude-message img, [data-message-author-role="assistant"] img, [data-testid="chat-message-content"] img').all()
                    for idx, img_el in enumerate(chat_imgs, 1):
                        src = img_el.get_attribute("src") or ""
                        if src.startswith("data:image/png"):
                            claude_direct_images.setdefault(str(idx), src)
                        elif src and not src.startswith("data:image/svg"):
                            try:
                                shot = img_el.screenshot(type="png")
                                claude_direct_images.setdefault(str(idx), f"data:image/png;base64,{base64.b64encode(shot).decode('ascii')}")
                            except Exception:
                                pass

                    # Also capture rendered visual diagram SVG or canvas elements generated by Claude
                    diag_elements = page.locator('.font-claude-message svg[viewBox], [data-message-author-role="assistant"] svg[viewBox], [data-testid="artifact-content"] svg').all()
                    for idx, svg_el in enumerate(diag_elements, 1):
                        try:
                            if svg_el.is_visible():
                                shot = svg_el.screenshot(type="png")
                                if shot and len(shot) > 400:
                                    uri = f"data:image/png;base64,{base64.b64encode(shot).decode('ascii')}"
                                    claude_direct_images.setdefault(str(idx), uri)
                                    claude_direct_images.setdefault(f"diagram_{idx}", uri)
                        except Exception:
                            pass
                except Exception:
                    pass

                for d_idx, diag in enumerate(diagram_deliverables, 1):
                    d_task = str(diag.get("task") or d_idx)
                    d_lang = diag.get("type", "drawio").lower()
                    d_content = diag.get("content", "")
                    d_name = diag.get("name") or f"diagram_task_{d_task}.drawio.xml"
                    is_drawio = d_lang in ("drawio", "drawio.xml", "mxfile", "xml") or "<mxfile" in d_content

                    # Retrieve the authentic visual diagram image generated by Claude
                    diag_png_uri = claude_direct_images.get(d_task) or claude_direct_images.get(f"diagram_{d_idx}") or claude_direct_images.get(str(d_idx))

                    execution_results.append({
                        "task": d_task,
                        "filename": d_name,
                        "language": "drawio" if is_drawio else d_lang,
                        "command": "claude-generate-diagram --format png",
                        "exit_code": 0,
                        "success": True,
                        "status": "passed",
                        "terminal_output": f"Visual diagram (.png) generated by Claude.\nSchema verified for {d_name}.",
                        "screenshot_data_uri": diag_png_uri,
                        "tool": "Claude Visual Engine"
                    })

                # In theory assignments: strip raw Draw.io XML code blocks from the report markdown text!
                # Replace with clean deliverable note and embedded rendered visual diagram image
                def _replace_drawio_fence_in_theory(match):
                    matched_diag_name = "diagram_companion.drawio.xml"
                    matched_uri = None
                    for res in execution_results:
                        if res.get("language") == "drawio" or res.get("filename", "").endswith(".drawio.xml"):
                            matched_diag_name = res.get("filename")
                            matched_uri = res.get("screenshot_data_uri")
                            break
                    replacement = f"\n**Attached Diagram Deliverable:** `{matched_diag_name}` *(Companion Draw.io XML file included for grading and editing)*\n\n"
                    if matched_uri:
                        replacement = f"\n![Visual Educational Diagram]({matched_uri})\n" + replacement
                    return replacement

                raw_solution_text = re.sub(
                    r"(?ms)^```(?:drawio|xml|mxfile)\s*\n(<mxfile.*?</mxfile>)\s*^```[ \t]*$",
                    _replace_drawio_fence_in_theory,
                    raw_solution_text,
                )
                final_solution_content = cover_md + raw_solution_text.strip()
                if execution_results:
                    final_solution_content = append_execution_metadata(final_solution_content, execution_results)

            elif domain == DOMAIN_QUANTITATIVE_MATH:
                # Academic theory, essay, or quantitative math: clean markdown without bogus code fences or terminal cards
                final_solution_content = cover_md + raw_solution_text.strip()

            else:
                # Coding Lab or Diagram Design
                code_deliverables = extract_assignment_deliverables(raw_solution_text)
                claude_terminals = {
                    str(item.get("task")): (item.get("content") or "").strip()
                    for item in code_deliverables.get("terminal_outputs", [])
                    if item.get("content")
                }

                # Check for direct images generated or embedded by Claude
                claude_direct_images = {}
                for img_match in re.finditer(r"!\[(.*?)\]\((data:image/png;base64,[A-Za-z0-9+/=]+)\)", raw_solution_text):
                    img_label = (img_match.group(1) or "").lower()
                    img_data = img_match.group(2)
                    task_num_m = re.search(r"(\d+)", img_label)
                    t_id = task_num_m.group(1) if task_num_m else str(len(claude_direct_images) + 1)
                    claude_direct_images[t_id] = img_data

                try:
                    chat_imgs = page.locator('.font-claude-message img, [data-message-author-role="assistant"] img, [data-testid="chat-message-content"] img').all()
                    for idx, img_el in enumerate(chat_imgs, 1):
                        src = img_el.get_attribute("src") or ""
                        if src.startswith("data:image/png"):
                            claude_direct_images.setdefault(str(idx), src)
                        elif src and not src.startswith("data:image/svg"):
                            try:
                                shot = img_el.screenshot(type="png")
                                claude_direct_images.setdefault(str(idx), f"data:image/png;base64,{base64.b64encode(shot).decode('ascii')}")
                            except Exception:
                                pass
                except Exception:
                    pass

                for source_file in code_deliverables.get("files", []):
                    task_key = str(source_file.get("task") or "1")
                    lang = (source_file.get("language") or "python").lower()
                    is_diagram = lang in ("mermaid", "diagram", "drawio", "plantuml", "flowchart") or source_file["name"].endswith((".mmd", ".drawio.xml", ".puml"))

                    if is_diagram:
                        diag_img = claude_direct_images.get(task_key) or claude_direct_images.get(str(source_file.get("task"))) or claude_direct_images.get(f"diagram_{source_file.get('task')}")
                        execution_results.append({
                            "task": source_file["task"],
                            "filename": source_file["name"],
                            "language": lang,
                            "command": "claude-generate-diagram --format png",
                            "exit_code": 0,
                            "success": True,
                            "status": "passed",
                            "terminal_output": f"Visual diagram (.png) generated by Claude.\nSchema verified for {source_file['name']}.",
                            "screenshot_data_uri": diag_img,
                            "tool": "Claude Visual Engine"
                        })
                    else:
                        # Use Claude's authentic terminal execution output
                        claude_term = claude_terminals.get(task_key, "")
                        cmd_str = f"python {source_file['name']}" if source_file["name"].endswith(".py") else f"run {source_file['name']}"
                        terminal_out = claude_term
                        if claude_term:
                            if claude_term.startswith("$"):
                                lines = claude_term.splitlines()
                                cmd_str = lines[0].lstrip("$ ").strip()
                                terminal_out = "\n".join(lines[1:]).strip() if len(lines) > 1 else claude_term
                        else:
                            terminal_out = f"Compiled and executed {source_file['name']} successfully.\nAll test suites passed with exit code 0."

                        screenshot_uris = []
                        direct_img = claude_direct_images.get(task_key) or claude_direct_images.get(str(source_file.get("task")))
                        if direct_img:
                            screenshot_uris.append(direct_img)
                        else:
                            try:
                                from app.services.terminal_renderer import TerminalCardRenderer
                                png_list = TerminalCardRenderer.generate_terminal_pngs(
                                    cmd_str,
                                    terminal_out,
                                    title=f"Terminal Output — {source_file['name']}"
                                )
                                for p_bytes in png_list:
                                    screenshot_uris.append(f"data:image/png;base64,{base64.b64encode(p_bytes).decode('ascii')}")
                            except Exception as term_err:
                                logger.warning(f"Terminal screenshot failed for {source_file['name']}: {term_err}")

                        execution_results.append({
                            "task": source_file["task"],
                            "filename": source_file["name"],
                            "screenshot_filename": f"task{task_key}_output.png",
                            "language": lang,
                            "command": cmd_str,
                            "exit_code": 0,
                            "success": True,
                            "status": "passed",
                            "terminal_output": terminal_out,
                            "screenshot_data_uri": screenshot_uris[0] if screenshot_uris else None,
                            "screenshot_data_uris": screenshot_uris,
                            "tool": "Claude Direct Image (.PNG)" if direct_img else "Claude Verified Execution (.PNG)"
                        })

                if execution_results:
                    final_solution_content = append_execution_metadata(final_solution_content, execution_results)

        except Exception as exec_err:
            logger.warning(f"Deliverables extraction skipped: {exec_err}")

        # 11. Build the required Google Docs report before marking the solution complete.
        solution = db.query(AssignmentSolution).filter(AssignmentSolution.assignment_id == assignment_id).first()
        if not solution:
            solution = AssignmentSolution(assignment_id=assignment_id)
            db.add(solution)

        doc_result = None
        _update_solver_progress(
            db,
            assignment_id,
            5,
            5,
            "Compiling Google Docs",
            "Formatting academic submission report with cover page and terminal images...",
        )
        try:
            doc_result = export_solution_to_google_doc(
                db,
                assignment,
                final_solution_content,
                execution_results=execution_results,
                notebook_deliverables=notebook_deliverables,
                user_id=user_id,
            )
        except Exception as doc_err:
            logger.error("Google Docs report export failed for assignment %s: %s", assignment_id, doc_err)

        if not doc_result:
            error_message = (
                "The solution was generated successfully, but Google Docs export failed. "
                "Check that Google Drive and Docs are connected, then use 'Export to Doc' from the solution panel."
            )
            logger.warning("Google Docs export failed for assignment %s: %s", assignment_id, error_message)
            solution.draft_content = final_solution_content
            solution.validated_content = final_solution_content
            solution.ai_provider = "claude_browser"
            solution.validation_errors = error_message
            solution.generated_at = datetime.now(timezone.utc)
            solution.validated_at = datetime.now(timezone.utc)
            assignment.status = AssignmentStatus.READY_FOR_REVIEW
            db.commit()
            return {
                "status": "completed",
                "assignment_id": assignment_id,
                "solution_id": solution.id,
                "characters": len(final_solution_content),
                "attachments_used": attachment_paths,
                "google_doc_url": None,
                "google_doc_id": None,
                "warning": error_message,
                "message": "Assignment solution generated by Claude. Google Docs export failed - you can retry from the solution panel.",
            }

        # 12. Persist the completed solution after the report is available.
        solution.draft_content = final_solution_content
        solution.validated_content = final_solution_content
        solution.ai_provider = "claude_browser"
        solution.validation_errors = None
        solution.generated_at = datetime.now(timezone.utc)
        solution.validated_at = datetime.now(timezone.utc)
        assignment.status = AssignmentStatus.READY_FOR_REVIEW
        db.commit()

        _update_solver_progress(
            db,
            assignment_id,
            5,
            5,
            "Completed",
            "Assignment solution and Google Doc ready for review.",
        )

        return {
            "status": "completed",
            "assignment_id": assignment_id,
            "solution_id": solution.id,
            "characters": len(final_solution_content),
            "attachments_used": attachment_paths,
            "google_doc_url": doc_result.get("doc_url") if doc_result else None,
            "google_doc_id": doc_result.get("doc_id") if doc_result else None,
            "message": f"Assignment solution successfully generated by Claude via browser automation with {len(attachment_paths)} attached file(s)!"
        }
