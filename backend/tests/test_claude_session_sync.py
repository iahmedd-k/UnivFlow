from unittest.mock import MagicMock, patch
import pytest
from fastapi import HTTPException

from app.classroom.router import (
    sync_claude_session,
    disconnect_claude_session,
    get_claude_browser_status,
    set_automatic_claude_solving,
    ClaudeCookieSyncRequest,
)
from app.db.models import Setting
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


def test_sync_claude_session_valid():
    db = MockDB()
    user = {"id": "user_test_123"}
    payload = ClaudeCookieSyncRequest(
        session_key="sk-ant-sid01-abcdef1234567890abcdef1234567890",
        user_agent="Mozilla/5.0 Test Browser",
    )

    res = sync_claude_session(payload, db=db, clerk_user=user)
    assert res["status"] == "connected"
    assert res["has_session_key"] is True

    key_setting = db.settings.get("classroom:user_test_123:claude_session_key")
    assert key_setting is not None
    assert key_setting.value != "sk-ant-sid01-abcdef1234567890abcdef1234567890"
    assert decrypt_token_if_encrypted(key_setting.value) == "sk-ant-sid01-abcdef1234567890abcdef1234567890"


def test_sync_claude_session_strips_cookie_name():
    db = MockDB()
    user = {"id": "user_test_123"}
    payload = ClaudeCookieSyncRequest(
        session_key="sessionKey=sk-ant-sid01-abcdef1234567890abcdef1234567890; Path=/; Domain=.claude.ai",
    )

    res = sync_claude_session(payload, db=db, clerk_user=user)
    assert res["status"] == "connected"
    key_setting = db.settings.get("classroom:user_test_123:claude_session_key")
    assert decrypt_token_if_encrypted(key_setting.value) == "sk-ant-sid01-abcdef1234567890abcdef1234567890"


def test_sync_claude_session_rejects_too_short():
    db = MockDB()
    user = {"id": "user_test_123"}
    payload = ClaudeCookieSyncRequest(session_key="too-short")

    with pytest.raises(HTTPException) as exc_info:
        sync_claude_session(payload, db=db, clerk_user=user)
    assert exc_info.value.status_code == 400


def test_disconnect_claude_session():
    db = MockDB()
    user = {"id": "user_test_123"}
    db.settings["classroom:user_test_123:claude_session_key"] = Setting(
        key="classroom:user_test_123:claude_session_key",
        value="sk-ant-sid01-test",
    )

    res = disconnect_claude_session(db=db, clerk_user=user)
    assert res["status"] == "disconnected"
    assert res["has_session_key"] is False
    assert len(db.settings) == 0
