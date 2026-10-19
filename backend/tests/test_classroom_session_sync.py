from unittest.mock import MagicMock, patch
import json
import pytest
from fastapi import HTTPException

from app.classroom.router import (
    sync_google_classroom_session,
    disconnect_google_classroom_session,
    get_google_classroom_browser_status,
    GoogleClassroomCookieSyncRequest,
    _finish_quick_turn_in_in_classroom_browser,
)
from app.db.models import Setting, Course, Assignment, Submission, SubmissionState, AssignmentStatus
from app.core.security import decrypt_token_if_encrypted


class MockDB:
    def __init__(self):
        self.settings = {}

    def query(self, model):
        mock_q = MagicMock()
        if model == Setting:
            def filter_func(condition):
                sub_q = MagicMock()
                val = getattr(getattr(condition, "right", None), "value", None)
                if isinstance(val, (list, tuple, set)):
                    matching = [self.settings[k] for k in val if k in self.settings]
                    sub_q.first.return_value = matching[0] if matching else None
                    sub_q.all.return_value = matching
                elif val and isinstance(val, str) and val in self.settings:
                    sub_q.first.return_value = self.settings[val]
                    sub_q.all.return_value = [self.settings[val]]
                else:
                    sub_q.first.return_value = None
                    sub_q.all.return_value = []
                sub_q.delete.side_effect = lambda synchronize_session=False: self.settings.clear()
                return sub_q
            mock_q.filter.side_effect = filter_func
        else:
            mock_q.filter.return_value.all.return_value = []
            mock_q.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []
            mock_q.filter.return_value.first.return_value = None
        return mock_q

    def add(self, obj):
        if isinstance(obj, Setting):
            self.settings[obj.key] = obj

    def commit(self):
        pass


def test_sync_google_classroom_session_valid():
    db = MockDB()
    user = {"id": "user_test_gcr"}
    payload = GoogleClassroomCookieSyncRequest(
        cookies=[
            {"name": "OSID", "value": "osid_val_12345", "domain": "classroom.google.com"},
            {"name": "SID", "value": "sid_val_67890", "domain": ".google.com"},
        ],
        user_agent="Mozilla/5.0 Test GCR Browser",
    )

    res = sync_google_classroom_session(payload, db=db, clerk_user=user)
    assert res["status"] == "connected"
    assert res["has_synced_session"] is True
    assert res["cookie_count"] == 2

    cookie_setting = db.settings.get("classroom:user_test_gcr:google_session_cookies")
    assert cookie_setting is not None
    decrypted = decrypt_token_if_encrypted(cookie_setting.value)
    loaded_cookies = json.loads(decrypted)
    assert len(loaded_cookies) == 2
    assert loaded_cookies[0]["name"] == "OSID"


def test_sync_google_classroom_session_string_format():
    db = MockDB()
    user = {"id": "user_test_gcr"}
    payload = GoogleClassroomCookieSyncRequest(
        cookies="OSID=string_osid_val; SID=string_sid_val; other=123",
        user_agent="Mozilla/5.0 Test Browser",
    )

    res = sync_google_classroom_session(payload, db=db, clerk_user=user)
    assert res["status"] == "connected"
    assert res["has_synced_session"] is True

    cookie_setting = db.settings.get("classroom:user_test_gcr:google_session_cookies")
    decrypted = decrypt_token_if_encrypted(cookie_setting.value)
    loaded_cookies = json.loads(decrypted)
    names = {c["name"] for c in loaded_cookies}
    assert "OSID" in names
    assert "SID" in names


def test_sync_google_classroom_session_rejects_missing_auth():
    db = MockDB()
    user = {"id": "user_test_gcr"}
    payload = GoogleClassroomCookieSyncRequest(
        cookies=[{"name": "some_random_cookie", "value": "123"}],
    )

    with pytest.raises(HTTPException) as exc_info:
        sync_google_classroom_session(payload, db=db, clerk_user=user)
    assert exc_info.value.status_code == 400
    assert "authentication tokens" in exc_info.value.detail.lower()


def test_disconnect_google_classroom_session():
    db = MockDB()
    user = {"id": "user_test_gcr"}
    db.settings["classroom:user_test_gcr:google_session_cookies"] = Setting(
        key="classroom:user_test_gcr:google_session_cookies",
        value="enc_cookies",
    )

    res = disconnect_google_classroom_session(db=db, clerk_user=user)
    assert res["status"] == "disconnected"
    assert res["has_synced_session"] is False
    assert "classroom:user_test_gcr:google_session_cookies" not in db.settings


def test_get_google_classroom_browser_status_with_synced_session():
    db = MockDB()
    user = {"id": "user_test_gcr"}
    db.settings["classroom:user_test_gcr:google_session_cookies"] = Setting(
        key="classroom:user_test_gcr:google_session_cookies",
        value="enc_cookies",
    )

    fake_client = MagicMock()
    fake_client.status.return_value = {"active": False, "profile_exists": True, "viewer_url": None}

    with patch("app.classroom.router.BrowserSessionClient.classroom", return_value=fake_client):
        res = get_google_classroom_browser_status(db=db, clerk_user=user)
        assert res["active"] is False
        assert res["profile_exists"] is True
        assert res["has_synced_session"] is True


def test_finish_quick_turn_in_auto_boots_and_injects_cookies():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.db.database import Base
    from app.core.security import encrypt_token_if_needed

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()

    user_id = "test_user_auto_turn_in"
    course = Course(id=1, external_id="course-ext-1", name="Test Course", user_id=user_id)
    assignment = Assignment(id=1, external_id="asgn-ext-1", course_id=1, title="Lab 1", user_id=user_id)
    submission = Submission(id=1, assignment_id=1, user_id=user_id, submission_state=SubmissionState.CREATED)
    digest_row = Setting(key=f"quick_turn_in_digest_test_1", value="digest123")

    # Stored synced Google session cookies
    cookies_json = json.dumps([{"name": "OSID", "value": "secret_osid", "domain": "classroom.google.com"}])
    cookie_setting = Setting(
        key=f"classroom:{user_id}:google_session_cookies",
        value=encrypt_token_if_needed(cookies_json),
    )
    db.add_all([course, assignment, submission, digest_row, cookie_setting])
    db.commit()

    fake_browser = MagicMock()
    # Initially inactive; should be booted automatically
    fake_browser.status.return_value = {"active": False, "profile_exists": False, "viewer_url": None}
    fake_browser.open.return_value = {"active": True, "viewer_url": "https://viewer.example.com"}

    mock_submit_calls = []

    def mock_submit_drive_files(**kwargs):
        mock_submit_calls.append(kwargs)
        return {"attached": 2, "turned_in": True}

    fake_classroom_service = MagicMock()
    fake_classroom_service.courses().courseWork().studentSubmissions().list().execute.return_value = {
        "studentSubmissions": [{"id": "sub-123", "state": "TURNED_IN"}]
    }

    with patch("app.classroom.router.BrowserSessionClient.classroom", return_value=fake_browser):
        with patch("app.services.classroom_browser_submission.submit_drive_files", side_effect=mock_submit_drive_files):
            res = _finish_quick_turn_in_in_classroom_browser(
                db=db,
                user_id=user_id,
                assignment=assignment,
                course=course,
                submission=submission,
                digest_row=digest_row,
                content_digest="digest123",
                google_doc_id="doc-123",
                google_doc_name="Solution Doc",
                zip_file_id="zip-123",
                zip_filename="Deliverables.zip",
                classroom_service=fake_classroom_service,
            )

            # Successfully auto-booted the browser session
            assert fake_browser.open.called
            # Successfully passed the decrypted cookies to submit_drive_files
            assert len(mock_submit_calls) == 1
            assert mock_submit_calls[0]["cookies"] == [{"name": "OSID", "value": "secret_osid", "domain": "classroom.google.com"}]
            # Submission succeeded and turned in
            assert res["success"] is True
            assert res["turned_in"] is True
            assert submission.submission_state == SubmissionState.TURNED_IN
            assert assignment.status == AssignmentStatus.SUBMITTED
