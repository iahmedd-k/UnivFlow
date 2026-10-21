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
        # 1. Search page frames
        for frame in page.frames:
            url = (frame.url or "").lower()
            if "picker" in url and ("google.com" in url or "drive" in url or "docs" in url):
                target = frame
                for child in frame.child_frames:
                    if "picker" in (child.url or "").lower():
                        target = child
                        break
                return target

        # 2. Check DOM iframe elements
        try:
            picker_iframes = page.locator('iframe[src*="picker"], iframe[class*="picker"], iframe[name*="picker"]')
            for i in range(picker_iframes.count()):
                f = picker_iframes.nth(i).content_frame()
                if f:
                    url = (f.url or "").lower()
                    if "picker" in url or "drive.google.com" in url:
                        return f
        except Exception:
            pass

        page.wait_for_timeout(250)
    raise ClassroomBrowserSubmissionError("Google Drive picker did not open in Classroom.")


def _select_drive_file(frame, file_id: str, display_name: str) -> None:
    """Select the requested Drive file inside the Google Drive picker dialog.
    
    Prefers matching directly against the 'Recent' tab items (open by default, where
    the newly generated submission file appears immediately) with automatic container
    scrolling across multiple passes before falling back to search or My Drive tab.
    """
    clean_name = (display_name or "").strip()
    base_name = clean_name.rsplit(".", 1)[0] if "." in clean_name else clean_name
    space_name = clean_name.replace("_", " ").replace("-", " ")

    # Extract key tokens (e.g. ['ahmed', 'khan', 'lab', 'task', '05', '232530'])
    raw_tokens = re.findall(r"[A-Za-z0-9]+", clean_name)
    key_tokens = [t.lower() for t in raw_tokens if len(t) >= 2]

    # Give the picker iframe a few seconds to populate its items
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        try:
            if frame.locator('[role="option"], [role="gridcell"], [role="row"], div[data-id], .picker-dataview-item').count() > 0:
                break
            sign_in_btn = frame.locator('button:has-text("Sign in"), [role="button"]:has-text("Sign in"), a:has-text("Sign in")')
            if sign_in_btn.count() > 0 and sign_in_btn.first.is_visible():
                logger.info("Drive picker displayed Sign in button; clicking to initiate automatic handshake...")
                sign_in_btn.first.click(force=True)
                time.sleep(2.0)
        except Exception:
            pass
        time.sleep(0.3)

    # Helper JS script to find, scroll into view, and click the matching element
    def _try_js_select(f_id: str, c_name: str, b_name: str, sp_name: str, tokens: list[str]) -> bool:
        try:
            matched = frame.evaluate("""([fId, cName, bName, spName, tokens]) => {
                const cleanLower = (cName || '').toLowerCase();
                const baseLower = (bName || '').toLowerCase();
                const spaceLower = (spName || '').toLowerCase();
                const fIdStr = (fId || '').trim();

                const candidates = Array.from(document.querySelectorAll(
                    '[role="option"], [role="gridcell"], [role="row"], .picker-dataview-item, div[data-id], div[data-target-id]'
                ));

                let bestMatch = null;
                let bestScore = 0;

                for (const el of candidates) {
                    const text = (el.innerText || el.textContent || '').trim().toLowerCase();
                    const aria = (el.getAttribute('aria-label') || '').toLowerCase();
                    const title = (el.getAttribute('title') || '').toLowerCase();
                    const elId = (el.getAttribute('data-id') || el.getAttribute('data-item-id') || el.getAttribute('data-target-id') || el.id || '');

                    // 1. Exact Google Drive File ID match (highest priority)
                    if (fIdStr && elId && (elId === fIdStr || elId.includes(fIdStr) || fIdStr.includes(elId))) {
                        bestMatch = el;
                        bestScore = 1000;
                        break;
                    }

                    let score = 0;
                    const combined = `${text} ${aria} ${title}`;

                    // 2. Full exact clean name
                    if (cleanLower && combined.includes(cleanLower)) score += 500;
                    // 3. Base name without extension
                    if (baseLower && baseLower.length > 3 && combined.includes(baseLower)) score += 300;
                    // 4. Space separated name
                    if (spaceLower && spaceLower.length > 3 && combined.includes(spaceLower)) score += 200;

                    // 5. Key tokens matching
                    if (tokens && tokens.length > 0) {
                        let matchedTokens = 0;
                        for (const tok of tokens) {
                            if (combined.includes(tok)) matchedTokens++;
                        }
                        if (matchedTokens === tokens.length) {
                            score += 250;
                        } else if (matchedTokens >= 2) {
                            score += matchedTokens * 35;
                        }
                    }

                    if (score > bestScore) {
                        bestScore = score;
                        bestMatch = el;
                    }
                }

                if (bestMatch && bestScore >= 100) {
                    // Bring element into the center of the viewport
                    bestMatch.scrollIntoView({ block: 'center', inline: 'center', behavior: 'instant' });
                    
                    // Dispatch synthetic mouse events to trigger selection
                    bestMatch.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true, view: window }));
                    bestMatch.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, cancelable: true, view: window }));
                    bestMatch.click();
                    return true;
                }
                return false;
            }""", [f_id, c_name, b_name, sp_name, tokens])
            return bool(matched)
        except Exception as e:
            logger.debug("JS select evaluation error: %s", e)
            return False

    # Helper JS to scroll the picker view container down
    def _scroll_picker_container(direction: str = "down", amount: int = 350) -> bool:
        try:
            return bool(frame.evaluate("""([dir, px]) => {
                const scrollables = Array.from(document.querySelectorAll('*')).filter(el => {
                    const style = window.getComputedStyle(el);
                    const overflowY = style.overflowY;
                    const isScrollable = (overflowY === 'auto' || overflowY === 'scroll') && el.scrollHeight > el.clientHeight;
                    return isScrollable || el.classList.contains('picker-dataview-content') || el.getAttribute('role') === 'listbox' || el.getAttribute('role') === 'grid';
                });
                if (scrollables.length > 0) {
                    const target = scrollables[0];
                    if (dir === 'down') {
                        target.scrollTop += px;
                    } else if (dir === 'top') {
                        target.scrollTop = 0;
                    }
                    return true;
                }
                // Fallback to window scroll
                if (dir === 'down') window.scrollBy(0, px);
                else window.scrollTo(0, 0);
                return true;
            }""", [direction, amount]))
        except Exception:
            return False

    # 1. Multi-pass search across Recent files with progressive scrolling
    logger.info("Searching Drive picker for file '%s' (ID: %s)...", clean_name, file_id)
    for pass_num in range(7):
        if _try_js_select(file_id, clean_name, base_name, space_name, key_tokens):
            logger.info("Successfully selected Drive file '%s' in picker (pass %d).", clean_name, pass_num + 1)
            time.sleep(0.5)
            return
        
        # Scroll container down and wait for items to render
        _scroll_picker_container("down", 350)
        time.sleep(0.4)

    # Scroll back to top before trying Playwright locators or tab switches
    _scroll_picker_container("top", 0)
    time.sleep(0.3)

    # 2. Try standard Playwright locator selectors
    recent_selectors = [
        f'[data-id="{file_id}"]' if file_id else None,
        f'[data-item-id="{file_id}"]' if file_id else None,
        f'[role="option"]:has-text("{clean_name}")',
        f'[role="gridcell"]:has-text("{clean_name}")',
        f'[role="row"]:has-text("{clean_name}")',
        f'.picker-dataview-item:has-text("{clean_name}")',
        f'div[title*="{clean_name}" i]',
        f'div[aria-label*="{clean_name}" i]',
        f'[role="option"]:has-text("{base_name}")' if base_name != clean_name else None,
        f'div[title*="{base_name}" i]' if base_name != clean_name else None,
        f'[role="option"]:has-text("{space_name}")' if space_name != clean_name else None,
    ]
    for sel in [s for s in recent_selectors if s]:
        try:
            cand = frame.locator(sel)
            if cand.count() > 0:
                target_cand = cand.first
                try:
                    target_cand.scroll_into_view_if_needed(timeout=2000)
                except Exception:
                    pass
                target_cand.click(force=True)
                logger.info("Found and selected Drive file '%s' via Playwright locator %s.", clean_name, sel)
                time.sleep(0.5)
                return
        except Exception:
            continue

    # 3. Try switching to 'My Drive' tab in the left sidebar if present
    logger.info("File '%s' not in visible Recent items; attempting 'My Drive' tab fallback...", clean_name)
    try:
        my_drive_tab = frame.locator('div[role="tab"]:has-text("My Drive"), span:has-text("My Drive"), [aria-label*="My Drive" i]')
        if my_drive_tab.count() > 0 and my_drive_tab.first.is_visible():
            my_drive_tab.first.click(force=True)
            time.sleep(1.5)
            # Re-try matching on My Drive
            for pass_num in range(5):
                if _try_js_select(file_id, clean_name, base_name, space_name, key_tokens):
                    logger.info("Selected Drive file '%s' from 'My Drive' tab (pass %d).", clean_name, pass_num + 1)
                    time.sleep(0.5)
                    return
                _scroll_picker_container("down", 350)
                time.sleep(0.4)
    except Exception as tab_err:
        logger.debug("'My Drive' tab switch failed: %s", tab_err)

    # 4. Search input fallback
    search_input = None
    for sel in [
        'input[aria-label*="Search" i]',
        'input[placeholder*="Search" i]',
        'input[type="search"]',
        '[role="searchbox"]',
        'input.picker-search-input',
        'input[type="text"]',
    ]:
        try:
            cand = frame.locator(sel)
            for i in range(cand.count()):
                item = cand.nth(i)
                if item.is_visible():
                    search_input = item
                    break
        except Exception:
            continue
        if search_input:
            break

    if search_input:
        query = clean_name or base_name
        logger.info("Searching Drive picker for: %s", query)
        try:
            search_input.click(force=True)
            search_input.fill(query)
            search_input.press("Enter")
            time.sleep(1.5)

            if _try_js_select(file_id, clean_name, base_name, space_name, key_tokens):
                logger.info("Selected Drive file '%s' from search results.", clean_name)
                return
        except Exception as se:
            logger.warning("Drive search in picker failed: %s", se)

    # Check if picker explicitly has a visible "Sign in to access this content" error
    try:
        body_text = frame.locator("body").inner_text()
        if any(k in body_text for k in ["Sign in to access this content", "Sign in to your Google Account", "You must sign in"]):
            logger.warning("Google Drive picker requires sign-in: %r", body_text[:200])
            raise ClassroomBrowserLoginRequired(
                "Your Google Classroom / Google Drive session has expired or requires sign-in. Use the Uniflow extension popup to re-sync your Classroom session."
            )
    except ClassroomBrowserLoginRequired:
        raise
    except Exception:
        pass

    raise ClassroomBrowserSubmissionError(
        f"Could not find or select '{display_name}' in Google Drive picker. Please check your Google Drive."
    )


def _confirm_picker_selection(picker) -> None:
    """Find and click the confirmation button (Insert / Select / Add) in the Drive picker."""
    deadline = time.monotonic() + 8.0
    while time.monotonic() < deadline:
        for sel in [
            'button:has-text("Insert")',
            'button:has-text("Select")',
            'button:has-text("Add")',
            '[role="button"]:has-text("Insert")',
            '[role="button"]:has-text("Select")',
            '[role="button"]:has-text("Add")',
            'button[aria-label*="Insert" i]',
            'button[aria-label*="Select" i]',
            'button[aria-label*="Add" i]',
            'div[role="button"][name="Insert"]',
            'div[role="button"][name="Select"]',
        ]:
            candidates = picker.locator(sel)
            count = candidates.count()
            for i in range(count):
                btn = candidates.nth(i)
                try:
                    if btn.is_visible() and btn.is_enabled():
                        btn.click(force=True)
                        logger.info("Confirmed Drive picker selection via button: %s", sel)
                        return
                except Exception:
                    pass
        time.sleep(0.3)

    # JavaScript fallback inside picker frame
    try:
        clicked = picker.evaluate("""() => {
            const all = Array.from(document.querySelectorAll('button, [role="button"], div[tabindex="0"]'));
            for (const b of all) {
                const txt = (b.innerText || b.getAttribute('aria-label') || '').trim();
                if (/^(Insert|Select|Add)$/i.test(txt) && !b.disabled && b.getAttribute('aria-disabled') !== 'true') {
                    b.click();
                    return true;
                }
            }
            return false;
        }""")
        if clicked:
            logger.info("Confirmed Drive picker selection via JS evaluation fallback.")
            return
    except Exception as je:
        logger.warning("Picker JS confirmation fallback error: %s", je)

    logger.warning("No enabled confirmation button found in picker. Double-clicking item may have completed selection.")


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
                    s_site = str(cookie_dict.get("sameSite", "")).lower()
                    if s_site in ["no_restriction", "none"]:
                        cookie_dict["sameSite"] = "None"
                    elif s_site == "strict":
                        cookie_dict["sameSite"] = "Strict"
                    else:
                        cookie_dict["sameSite"] = "Lax"

                    if not cookie_dict.get("domain") and not cookie_dict.get("url"):
                        cookie_dict["domain"] = ".google.com"
                    if not cookie_dict.get("path"):
                        cookie_dict["path"] = "/"
                    formatted_cookies.append(cookie_dict)

                try:
                    context.add_cookies(formatted_cookies)
                    logger.info("Injected %d Google Classroom session cookies for user %s", len(formatted_cookies), user_id)
                except Exception as batch_err:
                    logger.debug("Batch cookie injection failed (%s), injecting individually...", batch_err)
                    added = 0
                    for fc in formatted_cookies:
                        try:
                            context.add_cookies([fc])
                            added += 1
                        except Exception:
                            pass
                    logger.info("Injected %d/%d Google Classroom session cookies for user %s", added, len(formatted_cookies), user_id)
            except Exception as ce:
                logger.warning("Could not inject Google Classroom cookies for user %s: %s", user_id, ce)

        # Pre-warm Docs and Drive session top-level so Google mints OSID cookies
        warm_urls = ["https://docs.google.com", "https://drive.google.com"]
        if expected_email:
            warm_urls.append(f"https://drive.google.com/drive/u/0/my-drive?authuser={quote(expected_email)}")
        for warm_url in warm_urls:
            try:
                warm_page = context.new_page()
                warm_page.goto(warm_url, wait_until="domcontentloaded", timeout=12_000)
                warm_page.wait_for_timeout(1000)
                warm_page.close()
                logger.info("Pre-warmed %s top-level session for user %s", warm_url, user_id)
            except Exception as warm_err:
                logger.debug("%s pre-warm skipped/failed: %s", warm_url, warm_err)

        page = next(
            (candidate for candidate in context.pages if "classroom.google.com" in (candidate.url or "")),
            None,
        ) or context.new_page()

        logger.info("Navigating Classroom browser for user %s to: %s", user_id, target_url)
        page.goto(target_url, wait_until="domcontentloaded", timeout=35_000)

        # If Google is doing an automatic SSO / CheckCookie handshake through accounts.google.com,
        # wait up to 6 seconds for it to bounce back to classroom.google.com
        if "accounts.google.com" in (page.url or ""):
            logger.info("Encountered accounts.google.com redirect; waiting for automatic session handshake...")
            for _ in range(12):
                page.wait_for_timeout(500)
                if "accounts.google.com" not in (page.url or ""):
                    break

        # Wait for the student work panel to render
        deadline = time.monotonic() + 12.0
        while time.monotonic() < deadline:
            text = page.locator("body").inner_text()
            if any(k in text for k in ["Your work", "Add or create", "Turn in", "Mark as done", "Unsubmit", "Turned in", "Submitted", "Handed in", "Class not found"]):
                break
            page.wait_for_timeout(500)

        current_url = page.url or ""
        body_text = page.locator("body").inner_text()

        # Check for actual authentication requirement (only if on Google login input form)
        is_login_page = (
            "accounts.google.com" in current_url
            and (
                page.locator('input[type="email"], input[name="identifier"], input[type="password"]').count() > 0
                or "Sign in with your Google Account" in body_text
                or "Choose an account" in body_text
            )
        )
        if is_login_page:
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

        # Filter to files that actually have valid Drive IDs
        valid_files = [
            f for f in files
            if isinstance(f, dict) and f.get("id") and str(f.get("id")).strip()
        ]

        def _is_file_in_text(fname: str, txt: str) -> bool:
            if not fname:
                return True
            if fname.lower() in txt.lower():
                return True
            base = fname.rsplit(".", 1)[0] if "." in fname else fname
            return (base.lower() in txt.lower()) if len(base) > 3 else False

        # 2. Check if files are already attached
        attached_count = 0
        all_attached = all(_is_file_in_text(item["name"], body_text) for item in valid_files) if valid_files else True
        if all_attached and valid_files:
            attached_count = len(valid_files)
        elif valid_files:
            # Look for the Add/Create button using multiple robust selectors
            add_button = None
            for sel in [
                'button:has-text("Add or create")',
                '[role="button"]:has-text("Add or create")',
                '[aria-label*="Add or create" i]',
                'button:has-text("Add work")',
                '[role="button"]:has-text("Add work")',
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
                turn_in_candidates = page.locator('button:has-text("Turn in"), button:has-text("Mark as done"), [role="button"]:has-text("Turn in"), [role="button"]:has-text("Mark as done")')
                has_turn_in = any(turn_in_candidates.nth(i).is_visible() for i in range(turn_in_candidates.count())) if turn_in_candidates.count() > 0 else False

                if not has_turn_in:
                    logger.warning("Classroom UI state at failure: URL=%s text_snippet=%r", current_url, body_text[:400])
                    raise ClassroomBrowserSubmissionError(
                        "The assignment does not expose an 'Add or create' control. Check if the assignment deadline has passed, or if it is already submitted."
                    )
                logger.info("Assignment has no attachment control but 'Turn in' / 'Mark as done' is available.")
            else:
                def _ensure_drive_picker():
                    # 1. First check if Google Drive picker is already open and valid
                    try:
                        for frame in page.frames:
                            url = (frame.url or "").lower()
                            if "picker" in url and "drive.google.com" in url:
                                if frame.locator("body").count() > 0:
                                    return frame
                    except Exception:
                        pass

                    # 2. Re-open 'Add or create' menu and select Google Drive
                    drive_option = None
                    menu_deadline = time.monotonic() + 15.0
                    last_click = 0.0
                    click_attempt = 0

                    while time.monotonic() < menu_deadline:
                        if time.monotonic() - last_click > 1.5:
                            logger.info("Clicking 'Add or create' button (attempt %d)...", click_attempt + 1)
                            try:
                                add_button.click(force=True)
                            except Exception:
                                add_button.evaluate("el => el.click()")
                            last_click = time.monotonic()
                            click_attempt += 1

                        page.wait_for_timeout(350)

                        for sel in [
                            '[role="menu"] [role="menuitem"]:has-text("Google Drive")',
                            '[role="menuitem"]:has-text("Google Drive")',
                            'li[role="menuitem"]:has-text("Google Drive")',
                            'li:has-text("Google Drive")',
                            '[role="menu"] li:has-text("Google Drive")',
                            '[role="menu"] [role="menuitem"]:has-text("Drive")',
                            '[role="menuitem"]:has-text("Drive")',
                            'li[role="menuitem"]:has-text("Drive")',
                            'li:has-text("Drive")',
                            '[role="menu"] [role="menuitem"][data-type="2"]',
                            'li[role="menuitem"][data-type="2"]',
                            '[role="menu"] [role="menuitem"]:first-child',
                            'div[role="menu"] li:first-child',
                        ]:
                            try:
                                loc = page.locator(sel)
                                for i in range(loc.count()):
                                    cand = loc.nth(i)
                                    if cand.is_visible():
                                        drive_option = cand
                                        break
                            except Exception:
                                pass
                            if drive_option:
                                break

                        if drive_option:
                            break

                    if not drive_option:
                        logger.warning("Classroom dropdown failed to expose Drive option. Current page text: %r", body_text[:400])
                        raise ClassroomBrowserSubmissionError("Classroom did not show 'Google Drive' in the attachment dropdown.")

                    logger.info("Found Google Drive option in dropdown. Clicking...")
                    clicked_drive = False
                    try:
                        drive_option.click(force=True, timeout=3000)
                        clicked_drive = True
                    except Exception as e:
                        logger.debug("Standard click on Drive option failed (%s), trying JS click...", e)

                    if not clicked_drive:
                        try:
                            drive_option.evaluate("el => (el.closest('[role=\"menuitem\"], li') || el).click()")
                            clicked_drive = True
                        except Exception as je:
                            logger.warning("JS click on Drive option failed: %s", je)

                    return _wait_for_picker_frame(page)

                for item in valid_files:
                    # Check if file is already attached in student's work card
                    current_work_text = page.locator("body").inner_text()
                    if _is_file_in_text(item["name"], current_work_text):
                        logger.info("File '%s' is already attached in Classroom.", item["name"])
                        continue

                    picker = _ensure_drive_picker()
                    _select_drive_file(picker, item["id"], item["name"])
                    _confirm_picker_selection(picker)
                    page.wait_for_timeout(1500)

                # Wait for files to appear in student's work list
                deadline = time.monotonic() + 12.0
                while time.monotonic() < deadline:
                    page.wait_for_timeout(600)
                    updated_text = page.locator("body").inner_text()
                    attached_count = sum(1 for item in valid_files if _is_file_in_text(item["name"], updated_text))
                    if attached_count == len(valid_files):
                        break

                if attached_count != len(valid_files):
                    logger.warning("Could not verify all attached files. Text snippet: %r", updated_text[:300])

        # 3. Final submission check: click Turn In / Mark as Done
        body_text = page.locator("body").inner_text()
        if re.search(r"\b(Turned in|Submitted|Handed in)\b", body_text, re.I):
            return {"attached": attached_count, "turned_in": True, "already_submitted": True}

        action_btn = None
        for sel in [
            'button:has-text("Turn in")',
            '[role="button"]:has-text("Turn in")',
            'button:has-text("Hand in")',
            '[role="button"]:has-text("Hand in")',
            'button:has-text("Mark as done")',
            '[role="button"]:has-text("Mark as done")',
        ]:
            loc = page.locator(sel)
            for i in range(loc.count()):
                cand = loc.nth(i)
                try:
                    if cand.is_visible() and cand.is_enabled():
                        action_btn = cand
                        break
                except Exception:
                    pass
            if action_btn:
                break

        if not action_btn:
            logger.info("Turn In / Mark as Done button was not active. Files attached: %d", attached_count)
            return {"attached": attached_count, "turned_in": False}

        action_btn.click(force=True)
        page.wait_for_timeout(800)

        # Confirm turn in dialog if prompted
        dialog_deadline = time.monotonic() + 5.0
        while time.monotonic() < dialog_deadline:
            confirmed = False
            for sel in [
                'div[role="dialog"] button:has-text("Turn in")',
                'div[role="dialog"] [role="button"]:has-text("Turn in")',
                'div[role="dialog"] button:has-text("Mark as done")',
                'div[role="dialog"] [role="button"]:has-text("Mark as done")',
                'div[role="dialog"] button:has-text("Submit")',
                'div[role="dialog"] button:has-text("Hand in")',
                '[role="dialog"] button:has-text("Turn in")',
            ]:
                loc = page.locator(sel)
                if loc.count() > 0:
                    cand = loc.last
                    try:
                        if cand.is_visible() and cand.is_enabled():
                            cand.click(force=True)
                            logger.info("Confirmed turn in dialog via: %s", sel)
                            confirmed = True
                            break
                    except Exception:
                        pass
            if confirmed:
                break
            time.sleep(0.3)

        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline:
            state_text = page.locator("body").inner_text()
            if re.search(r"\b(Turned in|Submitted|Handed in|Unsubmit)\b", state_text, re.I):
                return {"attached": attached_count, "turned_in": True}
            time.sleep(0.5)

        return {"attached": attached_count, "turned_in": False}
