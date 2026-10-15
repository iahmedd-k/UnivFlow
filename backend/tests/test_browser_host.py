from pathlib import Path
from unittest.mock import MagicMock, patch
import json
import pytest
from fastapi import HTTPException

from app.services.browser_host import BrowserSessionHost


def test_clean_stale_locks(tmp_path: Path):
    """Verify that _clean_stale_locks removes SingletonLock, SingletonSocket, SingletonCookie."""
    lock_file = tmp_path / "SingletonLock"
    socket_file = tmp_path / "SingletonSocket"
    cookie_file = tmp_path / "SingletonCookie"
    other_file = tmp_path / "Preferences"

    lock_file.write_text("lock")
    socket_file.write_text("socket")
    cookie_file.write_text("cookie")
    other_file.write_text("{}")

    assert lock_file.exists()
    assert socket_file.exists()
    assert cookie_file.exists()
    assert other_file.exists()

    BrowserSessionHost._clean_stale_locks(tmp_path)

    assert not lock_file.exists()
    assert not socket_file.exists()
    assert not cookie_file.exists()
    assert other_file.exists()


def test_cdp_is_ready_true():
    """Verify _cdp_is_ready returns True when webSocketDebuggerUrl is returned."""
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps({"webSocketDebuggerUrl": "ws://127.0.0.1:12000/devtools"}).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        assert BrowserSessionHost._cdp_is_ready(12000) is True


def test_cdp_is_ready_false_on_connection_error():
    """Verify _cdp_is_ready returns False when connection fails."""
    with patch("urllib.request.urlopen", side_effect=OSError("Connection refused")):
        assert BrowserSessionHost._cdp_is_ready(12000) is False


def test_key_validation():
    """Verify profile key format validation."""
    valid_key = "a" * 64
    assert BrowserSessionHost._key(valid_key) == valid_key

    with pytest.raises(HTTPException) as exc_info:
        BrowserSessionHost._key("invalid-key")
    assert exc_info.value.status_code == 400
