from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.testclient import TestClient

from app.auth import clerk_auth, router as auth_module
from app.db.database import get_db
from app.v1.api.router import api_router


def test_google_callback_route_accepts_google_redirect_without_clerk_token(monkeypatch):
    app = FastAPI()
    app.include_router(api_router, prefix="/api/v1")
    app.dependency_overrides[get_db] = lambda: object()
    callback = Mock(
        return_value=RedirectResponse("/dashboard/classroom?google_connected=true")
    )
    monkeypatch.setattr(auth_module, "google_callback", callback)
    monkeypatch.setattr(clerk_auth.settings, "environment", "production")

    response = TestClient(app).get(
        "/api/v1/auth/google?code=google-code&state=oauth-state",
        follow_redirects=False,
    )

    assert response.status_code == 307
    assert response.headers["location"] == "/dashboard/classroom?google_connected=true"
    callback.assert_called_once()


def test_versioned_feature_routes_remain_authenticated(monkeypatch):
    app = FastAPI()
    app.include_router(api_router, prefix="/api/v1")
    monkeypatch.setattr(clerk_auth.settings, "environment", "production")

    response = TestClient(app).get("/api/v1/execution/languages")

    assert response.status_code == 401
