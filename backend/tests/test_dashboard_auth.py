from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.auth.clerk_auth import require_current_user
from app.db.database import get_db
from app.main import app


client = TestClient(app)


def reject_unauthenticated_user():
    raise HTTPException(status_code=401, detail="User not authenticated")


def test_dashboard_data_endpoints_require_current_user():
    app.dependency_overrides[get_db] = lambda: None
    app.dependency_overrides[require_current_user] = reject_unauthenticated_user
    try:
        for endpoint in (
            "/api/v1/dashboard/upcoming",
            "/api/v1/dashboard/overview",
        ):
            response = client.get(endpoint)
            assert response.status_code == 401, endpoint
    finally:
        app.dependency_overrides.pop(require_current_user, None)
        app.dependency_overrides.pop(get_db, None)
