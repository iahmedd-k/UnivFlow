from unittest.mock import MagicMock, patch
import json
import pytest

from app.classroom.router import (
    get_onboarding_status,
    dismiss_onboarding,
    save_onboarding_data,
    OnboardingSavePayload,
)
from app.db.models import Setting
from app.core.security import decrypt_token_if_encrypted


class MockDB:
    def __init__(self):
        self.settings = {}

    def query(self, model):
        mock_q = MagicMock()
        if model == Setting:
            def filter_func(*conditions):
                sub_q = MagicMock()
                # Simple lookup in self.settings
                matched = []
                for cond in conditions:
                    # check if binary condition Setting.key == '...'
                    val = getattr(getattr(cond, "right", None), "value", None)
                    if val and isinstance(val, str) and val in self.settings:
                        matched.append(self.settings[val])
                    elif isinstance(val, (list, tuple, set)):
                        for k in val:
                            if k in self.settings:
                                matched.append(self.settings[k])

                sub_q.first.return_value = matched[0] if matched else None
                sub_q.all.return_value = matched
                return sub_q
            mock_q.filter.side_effect = filter_func
        else:
            mock_q.filter.return_value.all.return_value = []
            mock_q.filter.return_value.first.return_value = None
        return mock_q

    def add(self, obj):
        if isinstance(obj, Setting):
            self.settings[obj.key] = obj

    def commit(self):
        pass


def test_onboarding_status_unconfigured():
    db = MockDB()
    user = {"id": "user_onboarding_test"}

    with patch("app.services.claude_browser_solver.get_student_metadata", return_value={"student_name": "Student", "roll_no": ""}):
        with patch("app.db.repositories.GoogleCredentialRepository.get", return_value=None):
            res = get_onboarding_status(db=db, clerk_user=user)

    assert res["is_dismissed"] is False
    assert res["needs_onboarding"] is True
    assert res["should_show"] is True
    assert "profile" in res["missing_items"]
    assert "semester_date" in res["missing_items"]
    assert "google_classroom" in res["missing_items"]
    assert "claude_cookie" in res["missing_items"]
    assert "portal_cookie" in res["missing_items"]


def test_onboarding_dismiss():
    db = MockDB()
    user = {"id": "user_onboarding_test"}

    dismiss_res = dismiss_onboarding(db=db, clerk_user=user)
    assert dismiss_res["status"] == "dismissed"
    assert f"classroom:user_onboarding_test:onboarding_dismissed" in db.settings
    assert db.settings[f"classroom:user_onboarding_test:onboarding_dismissed"].value == "true"

    with patch("app.services.claude_browser_solver.get_student_metadata", return_value={"student_name": "Student", "roll_no": ""}):
        with patch("app.db.repositories.GoogleCredentialRepository.get", return_value=None):
            status = get_onboarding_status(db=db, clerk_user=user)

    assert status["is_dismissed"] is True
    assert status["should_show"] is False


def test_onboarding_save_and_configured():
    db = MockDB()
    user = {"id": "user_onboarding_test"}

    payload = OnboardingSavePayload(
        student_name="Ahmed Khan",
        roll_no="210984",
        semester_start_date="2026-09-01",
        claude_session_key="sk-ant-sid01-testkey1234567890",
        portal_cookies="ASP.NET_SessionId=test12345",
        dismiss=True,
    )

    save_res = save_onboarding_data(payload, db=db, clerk_user=user)
    assert save_res["status"] == "success"

    # Verify settings stored
    assert f"student_profile_user_onboarding_test" in db.settings
    profile_data = json.loads(db.settings[f"student_profile_user_onboarding_test"].value)
    assert profile_data["student_name"] == "Ahmed Khan"
    assert profile_data["roll_no"] == "210984"

    assert f"classroom:user_onboarding_test:semester_start_date" in db.settings
    assert db.settings[f"classroom:user_onboarding_test:semester_start_date"].value == "2026-09-01"

    assert f"classroom:user_onboarding_test:claude_session_key" in db.settings
    stored_claude_key = db.settings[f"classroom:user_onboarding_test:claude_session_key"].value
    assert stored_claude_key != "sk-ant-sid01-testkey1234567890"
    assert decrypt_token_if_encrypted(stored_claude_key) == "sk-ant-sid01-testkey1234567890"

    assert f"portal:user_onboarding_test:portal_session_cookies" in db.settings
    assert db.settings[f"portal:user_onboarding_test:portal_session_cookies"].value == "ASP.NET_SessionId=test12345"

    assert f"classroom:user_onboarding_test:onboarding_dismissed" in db.settings
    assert db.settings[f"classroom:user_onboarding_test:onboarding_dismissed"].value == "true"
