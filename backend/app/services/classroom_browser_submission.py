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


def _wait_for_picker_frame(page, timeout_seconds: float = 20.0):
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        for frame in page.frames:
            if "drive.google.com/picker" in (frame.url or ""):
                return frame
        time.sleep(0.2)
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
            if options.count() == 1:
                break
        except Exception:
            pass
        time.sleep(0.25)
    if options.count() != 1:
        # Some Drive picker versions treat a pasted URL as a title search.
        # Retry with the expected name, then fail closed if it remains ambiguous.
        search.fill(display_name)
        search.press("Enter")
        deadline = time.monotonic() + 12.0
        while time.monotonic() < deadline:
            if options.count() == 1:
                break
            time.sleep(0.25)
    if options.count() != 1:
        raise ClassroomBrowserSubmissionError(
            f"Could not uniquely identify {display_name} in the user's Drive."
        )
    options.first.click()


def submit_drive_files(
    user_id: str,
    course_id: str,
    coursework_id: str,
    files: list[dict[str, str]],
    expected_email: str | None = None,
    cookies: list[dict[str, Any]] | None = None,
    user_agent: str | None = None,
) -> dict[str, Any]:
    """Attach the provided Drive files and submit the coursework in Classroom."""
    client = BrowserSessionClient.classroom()
    endpoint = client.cdp_endpoint(user_id)

    from playwright.sync_api import sync_playwright

    assignment_url = (
        f"https://classroom.google.com/c/{quote(str(course_id), safe='')}"
        f"/a/{quote(str(coursework_id), safe='')}/details"
    )
    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(endpoint, timeout=12_000)
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
        page.goto(assignment_url, wait_until="domcontentloaded", timeout=30_000)
        page.wait_for_timeout(1200)

        if "accounts.google.com" in (page.url or "") or page.get_by_text("Sign in", exact=True).count():
            raise ClassroomBrowserLoginRequired("Sign in to your Google Classroom account in the hosted browser, then retry.")

        account_button = page.get_by_role("button", name=re.compile("Google Account", re.I))
        if expected_email:
            if account_button.count() >= 1:
                account_label = account_button.first.get_attribute("aria-label") or account_button.first.inner_text()
                if expected_email.casefold() not in (account_label or "").casefold():
                    raise ClassroomBrowserSubmissionError(
                        "The hosted browser is signed in to a different Google account than the one connected to Uniflow."
                    )

        existing_text = page.locator("body").inner_text()
        if all(item["name"] in existing_text for item in files):
            attached_count = len(files)
        else:
            add_button = page.get_by_role("button", name=re.compile("Add or create", re.I))
            if add_button.count() != 1:
                raise ClassroomBrowserSubmissionError("The assignment does not expose a student attachment control.")
            add_button.click()
            page.get_by_text("Google Drive", exact=True).click()
            picker = _wait_for_picker_frame(page)
            for item in files:
                _select_drive_file(picker, item["id"], item["name"])
            add_files_button = picker.get_by_role("button", name="Add", exact=True)
            if add_files_button.count() != 1 or not add_files_button.is_enabled():
                raise ClassroomBrowserSubmissionError("Classroom did not enable Add for the selected Drive files.")
            add_files_button.click()
            page.wait_for_timeout(1000)
            updated_text = page.locator("body").inner_text()
            attached_count = sum(1 for item in files if item["name"] in updated_text)
            if attached_count != len(files):
                raise ClassroomBrowserSubmissionError("Classroom did not confirm that all Drive files were attached.")

        page_text = page.locator("body").inner_text()
        if re.search(r"\b(Turned in|Submitted)\b", page_text, re.I):
            return {"attached": attached_count, "turned_in": True, "already_submitted": True}

        action = page.get_by_role("button", name=re.compile(r"^(Turn in|Mark as done)$", re.I)).last
        if action.count() != 1 or not action.is_enabled():
            return {"attached": attached_count, "turned_in": False}
        action.click()

        confirmation_dialog = page.get_by_role("dialog").last
        if confirmation_dialog.count() and confirmation_dialog.is_visible():
            confirmation = confirmation_dialog.get_by_role(
                "button", name=re.compile(r"^(Turn in|Mark as done|Submit)$", re.I)
            ).last
            if confirmation.count() and confirmation.is_enabled():
                confirmation.click()

        deadline = time.monotonic() + 12.0
        while time.monotonic() < deadline:
            state_text = page.locator("body").inner_text()
            if re.search(r"\b(Turned in|Submitted|Unsubmit)\b", state_text, re.I):
                return {"attached": attached_count, "turned_in": True}
            time.sleep(0.4)
        return {"attached": attached_count, "turned_in": False}
