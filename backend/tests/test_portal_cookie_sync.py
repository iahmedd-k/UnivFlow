import json
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from app.main import app
from app.portal.router import _parse_cookie_header, _fetch_and_sync_portal_http
from app.db.models import Setting
from app.db.database import get_db
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db.models.common import Base


@pytest.fixture
def mock_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    engine.dispose()


def test_parse_cookie_header_string():
    raw = "ASP.NET_SessionId=mye51j2fscugpfg; .ASPXAUTH=9DF0B76A123; path=/; HttpOnly"
    cookies = _parse_cookie_header(raw)
    assert cookies.get("ASP.NET_SessionId") == "mye51j2fscugpfg"
    assert cookies.get(".ASPXAUTH") == "9DF0B76A123"


def test_parse_cookie_header_json_dict():
    raw = json.dumps({"ASP.NET_SessionId": "abc123456", "portal_pref": "1"})
    cookies = _parse_cookie_header(raw)
    assert cookies["ASP.NET_SessionId"] == "abc123456"
    assert cookies["portal_pref"] == "1"


def test_parse_cookie_header_json_list():
    raw = json.dumps([
        {"name": "ASP.NET_SessionId", "value": "sess7890123"},
        {"name": ".ASPXAUTH", "value": "auth4567890"},
    ])
    cookies = _parse_cookie_header(raw)
    assert cookies["ASP.NET_SessionId"] == "sess7890123"
    assert cookies[".ASPXAUTH"] == "auth4567890"


def test_parse_cookie_header_plain_session_token():
    raw = "mye51j2fscugpfg12345"
    cookies = _parse_cookie_header(raw)
    assert cookies["ASP.NET_SessionId"] == "mye51j2fscugpfg12345"


def test_fetch_and_sync_portal_http_mocked_success(mock_db):
    fake_html = """
    <html>
      <head><title>Student Attendance</title></head>
      <body>
        <table>
          <tr><th>Subject Name</th><th>Total</th><th>Present</th><th>Absent</th><th>Attendance %</th></tr>
          <tr><td>Software Engineering</td><td>20</td><td>18</td><td>2</td><td>90.0</td></tr>
          <tr><td>Database Systems</td><td>24</td><td>21</td><td>3</td><td>87.5</td></tr>
        </table>
      </body>
    </html>
    """
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = fake_html
    mock_resp.cookies = {}

    with patch("httpx.Client.get", return_value=mock_resp):
        res = _fetch_and_sync_portal_http(
            db=mock_db,
            uid="test_user",
            cookies={"ASP.NET_SessionId": "test_sess_123"},
            portal_base_url="https://portals.au.edu.pk/students/",
        )

    assert res["status"] == "success"
    assert res["attendance_count"] == 2
    assert res["attendance"][0]["subject"] == "Software Engineering"
    assert res["attendance"][0]["attended"] == 18

    # Verify cookie setting was saved to DB
    saved_cookie = mock_db.query(Setting).filter(Setting.key == "portal:test_user:portal_session_cookies").first()
    assert saved_cookie is not None
    assert "test_sess_123" in saved_cookie.value


def test_parse_cookie_header_cookie_prefix():
    raw = "Cookie: .AspNetCore.Cookies=CfDJ8Auth123; ASP.NET_SessionId=mye51j2fscugpfg"
    cookies = _parse_cookie_header(raw)
    assert cookies.get(".AspNetCore.Cookies") == "CfDJ8Auth123"
    assert cookies.get("ASP.NET_SessionId") == "mye51j2fscugpfg"


def test_parse_cookie_header_devtools_tabs():
    raw = "Name\tValue\tDomain\tPath\n.AspNetCore.Cookies\tCfDJ8AuthToken456\tportals.au.edu.pk\t/students\nASP.NET_SessionId\tmye51j2f\tportals.au.edu.pk\t/students"
    cookies = _parse_cookie_header(raw)
    assert cookies.get(".AspNetCore.Cookies") == "CfDJ8AuthToken456"
    assert cookies.get("ASP.NET_SessionId") == "mye51j2f"


def test_parse_cookie_header_curl_command():
    raw = "curl 'https://portals.au.edu.pk/students/Reports/Attendance' -H 'Cookie: .AspNetCore.Cookies=CfDJ8Token; ASP.NET_SessionId=Sess1'"
    cookies = _parse_cookie_header(raw)
    assert cookies.get(".AspNetCore.Cookies") == "CfDJ8Token"
    assert cookies.get("ASP.NET_SessionId") == "Sess1"


def test_parse_cookie_header_plain_aspnetcore_cookie_token():
    token = "CfDJ8O2alFrgKEdBuY0IDSGtddl4xIUGWUAq1GGuSPEZN6emZIZC_iIbVtbvKKmUCRx7CW7Nevn4aIa8BW2uLNlBrioR05iFflgVQmJ4eocWIwHnG"
    cookies = _parse_cookie_header(token)
    assert cookies.get(".AspNetCore.Cookies") == token


def test_fetch_and_sync_portal_http_candidate_url_fallback(mock_db):
    fake_html = """
    <html>
      <head><title>Student Attendance</title></head>
      <body>
        <table>
          <tr><th>Subject Name</th><th>Total</th><th>Present</th><th>Absent</th><th>Attendance %</th></tr>
          <tr><td>Operating Systems</td><td>30</td><td>27</td><td>3</td><td>90.0</td></tr>
        </table>
      </body>
    </html>
    """
    resp_redirect = MagicMock()
    resp_redirect.status_code = 302
    resp_redirect.headers = {"Location": "https://accounts.google.com/o/oauth2/auth"}

    resp_success = MagicMock()
    resp_success.status_code = 200
    resp_success.text = fake_html
    resp_success.cookies = {}

    # First URL redirects to login, second URL succeeds
    with patch("httpx.Client.get", side_effect=[resp_redirect, resp_success]):
        res = _fetch_and_sync_portal_http(
            db=mock_db,
            uid="test_user",
            cookies={".AspNetCore.Cookies": "valid_token", "ASP.NET_SessionId": "sess_123"},
            portal_base_url="https://portals.au.edu.pk/students/",
        )

    assert res["status"] == "success"
    assert res["attendance_count"] == 1
    assert res["attendance"][0]["subject"] == "Operating Systems"


def test_fetch_and_sync_portal_http_session_id_missing_auth_cookie_informative_error(mock_db):
    from fastapi import HTTPException

    resp_redirect = MagicMock()
    resp_redirect.status_code = 302
    resp_redirect.headers = {"Location": "https://accounts.google.com/o/oauth2/v2/auth?response_type=code"}

    with patch("httpx.Client.get", return_value=resp_redirect):
        with pytest.raises(HTTPException) as exc_info:
            _fetch_and_sync_portal_http(
                db=mock_db,
                uid="test_user",
                cookies={"ASP.NET_SessionId": "sess_only_12345"},
                portal_base_url="https://portals.au.edu.pk/students/",
            )

    assert exc_info.value.status_code == 401
    assert "Authentication cookie missing" in exc_info.value.detail
    assert ".AspNetCore.Cookies" in exc_info.value.detail

