import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app.auth import clerk_auth
from app.core.config import settings


@pytest.mark.asyncio
async def test_required_user_rejects_missing_production_session(monkeypatch):
    monkeypatch.setattr(settings, "environment", "production")

    with pytest.raises(HTTPException) as error:
        await clerk_auth.require_current_user(auth=None, db=None)

    assert error.value.status_code == 401


@pytest.mark.asyncio
async def test_required_user_uses_development_identity_only_without_token(monkeypatch):
    monkeypatch.setattr(settings, "environment", "development")

    user = await clerk_auth.require_current_user(auth=None, db=None)

    assert user["id"] == "dev_student_user"


@pytest.mark.asyncio
async def test_required_user_does_not_downgrade_invalid_token_to_development_user(monkeypatch):
    monkeypatch.setattr(settings, "environment", "development")

    def reject_token(token):
        raise HTTPException(status_code=401, detail="Invalid authentication token")

    monkeypatch.setattr(clerk_auth, "verify_clerk_token", reject_token)
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="invalid")

    with pytest.raises(HTTPException) as error:
        await clerk_auth.require_current_user(auth=credentials, db=None)

    assert error.value.status_code == 401
