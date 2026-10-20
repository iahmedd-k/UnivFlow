"""Google Classroom UI fallback for student submissions.

This uses the student's isolated persistent Google Classroom Chrome profile for
the UI actions which the Classroom API project is not permitted to perform.
The Drive files are still created in the student's own Google Drive first.
"""

import re
import time
from typing import Any
from urllib.parse import quote

from app.core.logging import logger
from app.services.browser_sessions import BrowserSessionClient


class ClassroomBrowserLoginRequired(RuntimeError):
    """The persistent Classroom browser has not been authenticated yet."""


class ClassroomBrowserSubmissionError(RuntimeError):
    """The Classroom UI could not safely complete the requested submission."""


def _to_gcr_base64_id(raw_id: str) -> str:
    """Google Classroom web URLs encode 64-bit integer IDs as URL-safe Base64."""
    raw = str(raw_id).strip()
    if not raw:
        return raw
    if raw.isdigit():
        import base64
        return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")
    return raw


def _wait_for_picker_frame(page, timeout_seconds: float = 25.0):
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        for frame in page.frames:
            if "drive.google.com" in (frame.url or "") and "picker" in (frame.url or ""):
                return frame
        page.wait_for_timeout(250)
    raise ClassroomBrowserSubmissionError("Google Drive picker did not open in Classroom.")


def _select_drive_file(frame, file_id: str, display_name: str) -> None:
    search = frame.get_by_role("combobox", name=re.compile("Search in Drive", re.I))
    # Search by the unique Drive ID to avoid selecting one of the duplicate
    # filenames often produced by retries.
    search.fill(f"https://drive.google.com/open?id={quote(file_id, safe='')}")
    search.press("Enter")
    options = frame.get_by_role("option")
    deadline = time.monotonic() + 18.0
    while time.monotonic() < deadline:
        try:
            if options.count() >= 1:
                break
        except Exception:
            pass
        time.sleep(0.25)
    if options.count() == 0:
        # Some Drive picker versions treat a pasted URL as a title search.
        # Retry with the expected name.
        search.fill(display_name)
        search.press("Enter")
        deadline = time.monotonic() + 12.0
        while time.monotonic() < deadline:
            if options.count() >= 1:
                break
            time.sleep(0.25)
    if options.count() == 0:
        # Check Recent list directly for the filename
        recent_item = frame.locator(f'[role="option"]:has-text("{display_name}"), div[role="row"]:has-text("{display_name}")')
        if recent_item.count() >= 1:
            recent_item.first.click()
            return
        raise ClassroomBrowserSubmissionError(
            f"Could not uniquely identify {display_name} in the user's Drive."
        )
    options.first.click()


def submit_drive_files(
    user_id: str,
    course_id: str,
    coursework_id: str,
    files: list[dict[str, str]],
    assignment_url: str | None = None,
    assignment_title: str | None = None,
    expected_email: str | None = None,
    cookies: list[dict[str, Any]] | None = None,
    user_agent: str | None = None,
) -> dict[str, Any]:
    """Attach the provided Drive files and submit the coursework in Classroom."""
    client = BrowserSessionClient.classroom()
    endpoint = client.cdp_endpoint(user_id)

    from playwright.sync_api import sync_playwright

    b64_course = _to_gcr_base64_id(course_id)
    b64_work = _to_gcr_base64_id(coursework_id)

    target_url = assignment_url
    if not target_url:
        target_url = (
            f"https://classroom.google.com/c/{quote(str(b64_course), safe='')}"
            f"/a/{quote(str(b64_work), safe='')}/details"
        )
    else:
        # If the provided URL had raw numeric IDs, normalize them to base64
        if str(course_id) in target_url and str(course_id).isdigit():
            target_url = target_url.replace(f"/c/{course_id}", f"/c/{b64_course}")
        if str(coursework_id) in target_url and str(coursework_id).isdigit():
            target_url = target_url.replace(f"/a/{coursework_id}", f"/a/{b64_work}")
            target_url = target_url.replace(f"/sa/{coursework_id}", f"/sa/{b64_work}")

    if expected_email and "authuser=" not in target_url:
        sep = "&" if "?" in target_url else "?"
        target_url += f"{sep}authuser={quote(expected_email)}"

    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(endpoint, timeout=15_000)
        if not browser.contexts:
            raise ClassroomBrowserSubmissionError("The saved Classroom browser profile is unavailable.")
        context = browser.contexts[0]

        if cookies:
            try:
                formatted_cookies = []
                for c in cookies:
                    cookie_dict = dict(c)
                    same_site = cookie_dict.get("sameSite")
                    if same_site:
                        ss = str(same_site).lower()
                        if "lax" in ss:
                            cookie_dict["sameSite"] = "Lax"
                        elif "strict" in ss:
                            cookie_dict["sameSite"] = "Strict"
                        elif "none" in ss:
                            cookie_dict["sameSite"] = "None"
                        else:
                            cookie_dict.pop("sameSite", None)
                    else:
                        cookie_dict.pop("sameSite", None)
                    if not cookie_dict.get("domain") and not cookie_dict.get("url"):
                        cookie_dict["domain"] = ".google.com"
                    formatted_cookies.append(cookie_dict)
                context.add_cookies(formatted_cookies)
                logger.info("Injected %d Google Classroom session cookies for user %s", len(formatted_cookies), user_id)
            except Exception as ce:
                logger.warning("Could not inject Google Classroom cookies for user %s: %s", user_id, ce)

        page = next(
            (candidate for candidate in context.pages if "classroom.google.com" in (candidate.url or "")),
            None,
        ) or context.new_page()

        logger.info("Navigating Classroom browser for user %s to: %s", user_id, target_url)
        page.goto(target_url, wait_until="domcontentloaded", timeout=35_000)

        # Wait for the student work panel to render
        deadline = time.monotonic() + 12.0
        while time.monotonic() < deadline:
            text = page.locator("body").inner_text()
            if any(k in text for k in ["Your work", "Add or create", "Turn in", "Mark as done", "Unsubmit", "Turned in", "Submitted", "Handed in", "Class not found"]):
                break
            page.wait_for_timeout(500)

        current_url = page.url or ""
        body_text = page.locator("body").inner_text()

        # Check for authentication requirement
        if "accounts.google.com" in current_url or page.get_by_text("Sign in", exact=True).count():
            raise ClassroomBrowserLoginRequired("Sign in to your Google Classroom account in the hosted browser, then retry.")

        # Check for class not found or account mismatch
        if "Class not found" in body_text or "Course not found" in body_text:
            switch_btn = page.locator('button:has-text("Switch account"), a:has-text("Switch account")')
            if switch_btn.count():
                raise ClassroomBrowserSubmissionError(
                    "Google Classroom account mismatch. You are signed into a Google account that does not belong to this class."
                )
            raise ClassroomBrowserSubmissionError("This coursework or class could not be found in Google Classroom for this account.")

        # Smart Recovery: If "Your work" or submission status is not immediately visible,
        # check if we are on the stream or classwork list and navigate into the assignment
        has_work_panel = any(k in body_text for k in ["Your work", "Add or create", "Turn in", "Mark as done", "Unsubmit", "Turned in", "Submitted", "Handed in"])
        if not has_work_panel:
            logger.info("Classroom page did not immediately show 'Your work'. Checking for assignment links or 'View assignment'...")
            candidate_links = page.locator(f'a[href*="{b64_work}"], [data-item-id*="{b64_work}"]')
            if candidate_links.count() == 0 and assignment_title:
                candidate_links = page.locator(f'a:has-text("{assignment_title}"), div[role="button"]:has-text("{assignment_title}")')

            if candidate_links.count() > 0:
                candidate_links.first.click()
                page.wait_for_timeout(1000)

                view_btn = page.locator('a:has-text("View assignment"), a:has-text("View instructions"), a[href*="/details"]')
                if view_btn.count() > 0:
                    view_btn.first.click()
                    page.wait_for_timeout(1500)

                body_text = page.locator("body").inner_text()

        # Verify Google Account if expected email was provided
        if expected_email:
            account_button = page.get_by_role("button", name=re.compile("Google Account", re.I))
            if account_button.count() >= 1:
                account_label = account_button.first.get_attribute("aria-label") or account_button.first.inner_text()
                if expected_email.casefold() not in (account_label or "").casefold():
                    logger.warning("Account label %s did not match expected email %s", account_label, expected_email)

        # 1. Check if the assignment is ALREADY submitted/turned in
        if re.search(r"\b(Turned in|Submitted|Handed in)\b", body_text, re.I) or page.locator('button:has-text("Unsubmit")').count() > 0:
            logger.info("Assignment %s is already turned in on Google Classroom for user %s", coursework_id, user_id)
            return {"attached": len(files), "turned_in": True, "already_submitted": True}

        # 2. Check if files are already attached
        attached_count = 0
        all_attached = all(item["name"] in body_text for item in files)
        if all_attached:
            attached_count = len(files)
        else:
            # Look for the Add/Create button using multiple robust selectors
            add_button = None
            for sel in [
                'button:has-text("Add or create")',
                '[aria-label*="Add or create" i]',
                'button:has-text("Add work")',
                '[aria-label*="Add work" i]',
                'button:has-text("+ Add")',
                'button:has-text("Add")',
            ]:
                loc = page.locator(sel)
                count = loc.count()
                for i in range(count):
                    cand = loc.nth(i)
                    if cand.is_visible():
                        add_button = cand
                        break
                if add_button:
                    break

            if not add_button:
                # If neither Add/Create nor Turn in is available, check why
                turn_in_candidates = page.locator('button:has-text("Turn in"), button:has-text("Mark as done")')
                has_turn_in = any(turn_in_candidates.nth(i).is_visible() for i in range(turn_in_candidates.count())) if turn_in_candidates.count() > 0 else False

                if not has_turn_in:
                    logger.warning("Classroom UI state at failure: URL=%s text_snippet=%r", current_url, body_text[:400])
                    raise ClassroomBrowserSubmissionError(
                        "The assignment does not expose an 'Add or create' control. Check if the assignment deadline has passed, or if it is already submitted."
                    )
                # If Turn In exists without Add control (e.g., question assignment or student already has files attached):
                logger.info("Assignment has no attachment control but 'Turn in' / 'Mark as done' is available.")
            else:
                add_button.click()
                page.wait_for_timeout(600)

                # Click Google Drive option in dropdown menu
                drive_option = None
                for sel in ['text="Google Drive"', '[aria-label*="Google Drive" i]', 'div:has-text("Google Drive")']:
                    loc = page.locator(sel)
                    for i in range(loc.count()):
                        cand = loc.nth(i)
                        if cand.is_visible():
                            drive_option = cand
                            break
                    if drive_option:
                        break

                if not drive_option:
                    raise ClassroomBrowserSubmissionError("Classroom did not show 'Google Drive' in the attachment dropdown.")

                drive_option.click()
                picker = _wait_for_picker_frame(page)
                for item in files:
                    _select_drive_file(picker, item["id"], item["name"])
                add_files_button = picker.get_by_role("button", name="Add", exact=True)
                if add_files_button.count() != 1 or not add_files_button.is_enabled():
                    raise ClassroomBrowserSubmissionError("Classroom did not enable Add for the selected Drive files.")
                add_files_button.click()

                # Wait for files to appear in student's work list
                deadline = time.monotonic() + 12.0
                while time.monotonic() < deadline:
                    page.wait_for_timeout(600)
                    updated_text = page.locator("body").inner_text()
                    attached_count = sum(1 for item in files if item["name"] in updated_text)
                    if attached_count == len(files):
                        break

                if attached_count != len(files):
                    logger.warning("Could not verify all attached files. Text snippet: %r", updated_text[:300])

        # 3. Final submission check: click Turn In / Mark as Done
        body_text = page.locator("body").inner_text()
        if re.search(r"\b(Turned in|Submitted|Handed in)\b", body_text, re.I):
            return {"attached": attached_count, "turned_in": True, "already_submitted": True}

        action_btn = None
        for sel in [
            'button:has-text("Turn in")',
            'button:has-text("Hand in")',
            'button:has-text("Mark as done")',
        ]:
            loc = page.locator(sel)
            for i in range(loc.count()):
                cand = loc.nth(i)
                if cand.is_visible() and cand.is_enabled():
                    action_btn = cand
                    break
            if action_btn:
                break

        if not action_btn:
            logger.info("Turn In / Mark as Done button was not active. Files attached: %d", attached_count)
            return {"attached": attached_count, "turned_in": False}

        action_btn.click()
        page.wait_for_timeout(800)

        # Confirm turn in dialog if prompted
        confirmation_dialog = page.get_by_role("dialog").last
        if confirmation_dialog.count() and confirmation_dialog.is_visible():
            confirmation = confirmation_dialog.get_by_role(
                "button", name=re.compile(r"^(Turn in|Mark as done|Submit|Hand in)$", re.I)
            ).last
            if confirmation.count() and confirmation.is_enabled():
                confirmation.click()

        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline:
            state_text = page.locator("body").inner_text()
            if re.search(r"\b(Turned in|Submitted|Handed in|Unsubmit)\b", state_text, re.I):
                return {"attached": attached_count, "turned_in": True}
            time.sleep(0.5)

        return {"attached": attached_count, "turned_in": False}
