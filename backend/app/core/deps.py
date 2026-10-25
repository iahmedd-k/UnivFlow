import logging
from collections.abc import Callable

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import jwt
from sqlalchemy.orm import Session

from app.core.exceptions import ForbiddenError, UnauthorizedError
from app.core.security import decode_access_token
from app.db import get_db
from app.models.user import User, UserRole
from app.repositories.user_repo import UserRepository

logger = logging.getLogger(__name__)

bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise UnauthorizedError("Not authenticated")

    token = credentials.credentials
    user_repo = UserRepository(db)

    # 1. Try decoding with local secret key (native JWT)
    try:
        payload = decode_access_token(token)
        user_id = payload.get("sub")
        if user_id is not None and str(user_id).isdigit():
            user = user_repo.get_by_id(int(user_id))
            if user:
                if not user.is_active:
                    raise UnauthorizedError("Inactive user")
                return user
    except Exception:
        pass

    # 2. Try decoding as Clerk JWT
    try:
        claims = jwt.get_unverified_claims(token)
        clerk_user_id = claims.get("sub")
        if clerk_user_id:
            email = (
                claims.get("email")
                or claims.get("primary_email_address")
                or f"{clerk_user_id}@clerk.user"
            )
            user = user_repo.get_by_email(email)
            if user is None:
                first_name = (
                    claims.get("given_name")
                    or claims.get("first_name")
                    or "User"
                )
                last_name = claims.get("family_name") or claims.get("last_name") or ""
                user = user_repo.create(
                    first_name=first_name,
                    last_name=last_name,
                    email=email,
                    password_hash="clerk_managed",
                )
            if not user.is_active:
                raise UnauthorizedError("Inactive user")
            return user
    except Exception as exc:
        logger.error(f"Error during Clerk token resolution: {exc}", exc_info=True)
        raise UnauthorizedError("Invalid authentication token") from exc

    raise UnauthorizedError("Invalid token payload")


def require_role(*roles: UserRole) -> Callable:
    def role_checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in roles:
            raise ForbiddenError("Insufficient permissions")

        return current_user

    return role_checker