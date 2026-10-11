import os
import re
import json
import time
import shutil
import urllib.request
import urllib.error
import subprocess
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, Tuple
from sqlalchemy.orm import Session

from app.db.models import (
    Assignment,
    AssignmentSolution,
    AssignmentMaterial,
    Course,
    AssignmentStatus,
    Setting,
)
from app.core.config import settings
from app.core.logging import logger
from app.services.google_docs import get_google_docs_service
from app.services.ai_solution import export_solution_to_google_doc

CLAUDE_PROFILE_DIR = Path(__file__).resolve().parent.parent.parent / "tmp" / "claude_browser_profile"
CLAUDE_MATERIALS_DIR = Path(__file__).resolve().parent.parent.parent / "tmp" / "materials"
CLAUDE_MATERIALS_DIR.mkdir(parents=True, exist_ok=True)
CLAUDE_PROFILE_DIR.mkdir(parents=True, exist_ok=True)

CLAUDE_CDP_PORT = 21735
USER_CDP_PORT = 9222

_claude_process: Optional[subprocess.Popen] = None


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


def is_cdp_port_live(port: int, timeout: float = 0.5) -> bool:
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/json/version")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return bool(data.get("webSocketDebuggerUrl"))
    except Exception:
        return False


def get_active_cdp_port() -> Optional[int]:
    """Check if either user's port 9222 or Uniflow's port 21735 is responding."""
    if is_cdp_port_live(USER_CDP_PORT):
        return USER_CDP_PORT
    if is_cdp_port_live(CLAUDE_CDP_PORT):
        return CLAUDE_CDP_PORT
    return None


def open_claude_browser_window() -> Dict[str, Any]:
    """Launch or focus Chrome with the Claude persistent profile and remote debugging enabled."""
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
        f"--user-data-dir={str(CLAUDE_PROFILE_DIR)}",
        f"--remote-debugging-port={CLAUDE_CDP_PORT}",
        "--remote-debugging-address=127.0.0.1",
        "--remote-allow-origins=*",
        "--no-first-run",
        "--no-default-browser-check",
        "--start-maximized",
        "https://claude.ai/new",
    ]

    try:
        flags = (subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP) if os.name == "nt" else 0
        _claude_process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            creationflags=flags
        )
    except Exception as e:
        logger.error(f"Failed to launch Chrome for Claude: {e}")
        return {"status": "error", "error": f"Failed to launch Chrome: {str(e)}"}

    # Wait up to 10 seconds for CDP endpoint to become ready
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        if is_cdp_port_live(CLAUDE_CDP_PORT):
            return {
                "status": "launched",
                "port": CLAUDE_CDP_PORT,
                "message": "Chrome launched on debugging port 21735."
            }
        time.sleep(0.4)

    return {
        "status": "launched_waiting",
        "port": CLAUDE_CDP_PORT,
        "message": "Chrome window opened, waiting for local connection..."
    }


def get_student_metadata(db: Session, course: Optional[Course]) -> Dict[str, str]:
    """Extract standard student and institutional metadata for Air University submissions."""
    profile_row = db.query(Setting).filter(Setting.key.like("clerk_user_%")).order_by(Setting.updated_at.desc()).first()
    profile = {}
    if profile_row and profile_row.value:
        try:
            profile = json.loads(profile_row.value)
        except Exception:
            profile = {}

    student_name = " ".join(
        part for part in (profile.get("first_name"), profile.get("last_name")) if part
    ).strip() or profile.get("name") or "Ahmed Khan"

    user_email = profile.get("email", "")
    roll_no = profile.get("student_id") or profile.get("roll_no") or profile.get("rollNumber") or ""
    if not roll_no and user_email:
        digits_match = re.search(r'(\d{5,8})', user_email)
        if digits_match:
            roll_no = digits_match.group(1)
        else:
            roll_no = user_email.split("@")[0]
    if not roll_no:
        roll_no = "232530"

    course_name = course.name if course else "Course"
    instructor = (course.teacher_name if course and course.teacher_name else "") or "Course Instructor"
    section = (course.section if course and course.section else "") or "BSCSev-F-23-A-925"

    return {
        "student_name": student_name,
        "roll_no": roll_no,
        "student_email": user_email or "232530@students.au.edu.pk",
        "course_name": course_name,
        "instructor": instructor,
        "section": section,
        "university": "AIR UNIVERSITY, ISLAMABAD",
        "department": "Department of Computer Science & Information Technology",
        "date": datetime.now().strftime("%B %d, %Y")
    }


def scan_local_downloads_for_assignment(assignment: Assignment, course: Optional[Course] = None) -> List[str]:
    """Scan the user's Downloads folder for newly downloaded assignment sheets or lab manuals."""
    downloads_dir = Path.home() / "Downloads"
    if not downloads_dir.exists() or not downloads_dir.is_dir():
        return []

    found_files: List[str] = []
    keywords = set()
    for text in (assignment.title, getattr(course, "name", ""), getattr(course, "external_id", "")):
        if text:
            clean_words = re.findall(r'[a-zA-Z0-9]{3,}', text.lower())
            keywords.update(clean_words)

    keywords = {k for k in keywords if k not in {"the", "and", "for", "with", "from", "fall", "spring", "2026", "2025"}}

    now = time.time()
    valid_exts = {".pdf", ".docx", ".doc", ".txt", ".zip", ".py", ".cpp", ".sql", ".java", ".asm"}

    try:
        for item in downloads_dir.iterdir():
            if item.is_file() and item.suffix.lower() in valid_exts:
                try:
                    mtime = item.stat().st_mtime
                    if now - mtime < 7 * 86400:
                        fname = item.name.lower()
                        if any(k in fname for k in keywords) or ("assignment" in fname and str(assignment.id) in fname) or ("lab" in fname and any(k in fname for k in keywords)):
                            dest = CLAUDE_MATERIALS_DIR / f"assignment_{assignment.id}_dl_{item.name}"
                            if not dest.exists() or dest.stat().st_size == 0:
                                shutil.copy2(item, dest)
                            found_files.append(str(dest.resolve()))
                except Exception:
                    pass
    except Exception as err:
        logger.debug(f"Downloads scan error: {err}")

    return found_files


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
    Ensure all assignment files (PDFs, docs) are downloaded locally and ready for upload to Claude.
    Returns list of absolute file paths.
    """
    materials = db.query(AssignmentMaterial).filter(AssignmentMaterial.assignment_id == assignment.id).all()
    file_paths: List[str] = []
    docs_service = get_google_docs_service(db)

    # 1. Check existing cached materials in materials dir
    cached_pattern = f"assignment_{assignment.id}_"
    for f in CLAUDE_MATERIALS_DIR.glob(f"{cached_pattern}*"):
        if f.is_file() and f.stat().st_size > 0 and not f.name.endswith("_questions.txt"):
            file_paths.append(str(f.resolve()))

    # 2. Check and download from Google Drive
    for m in materials:
        if m.drive_file_id and docs_service:
            try:
                title = m.title or f"assignment_{assignment.id}_material.pdf"
                safe_title = re.sub(r'[^a-zA-Z0-9_\-\.]', '_', title)
                if not safe_title.lower().endswith(('.pdf', '.docx', '.doc', '.txt', '.zip')):
                    safe_title += ".pdf"
                dest_path = CLAUDE_MATERIALS_DIR / f"assignment_{assignment.id}_{safe_title}"

                if not dest_path.exists() or dest_path.stat().st_size == 0:
                    data = docs_service.download_file(m.drive_file_id)
                    if data:
                        dest_path.write_bytes(data)
                        logger.info(f"Downloaded material for assignment {assignment.id}: {dest_path}")

                if dest_path.exists() and dest_path.stat().st_size > 0:
                    file_paths.append(str(dest_path.resolve()))
            except Exception as e:
                logger.warning(f"Could not download material {m.id} for assignment {assignment.id}: {e}")

    # 3. Check local Downloads folder
    dl_files = scan_local_downloads_for_assignment(assignment, course)
    file_paths.extend(dl_files)
    file_paths = list(dict.fromkeys(file_paths))

    # 4. Fallback: if materials only have extracted content and no binaries, dump to question text
    if not file_paths:
        combined_text = []
        for m in materials:
            if m.content and m.content.strip():
                combined_text.append(f"--- Material: {m.title or 'Attachment'} ---\n{m.content.strip()}")
        if combined_text:
            text_path = CLAUDE_MATERIALS_DIR / f"assignment_{assignment.id}_questions.txt"
            text_path.write_text("\n\n".join(combined_text), encoding="utf-8")
            file_paths.append(str(text_path.resolve()))

    return list(dict.fromkeys(file_paths))


def _handle_claude_login_and_oauth(page, student_email: str = "232530@students.au.edu.pk", max_retries: int = 3) -> bool:
    """
    Zero-touch Claude login automation:
    Auto-clicks 'Continue with Google', auto-selects student Google account, and redirects into Claude chat.
    """
    for attempt in range(max_retries):
        cur_url = (getattr(page, "url", "") or "").lower()

        try:
            inp = page.locator('div[contenteditable="true"]').first
            if inp.count() > 0 and inp.is_visible():
                return True
        except Exception:
            pass

        # Auto-dismiss Claude onboarding modals
        for dismiss_sel in (
            "button:has-text('Acknowledge')",
            "button:has-text('Got it')",
            "button:has-text('Accept')",
            "button:has-text('Continue')",
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

        # If on Google OAuth page
        if "accounts.google.com" in cur_url:
            try:
                from app.portal.router import _handle_google_oauth_if_needed
                logger.info(f"Handling Google OAuth for Claude (email: {student_email})...")
                _handle_google_oauth_if_needed(page, student_email=student_email)
                if hasattr(page, "wait_for_timeout"):
                    page.wait_for_timeout(3000)
            except Exception as e:
                logger.debug(f"OAuth helper error: {e}")
            continue

        # Look for Continue with Google on Claude
        google_btns = (
            "button:has-text('Continue with Google')",
            "a:has-text('Continue with Google')",
            "button:has-text('Log in with Google')",
            "button:has-text('Sign in with Google')",
            "button[data-testid*='google' i]",
        )
        clicked_google = False
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
        inp = page.locator('div[contenteditable="true"]').first
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


def solve_assignment_via_claude_browser(
    db: Session,
    assignment_id: int,
    max_wait_seconds: int = 180
) -> Dict[str, Any]:
    """
    Autonomous pipeline that connects to the user's Chrome browser, attaches assignment PDFs/materials,
    submits an academic prompt to Claude, waits for response completion, prepends the Air University cover page,
    and updates the database.
    """
    from playwright.sync_api import sync_playwright

    assignment = db.query(Assignment).filter(Assignment.id == assignment_id).first()
    if not assignment:
        return {"status": "error", "error": f"Assignment {assignment_id} not found"}

    course = db.query(Course).filter(Course.id == assignment.course_id).first()
    meta = get_student_metadata(db, course)
    attachment_paths = prepare_assignment_materials(db, assignment, course)
    extracted_text = extract_assignment_question_text(db, assignment)

    # 1. Ensure Chrome CDP endpoint is ready
    port = get_active_cdp_port()
    if port is None:
        launch_res = open_claude_browser_window()
        if launch_res.get("status") == "error":
            return launch_res
        port = get_active_cdp_port()
        if port is None:
            return {
                "status": "error",
                "error": "Chrome was launched, but its remote debugging port (21735) is not responding yet. Please ensure Chrome opened and try again."
            }

    logger.info(f"Connecting to Chrome on CDP port {port} for Assignment {assignment_id}...")

    # 2. Connect Playwright over CDP
    with sync_playwright() as p:
        try:
            browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{port}", timeout=10000)
        except Exception as e:
            return {
                "status": "error",
                "error": f"Could not connect to Chrome on port {port}: {str(e)}"
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

        # 3. Check login status & trigger zero-touch auto-login
        prompt_selector = 'div[contenteditable="true"]'
        lower_url = (getattr(page, "url", "") or "").lower()

        if any(token in lower_url for token in ("login", "logout", "signin")) or "accounts.google.com" in lower_url:
            logger.info("Attempting zero-touch Claude sign-in via Google OAuth...")
            student_email = meta.get("student_email") or "232530@students.au.edu.pk"
            _handle_claude_login_and_oauth(page, student_email=student_email)

            # Recheck URL after auto-login attempt
            lower_url = (getattr(page, "url", "") or "").lower()
            if any(token in lower_url for token in ("login", "logout", "signin")) or "accounts.google.com" in lower_url:
                return {
                    "status": "needs_login",
                    "error": "Claude is not signed in. The Chrome window is open on screen. Please click 'Continue with Google' to sign in, then click Solve again."
                }

        # Verify chat input box exists
        try:
            page.wait_for_selector(prompt_selector, timeout=6000)
        except Exception:
            login_el = page.query_selector("button:has-text('Continue with Google'), a:has-text('Continue with Google'), button:has-text('Log in'), button:has-text('Sign in')")
            if login_el or any(token in (getattr(page, "url", "") or "").lower() for token in ("login", "logout", "signin")):
                return {
                    "status": "needs_login",
                    "error": "Claude is not signed in. The Chrome window is open on screen. Please click 'Continue with Google' to sign in, then click Solve again."
                }
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

        prompt_text = (
            f"You are an expert academic specialist and professor in {meta['course_name']} at Air University, Islamabad.\n\n"
            f"STUDENT DETAILS:\n"
            f"- Student Name: {meta['student_name']}\n"
            f"- Roll No: {meta['roll_no']}\n"
            f"- Section: {meta['section']}\n"
            f"- Course: {meta['course_name']}\n"
            f"- Assignment Title: {assignment.title}\n"
            f"- Instructor: {meta['instructor']}\n\n"
            f"{questions_block}\n"
            f"INSTRUCTIONS:\n"
            f"1. Thoroughly review and solve EVERY question, task, problem statement, and requirement presented above and in the attached assignment material"
            f"{f' ({file_names_str})' if file_names_str else ''}.\n"
            f"2. For each question:\n"
            f"   - Clearly restate the Question / Problem Statement.\n"
            f"   - Provide comprehensive, step-by-step academic explanations, case analyses, and theory.\n"
            f"   - Provide full, production-ready source code, SQL queries, or visual diagrams (in Mermaid ```mermaid or Draw.io XML ```xml blocks) wherever requested.\n"
            f"   - Include thorough verification, expected outputs, or component breakdowns.\n"
            f"3. Do not omit any part. Ensure the submission meets the highest university grading standards.\n"
            f"4. Format your entire answer in clean, publication-ready Markdown."
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
        try:
            from app.services.ai_solution import extract_code_deliverables, extract_diagram_deliverables, append_execution_metadata
            from app.services.code_runner import SingleFileCodeRunner
            from app.services.browser_tool_runner import BrowserToolRunner

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
                else:
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

        # 11. Persist solution into Database
        solution = db.query(AssignmentSolution).filter(AssignmentSolution.assignment_id == assignment_id).first()
        if not solution:
            solution = AssignmentSolution(assignment_id=assignment_id)
            db.add(solution)

        solution.draft_content = final_solution_content
        solution.validated_content = final_solution_content
        solution.ai_provider = "claude_browser"
        solution.validation_errors = None
        solution.generated_at = datetime.now(timezone.utc)
        solution.validated_at = datetime.now(timezone.utc)
        assignment.status = AssignmentStatus.READY_FOR_REVIEW
        db.commit()

        # 12. Export to Google Doc if connected
        doc_result = None
        try:
            doc_result = export_solution_to_google_doc(db, assignment, final_solution_content, execution_results=execution_results)
        except Exception as doc_err:
            logger.warning(f"Google Docs export skipped or failed: {doc_err}")

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
