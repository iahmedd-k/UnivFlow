from urllib.parse import parse_qs, urlsplit
from unittest.mock import Mock

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.auth import router


def test_google_oauth_callback_does_not_require_clerk_session(monkeypatch):
    request = Request({
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "scheme": "https",
        "path": "/api/v1/auth/google",
        "query_string": b"code=google-auth-code&state=csrf-state",
        "headers": [],
        "client": ("127.0.0.1", 12345),
        "server": ("example.com", 443),
    })
    db = object()
    callback_result = object()
    callback_args = {}

    def handle_callback(*, request, db):
        callback_args.update(request=request, db=db)
        return callback_result

    monkeypatch.setattr(router, "_check_rate_limit", Mock(side_effect=KeyError("key")))
    monkeypatch.setattr(router, "google_callback", handle_callback)

    result = router.google_auth(request=request, db=db, clerk_user=None)

    assert result is callback_result
    assert callback_args == {"request": request, "db": db}


def test_google_callback_redirects_safely_when_state_store_raises_key_error(monkeypatch):
    request = Request({
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "scheme": "https",
        "path": "/api/v1/auth/google",
        "query_string": b"code=google-auth-code&state=csrf-state",
        "headers": [],
        "client": ("127.0.0.1", 12345),
        "server": ("example.com", 443),
    })
    db = Mock()
    db.query.side_effect = KeyError("key")
    monkeypatch.setattr(router.settings, "frontend_url", "https://uniflow.example")

    response = router.google_callback(request=request, db=db)
    parsed = urlsplit(response.headers["location"])

    assert response.status_code == 302
    assert parsed.netloc == "uniflow.example"
    assert parse_qs(parsed.query) == {"google_error": ["callback_failed"]}
    db.rollback.assert_called_once()


def test_starting_google_oauth_still_requires_clerk_session(monkeypatch):
    request = Request({
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "scheme": "https",
        "path": "/api/v1/auth/google",
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 12345),
        "server": ("example.com", 443),
    })

    monkeypatch.setattr(router, "_check_rate_limit", Mock())

    with pytest.raises(HTTPException) as error:
        router.google_auth(request=request, db=object(), clerk_user=None)

    assert error.value.status_code == 401


def test_oauth_redirect_returns_to_classroom_and_preserves_query(monkeypatch):
    monkeypatch.setattr(router.settings, "frontend_url", "https://uniflow.example")

    redirect_url = router._oauth_frontend_redirect(
        "/dashboard/classroom?tab=courses",
        google_connected="true",
        email="student+classroom@example.com",
    )
    parsed = urlsplit(redirect_url)

    assert parsed.scheme == "https"
    assert parsed.netloc == "uniflow.example"
    assert parsed.path == "/dashboard/classroom"
    assert parse_qs(parsed.query) == {
        "tab": ["courses"],
        "google_connected": ["true"],
        "email": ["student+classroom@example.com"],
    }


def test_oauth_redirect_rejects_external_destination(monkeypatch):
    monkeypatch.setattr(router.settings, "frontend_url", "https://uniflow.example")

    redirect_url = router._oauth_frontend_redirect(
        "https://attacker.example/steal",
        google_error="access_denied",
    )

    assert redirect_url == "https://uniflow.example?google_error=access_denied"


def test_oauth_redirect_defaults_to_vercel_when_frontend_url_is_azure_vm(monkeypatch):
    monkeypatch.setattr(
        router.settings,
        "frontend_url",
        "https://univlfow.koreacentral.cloudapp.azure.com",
    )

    redirect_url = router._oauth_frontend_redirect(
        "/dashboard/classroom",
        google_connected="true",
    )
    parsed = urlsplit(redirect_url)

    assert parsed.scheme == "https"
    assert parsed.netloc == "univ-flow-bt12.vercel.app"
    assert parsed.path == "/dashboard/classroom"
    assert parse_qs(parsed.query) == {"google_connected": ["true"]}


def test_oauth_redirect_preserves_state_frontend_origin(monkeypatch):
    monkeypatch.setattr(
        router.settings,
        "frontend_url",
        "https://univlfow.koreacentral.cloudapp.azure.com",
    )

    redirect_url = router._oauth_frontend_redirect(
        "/dashboard/classroom",
        frontend_origin="https://univ-flow-bt12.vercel.app",
        google_connected="true",
    )
    parsed = urlsplit(redirect_url)

    assert parsed.netloc == "univ-flow-bt12.vercel.app"
    assert parsed.path == "/dashboard/classroom"


def test_safe_oauth_redirect_to_accepts_dashboard_root():
    assert router._safe_oauth_redirect_to("/dashboard") == "/dashboard"
    assert router._safe_oauth_redirect_to("/dashboard/classroom") == "/dashboard/classroom"
    assert router._safe_oauth_redirect_to(None) is None

