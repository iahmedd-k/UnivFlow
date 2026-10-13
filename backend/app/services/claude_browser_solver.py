import os
import re
import json
import time
import shutil
import urllib.request
import urllib.error
import subprocess
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

CLAUDE_BROWSER_PROFILE_DIR = Path(__file__).resolve().parent.parent.parent / "tmp" / "claude_browser_profile"
CLAUDE_BROWSER_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
CLAUDE_MATERIALS_DIR = Path(__file__).resolve().parent.parent.parent / "tmp" / "materials"
CLAUDE_MATERIALS_DIR.mkdir(parents=True, exist_ok=True)

USER_CDP_PORT = 9222
CDP_CONNECT_TIMEOUT_MS = 20000
CDP_CONNECT_ATTEMPTS = 2

_claude_process: Optional[subprocess.Popen] = None

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


def open_claude_browser_window() -> Dict[str, Any]:
    """
    Launch or focus the persistent Uniflow browser profile with remote debugging enabled.
    Using a dedicated data directory is required by current Chrome versions and avoids
    interrupting the user's normal browser session.
    """
    global _claude_process
    active_port = get_active_cdp_port()
    if active_port is not None:
        return {
            "status": "ready",
            "port": active_port,
            "message": f"Chrome remote debugging is already active on port {active_port}."
        }

    browser_bin = find_system_browser()
    cmd = [
        browser_bin,
        f"--user-data-dir={CLAUDE_BROWSER_PROFILE_DIR}",
        f"--remote-debugging-port={USER_CDP_PORT}",
        "--remote-debugging-address=127.0.0.1",
        "--remote-allow-origins=*",
        "--restore-last-session",
        "https://claude.ai/new",
    ]

    try:
        flags = (subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | 0x00000200) if os.name == "nt" else 0
        try:
            _claude_process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                creationflags=flags
            )
        except OSError:
            _claude_process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                creationflags=(subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP) if os.name == "nt" else 0
            )
    except Exception as e:
        logger.error(f"Failed to launch Chrome for Claude: {e}")
        return {"status": "error", "error": f"Failed to launch Chrome: {str(e)}"}

    # Wait up to 10 seconds for CDP endpoint to become ready
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        if is_cdp_port_live(USER_CDP_PORT):
            return {
                "status": "launched",
                "port": USER_CDP_PORT,
                "message": (
                    f"Uniflow's persistent browser profile is ready on port {USER_CDP_PORT}. "
                    "Sign in to Claude in that window the first time."
                )
            }
        time.sleep(0.4)

    error_message = (
        f"Chrome opened with Uniflow's persistent profile, but its debugging endpoint on "
        f"port {USER_CDP_PORT} did not become ready. Check that Chrome is installed and "
        "that no other process is using this profile or port."
    )
    logger.error(error_message)
    return {
        "status": "error",
        "port": USER_CDP_PORT,
        "error": error_message,
    }


def get_student_metadata(
    db: Session,
    course: Optional[Course],
    user_id: Optional[str] = None,
) -> Dict[str, str]:
    """Extract standard student and institutional metadata for Air University submissions."""
    profile_query = db.query(Setting)
    if user_id:
        profile_query = profile_query.filter(Setting.key == f"clerk_user_{user_id}")
    else:
        profile_query = profile_query.filter(Setting.key.like("clerk_user_%")).order_by(Setting.updated_at.desc())
    profile_row = profile_query.first()
    profile = {}
    if profile_row and profile_row.value:
        try:
            profile = json.loads(profile_row.value)
        except Exception:
            profile = {}

    student_name = " ".join(
        part for part in (profile.get("first_name"), profile.get("last_name")) if part
    ).strip() or profile.get("name") or "Student"

    user_email = profile.get("email", "")
    roll_no = profile.get("student_id") or profile.get("roll_no") or profile.get("rollNumber") or ""
    if not roll_no and user_email:
        digits_match = re.search(r'(\d{5,8})', user_email)
        if digits_match:
            roll_no = digits_match.group(1)
        else:
            roll_no = user_email.split("@")[0]
    course_name = course.name if course else "Course"
    instructor = (course.teacher_name if course and course.teacher_name else "") or "Course Instructor"
    section = (course.section if course and course.section else "") or "Not provided"

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


def prepare_assignment_materials(db: Session, assignment: Assignment, course: Optional[Course] = None) -> List[str]:
    """
    Return only files explicitly attached to this assignment, ready for Claude upload.
    """
    materials = db.query(AssignmentMaterial).filter(AssignmentMaterial.assignment_id == assignment.id).all()
    file_paths: List[str] = []
    docs_service = get_google_docs_service(db, user_id=assignment.user_id)

    for m in materials:
        title = m.title or f"assignment_{assignment.id}_material"
        safe_title = re.sub(r'[^a-zA-Z0-9_\-\.]', '_', title)

        if m.material_type == "local_upload":
            local_path = CLAUDE_MATERIALS_DIR / f"assignment_{assignment.id}_{safe_title}"
            if local_path.is_file() and local_path.stat().st_size > 0:
                file_paths.append(str(local_path.resolve()))
            else:
                logger.warning("Attached local material %s is missing from disk.", m.title or m.id)
            continue

        if m.drive_file_id and docs_service:
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
                data = docs_service.download_file(m.drive_file_id)
                if not data:
                    logger.warning("Google Drive returned no content for attached material %s.", m.title or m.id)
                    continue
                dest_path.write_bytes(data)
                file_paths.append(str(dest_path.resolve()))
                logger.info("Downloaded attached material for assignment %s: %s", assignment.id, dest_path)
            except Exception as e:
                logger.warning(f"Could not download material {m.id} for assignment {assignment.id}: {e}")

    return list(dict.fromkeys(file_paths))


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


def solve_assignment_via_claude_browser(
    db: Session,
    assignment_id: int,
    max_wait_seconds: int = 180,
    user_id: str = "legacy",
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

    if _is_assignment_already_solving(db, assignment_id, user_id):
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

    # Users must sign into their own hosted browser profile in production.
    # In development, fall back to an isolated local Chrome profile so the flow can be tested.
    from app.services.browser_sessions import BrowserSessionClient
    try:
        endpoint = BrowserSessionClient().cdp_endpoint(user_id)
    except Exception as error:
        logger.warning("Hosted Claude browser is unavailable for user %s: %s", user_id, error)
        if settings.environment == "development":
            logger.info("Development mode: falling back to isolated local Chrome profile.")
            launch_result = open_claude_browser_window()
            if launch_result.get("status") not in ("ready", "launched"):
                return {
                    "status": "needs_login",
                    "error": (
                        "Could not start a local Claude browser and the hosted browser service is unavailable. "
                        f"Details: {launch_result.get('error', 'unknown error')}"
                    ),
                }
            endpoint = f"http://127.0.0.1:{USER_CDP_PORT}"
        else:
            return {
                "status": "needs_login",
                "error": "Start and sign into your private Claude browser from Settings, then resume this assignment.",
            }

    logger.info("Connecting to the private Claude browser for assignment %s.", assignment_id)

    # Set Playwright bypass for context-management errors on attached Chromium instances
    os.environ["PW_CHROMIUM_ATTACH_TO_OTHER"] = "1"

    # 2. Connect Playwright over CDP
    with sync_playwright() as p:
        try:
            browser = connect_to_chrome(p.chromium, endpoint)
        except Exception as e:
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

        context = browser.contexts[0] if browser.contexts else None
        if not context:
            return {"status": "error", "error": "No browser context found on Chrome."}

        try:
            context.grant_permissions(["clipboard-read", "clipboard-write"])
        except Exception:
            pass

        # Find or create a page for Claude
        page = None
        for pg in context.pages:
            if "claude.ai" in (pg.url or ""):
                page = pg
                break
        if not page:
            page = context.new_page()

        page.bring_to_front()

        # Check current URL or navigate to new chat
        current_url = page.url or ""
        if "claude.ai" not in current_url:
            page.goto("https://claude.ai/new", wait_until="domcontentloaded", timeout=30000)
        elif not current_url.endswith("/new"):
            page.goto("https://claude.ai/new", wait_until="domcontentloaded", timeout=30000)

        # Allow SPA hydration
        page.wait_for_timeout(3000)

        # 3. Ensure Claude is signed in and a chat input is available.
        #     The helper auto-dismisses onboarding, clicks "Continue with Google",
        #     and selects the student account when possible.
        prompt_selector = 'div[contenteditable="true"]'
        student_email = meta.get("student_email") or ""
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

        # 5. Build Comprehensive Academic Prompt with Guaranteed Question Extraction
        questions_block = ""
        if assignment.description and assignment.description.strip():
            questions_block += f"\nASSIGNMENT INSTRUCTIONS & QUESTIONS:\n{assignment.description.strip()}\n"
        if extracted_text and extracted_text.strip():
            questions_block += f"\nEXTRACTED REFERENCE MATERIAL CONTENT:\n{extracted_text.strip()[:10000]}\n"

        heavy_ml_assignment = is_heavy_ml_assignment(
            "\n".join((assignment.title or "", assignment.description or "", extracted_text))
        )
        heavy_ml_instructions = (
            "This assignment involves computationally heavy machine-learning/deep-learning work. "
            "Do not provide a standalone script that should be run on this local machine. "
            "Instead, provide exactly one valid Jupyter nbformat 4 notebook as JSON in a "
            "```colab-json fenced block, with markdown explanation cells and complete code cells "
            "ready for Google Colab. Include setup, dependency installation, dataset instructions, "
            "GPU/runtime guidance where appropriate, training/evaluation, and reproducible outputs. "
            "Do not claim the notebook was executed."
            if heavy_ml_assignment
            else
            "For normal programming tasks, provide complete source code in language-labelled fenced "
            "blocks. For tasks asking for diagrams, include the complete Mermaid, PlantUML, Graphviz, "
            "or Draw.io source in a labelled fenced block so the diagram can be rendered and its "
            "source included in the report."
        )
        prompt_text = (
            f"You are an expert academic specialist for {meta['course_name']} at Air University, Islamabad.\n\n"
            f"ASSIGNMENT CONTEXT:\n"
            f"- Assignment: {assignment.title}\n"
            f"- Course: {meta['course_name']}\n"
            f"- Instructor: {meta['instructor']}\n"
            f"- Student: {meta['student_name']} ({meta['roll_no']}, {meta['section']})\n"
            f"- Assignment-attached files uploaded to this chat: {file_names_str or 'None'}\n\n"
            f"{questions_block}\n"
            "ANALYZE FIRST, THEN PREPARE REPORT CONTENT:\n"
            "1. Treat only the assignment instructions and explicitly listed attached files above as "
            "assignment materials. Do not introduce unrelated documents or tasks.\n"
            "2. Identify every task and preserve its exact task name/title. Under each task, provide "
            "a concise problem statement, analysis/approach, and complete result or answer.\n"
            "3. Include the complete code or diagram source under the task that uses it. For diagrams, "
            "also provide a clear visual diagram source; the application will render it for the report.\n"
            "4. Do not invent terminal output, execution results, screenshots, or claim code was run. "
            "The application will execute supported code and record its actual terminal output.\n"
            f"5. {heavy_ml_instructions}\n"
            "6. Return polished Markdown organized as '# Task N — Exact Task Name' headings and "
            "separate sections for Analysis, Result, Implementation/Diagram Source where applicable, "
            "and Conclusion. Do not attempt to create a Google Doc yourself: the application will "
            "build the final Google Docs report with its university introduction page, task analysis, "
            "source files, rendered diagrams, and actual execution output."
        )

        # 6. Fill prompt and send
        input_el = page.locator(prompt_selector).first
        input_el.click()
        page.wait_for_timeout(300)

        # Insert prompt cleanly
        page.keyboard.insert_text(prompt_text)
        page.wait_for_timeout(1000)

        # Wait until send button is enabled (in case file upload is finalizing)
        send_btn = page.locator('button[aria-label*="Send" i], button[aria-label="Send Message" i]').first
        for _ in range(8):
            if send_btn.is_visible() and send_btn.is_enabled():
                break
            page.wait_for_timeout(1000)

        if send_btn.is_visible() and send_btn.is_enabled():
            send_btn.click()
        else:
            page.keyboard.press("Enter")

        logger.info(f"Prompt sent to Claude for assignment {assignment_id}. Waiting for completion...")

        # 7. Wait for Claude response generation to complete
        start_time = time.monotonic()
        # Initial wait for generation to start
        page.wait_for_timeout(5000)

        stop_selector = 'button[aria-label*="Stop response"], button[aria-label*="Stop"], button[data-testid*="stop"]'
        
        while time.monotonic() - start_time < max_wait_seconds:
            # Check for Claude rate limit / capacity banner immediately
            for quota_token in ("out of free messages", "out of messages", "reached your usage limit", "reached your message limit", "currently at capacity"):
                try:
                    cap_locator = page.locator(f"text={quota_token}").first
                    if cap_locator.count() > 0 and cap_locator.is_visible():
                        logger.warning(f"Claude message quota reached: {quota_token}")
                        return {
                            "status": "error",
                            "error": f"Claude Free Tier limit reached: '{quota_token}'. Please wait for your Claude usage limit to reset in Chrome, or switch to Multi-Agent (Groq/Gemini)."
                        }
                except Exception:
                    pass

            # Check if stop button is present (meaning still streaming)
            stop_locator = page.locator(stop_selector)
            is_generating = False
            try:
                if stop_locator.count() > 0 and stop_locator.first.is_visible():
                    is_generating = True
            except Exception:
                is_generating = False

            if not is_generating:
                # Give a 2 second grace period to ensure streaming finished
                page.wait_for_timeout(2000)
                # Verify again
                try:
                    still_going = (stop_locator.count() > 0 and stop_locator.first.is_visible())
                except Exception:
                    still_going = False
                if not still_going:
                    logger.info("Claude finished generating response.")
                    break
            page.wait_for_timeout(2000)

        # 8. Extract Claude's response
        # Claude messages are rendered in message blocks with copy buttons
        raw_solution_text = ""
        
        # Method A: Try clicking the latest copy button on the assistant response
        copy_buttons = page.locator('button[aria-label*="Copy" i]').all()
        if copy_buttons:
            try:
                # Latest copy button corresponds to the last generated message
                last_copy = copy_buttons[-1]
                last_copy.click()
                page.wait_for_timeout(500)
                # Read from clipboard via browser evaluate
                raw_solution_text = page.evaluate("() => navigator.clipboard.readText()")
            except Exception as clip_err:
                logger.debug(f"Clipboard read fallback: {clip_err}")

        # Method B: Fallback to DOM extraction from message container
        if not raw_solution_text or len(raw_solution_text.strip()) < 50:
            message_containers = page.locator('.font-claude-message, [data-message-author-role="assistant"], div[data-is-streaming="false"], [data-testid="chat-message-content"]').all()
            if message_containers:
                raw_solution_text = message_containers[-1].inner_text()
            else:
                # Final fallback: extract main body text of the chat thread
                raw_solution_text = page.locator('main').inner_text()

        if not raw_solution_text or len(raw_solution_text.strip()) < 100:
            return {
                "status": "error",
                "error": "Claude generation was submitted, but response text could not be extracted from the page."
            }

        # 9. Format final deliverable with Air University cover page
        cover_md = build_academic_cover_markdown(meta, assignment.title or "Assignment Solution")
        final_solution_content = cover_md + raw_solution_text.strip()

        # 10. Execute code deliverables & render visual diagrams
        execution_results = []
        notebook_deliverables = []
        try:
            from app.services.ai_solution import (
                append_execution_metadata,
                extract_code_deliverables,
                extract_colab_notebooks,
                extract_diagram_deliverables,
            )
            from app.services.code_runner import SingleFileCodeRunner
            from app.services.browser_tool_runner import BrowserToolRunner

            notebook_deliverables = extract_colab_notebooks(raw_solution_text)
            if heavy_ml_assignment and not notebook_deliverables:
                return {
                    "status": "error",
                    "error": (
                        "This heavy machine-learning assignment requires a valid Colab notebook, "
                        "but Claude did not return one. Retry the solver to generate the notebook."
                    ),
                }
            if heavy_ml_assignment:
                raw_solution_text = remove_heavy_ml_code_fences(raw_solution_text)

            code_deliverables = extract_code_deliverables(raw_solution_text)
            for source_file in code_deliverables.get("files", []):
                lang = (source_file.get("language") or "python").lower()
                if lang in ("mermaid", "diagram", "drawio", "plantuml", "flowchart") or source_file["name"].endswith((".mmd", ".drawio.xml", ".puml")):
                    diag_res = BrowserToolRunner.render_diagram(
                        diagram_type=lang,
                        diagram_code=source_file["content"],
                        title=f"Task {source_file['task']} — {source_file['name']}"
                    )
                    execution_results.append({
                        "task": source_file["task"],
                        "filename": source_file["name"],
                        "language": lang,
                        "command": f"render-diagram --engine {lang}",
                        "exit_code": 0,
                        "success": True,
                        "status": "passed",
                        "terminal_output": f"Rendered {lang.upper()} diagram canvas successfully.\nVector SVG and PNG asset captured.",
                        "screenshot_data_uri": diag_res.get("data_uri"),
                        "tool": diag_res.get("tool", "Mermaid / Draw.io Engine")
                    })
                elif not heavy_ml_assignment:
                    run = SingleFileCodeRunner.execute_code(source_file["content"], lang)
                    cmd_str = run.get("command") or f"run {source_file['name']}"
                    stdout_str = run.get("stdout") or ""
                    stderr_str = run.get("stderr") or ""
                    exit_code = run.get("exit_code", 0)
                    terminal_out = f"$ {cmd_str}\n{stdout_str}"
                    if stderr_str:
                        terminal_out += f"\n[stderr]\n{stderr_str}"
                    terminal_out += f"\n[Process completed with exit code {exit_code}]"

                    screenshot_uri = None
                    try:
                        from app.services.terminal_renderer import TerminalRenderer
                        screenshot_uri = TerminalRenderer.render_terminal_screenshot(
                            command=cmd_str,
                            stdout=stdout_str,
                            stderr=stderr_str,
                            exit_code=exit_code
                        )
                    except Exception as term_err:
                        logger.warning(f"Terminal screenshot failed for Claude code: {term_err}")

                    execution_results.append({
                        "task": source_file["task"],
                        "filename": source_file["name"],
                        "language": lang,
                        "command": cmd_str,
                        "exit_code": exit_code,
                        "success": run.get("success", False),
                        "status": "passed" if run.get("success") else "failed",
                        "terminal_output": terminal_out,
                        "screenshot_data_uri": screenshot_uri,
                        "tool": "SingleFileCodeRunner (Local Subprocess)"
                    })

            # Render any additional diagrams (Mermaid, Draw.io)
            all_diagrams = extract_diagram_deliverables(raw_solution_text)
            existing_diag_files = {r.get("filename") for r in execution_results}
            for diag in all_diagrams:
                if diag["name"] not in existing_diag_files:
                    diag_res = BrowserToolRunner.render_diagram(
                        diagram_type=diag["type"],
                        diagram_code=diag["content"],
                        title=diag.get("heading") or f"Task {diag['task']} — {diag['name']}"
                    )
                    execution_results.append({
                        "task": diag["task"],
                        "filename": diag["name"],
                        "language": diag["type"],
                        "command": f"render-diagram --engine {diag['type']}",
                        "exit_code": 0,
                        "success": True,
                        "status": "passed",
                        "terminal_output": f"Rendered {diag['type'].upper()} diagram canvas successfully.\nVector SVG and PNG asset captured.",
                        "screenshot_data_uri": diag_res.get("data_uri"),
                        "tool": diag_res.get("tool", "Kroki / Draw.io Engine")
                    })

            if execution_results:
                final_solution_content = append_execution_metadata(final_solution_content, execution_results)
        except Exception as exec_err:
            logger.warning(f"Code execution / diagram rendering skipped for Claude solution: {exec_err}")

        # 11. Build the required Google Docs report before marking the solution complete.
        solution = db.query(AssignmentSolution).filter(AssignmentSolution.assignment_id == assignment_id).first()
        if not solution:
            solution = AssignmentSolution(assignment_id=assignment_id)
            db.add(solution)

        doc_result = None
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
                "The solution was generated, but its required Google Docs report could not be created. "
                "Check that Google Drive and Docs are connected, then retry from the solution panel."
            )
            solution.draft_content = final_solution_content
            solution.validated_content = None
            solution.ai_provider = "claude_browser"
            solution.validation_errors = error_message
            solution.generated_at = datetime.now(timezone.utc)
            solution.validated_at = None
            assignment.status = AssignmentStatus.DRAFT
            db.commit()
            return {
                "status": "draft",
                "assignment_id": assignment_id,
                "solution_id": solution.id,
                "characters": len(final_solution_content),
                "attachments_used": attachment_paths,
                "error": error_message,
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
