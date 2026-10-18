from fastapi import HTTPException

from app.core.config import settings


def require_user_id(clerk_user: dict | None) -> str:
    """Return the authenticated Clerk subject, with the app's local dev identity."""
    user_id = str((clerk_user or {}).get("id") or "").strip()
    if user_id:
        return user_id
    if not settings.is_production:
        return "dev_student_user"
    raise HTTPException(status_code=401, detail="Sign in to access this resource.")


def user_owner_ids(user_id: str) -> tuple[str, ...]:
    """Include pre-account legacy rows only for the isolated local dev user."""
    if user_id == "dev_student_user" and not settings.is_production:
        return (user_id, "legacy")
    return (user_id,)
