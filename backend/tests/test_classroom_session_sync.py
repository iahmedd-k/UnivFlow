from unittest.mock import MagicMock, patch
import json
import pytest
from fastapi import HTTPException

from app.classroom.router import (
    sync_google_classroom_session,
    disconnect_google_classroom_session,
    get_google_classroom_browser_status,
    GoogleClassroomCookieSyncRequest,
    execute_quick_turn_in,
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

    res = get_google_classroom_browser_status(db=db, clerk_user=user)
    assert res["active"] is False
    assert res["profile_exists"] is True
    assert res["has_synced_session"] is True
    assert res["extension_managed"] is True


def test_execute_quick_turn_in_attach_only():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.db.database import Base
    from app.db.models import AssignmentSolution

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()

    user_id = "test_user_attach_only"
    course = Course(id=1, external_id="c-ext-1", name="Test Course", user_id=user_id)
    assignment = Assignment(id=1, external_id="a-ext-1", course_id=1, title="Lab 1", user_id=user_id)
    solution = AssignmentSolution(id=1, assignment_id=1, user_id=user_id, validated_content="# Solution\n```python\nprint('hello')\n```")
    submission = Submission(id=1, assignment_id=1, user_id=user_id, google_doc_id="doc-123")
    db.add_all([course, assignment, solution, submission])
    db.commit()

    fake_classroom_service = MagicMock()
    fake_docs_service = MagicMock()
    fake_docs_service.upload_file.return_value = {"id": "zip-123"}
    fake_docs_service.remove_public_sharing.return_value = True
    fake_docs_service.get_file.return_value = {"name": "Solution Doc"}

    with patch("app.services.ai_solution.export_solution_to_google_doc", return_value={"doc_id": "doc-123"}):
        with patch("app.classroom.router.get_classroom_service", return_value=MagicMock(service=fake_classroom_service)):
            with patch("app.classroom.router.get_google_docs_service", return_value=fake_docs_service):
                with patch("app.classroom.router._attach_submission_files", return_value=("sub-123", "NEW")):
                    res = execute_quick_turn_in(db, assignment_id=1, user_id=user_id, action="attach_only")
                    assert res["success"] is True
                    assert res["action_taken"] == "attached_draft"
                    assert res["turned_in"] is False
                    assert res["classroom_submission_id"] == "sub-123"
                    assert submission.submission_state == SubmissionState.CREATED
