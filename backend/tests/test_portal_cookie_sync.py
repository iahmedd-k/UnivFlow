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
