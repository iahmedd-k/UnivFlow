from contextlib import contextmanager
from importlib import import_module
from types import SimpleNamespace

import playwright.sync_api

portal_router = import_module("app.portal.router")


class FakeLocator:
    def __init__(self, text="", count=0):
        self.text = text
        self.visible_count = count

    def count(self):
        return self.visible_count

    def inner_text(self, timeout):
        return self.text


class FakePage:
    def __init__(self, url, text="", password_count=0):
        self.url = url
        self.text = text
        self.password_count = password_count

    def locator(self, selector):
        if selector == "body":
            return FakeLocator(text=self.text)
        return FakeLocator(count=self.password_count)


class FakeChromium:
    def __init__(self, pages):
        self.contexts = [SimpleNamespace(pages=pages)]

    def connect_over_cdp(self, endpoint, timeout):
        return self


def test_login_detection_rejects_google_redirect_and_portal_login():
    google_page = FakePage("https://accounts.google.com/signin")
    portal_login = FakePage(
        "https://portals.au.edu.pk/students/",
        text="Student Login Please enter your password",
    )
    assert portal_router._portal_page_needs_login(google_page, "portals.au.edu.pk")
    assert portal_router._portal_page_needs_login(portal_login, "portals.au.edu.pk")


def test_login_detection_accepts_authenticated_portal_page():
    dashboard = FakePage(
        "https://portals.au.edu.pk/students/Dashboard.aspx",
        text="Student dashboard Current semester",
    )
    assert not portal_router._portal_page_needs_login(dashboard, "portals.au.edu.pk")


def test_portal_navigation_discovery_selects_tabs_and_postbacks_only():
    controls = [
        {
            "index": 1,
            "tag": "button",
            "role": "tab",
            "text": "Attendance",
            "visible": True,
            "href": "",
        },
        {
            "index": 2,
            "tag": "a",
            "text": "Registered Courses",
            "visible": True,
            "href": "javascript:__doPostBack('ctl00$RegisteredCourses','')",
            "is_postback": True,
            "in_navigation": True,
        },
        {
            "index": 3,
            "tag": "button",
            "text": "Register Course",
            "visible": True,
            "href": "",
            "is_postback": True,
            "in_navigation": True,
        },
        {
            "index": 4,
            "tag": "a",
            "text": "Attendance",
            "visible": True,
            "href": "https://portals.au.edu.pk/students/Attendance.aspx",
            "in_navigation": True,
        },
        {
            "index": 5,
            "tag": "a",
            "text": "Transcript",
            "visible": True,
            "href": "https://other.example/transcript",
            "in_navigation": True,
        },
    ]

    candidates = portal_router._portal_navigation_controls(controls, "portals.au.edu.pk")

    assert [item["index"] for item in candidates] == [1, 2]


def test_academic_portal_link_discovery_matches_compact_registered_courses_route():
    assert portal_router._is_academic_portal_link(
        "https://portals.au.edu.pk/students/Reports/RegisteredCourses"
    )
    assert portal_router._is_academic_portal_link(
        "/students/Reports/RegisteredCourses",
        "Registered Courses",
    )
    assert not portal_router._is_academic_portal_link(
        "https://portals.au.edu.pk/students/Home/Index",
        "Dashboard",
    )


def test_connection_status_does_not_accept_blank_or_google_pages(monkeypatch):
    pages = [
        FakePage("about:blank"),
        FakePage("https://accounts.google.com/signin"),
    ]
    chromium = FakeChromium(pages)
    monkeypatch.setattr(portal_router, "_cdp_is_available", lambda user_id: True)

    @contextmanager
    def fake_sync_playwright():
        yield SimpleNamespace(chromium=chromium)

    monkeypatch.setattr(playwright.sync_api, "sync_playwright", fake_sync_playwright)
    assert not portal_router._portal_browser_authenticated(
        "student-1",
        "https://portals.au.edu.pk/students/",
    )


def test_connection_status_accepts_authenticated_portal_tab(monkeypatch):
    pages = [
        FakePage("https://accounts.google.com/signin"),
        FakePage(
            "https://portals.au.edu.pk/students/Dashboard.aspx",
            text="Student dashboard Current semester",
        ),
    ]
    chromium = FakeChromium(pages)
    monkeypatch.setattr(portal_router, "_cdp_is_available", lambda user_id: True)

    @contextmanager
    def fake_sync_playwright():
        yield SimpleNamespace(chromium=chromium)

    monkeypatch.setattr(playwright.sync_api, "sync_playwright", fake_sync_playwright)
    assert portal_router._portal_browser_authenticated(
        "student-1",
        "https://portals.au.edu.pk/students/",
    )
