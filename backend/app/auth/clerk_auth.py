import jwt
import httpx
import json
from typing import Optional, Dict, Any
from fastapi import Request, HTTPException, Depends, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from app.core.config import settings
from app.core.logging import logger
from app.db.database import get_db
from app.db.models import Setting

security = HTTPBearer(auto_error=False)

# Cache for Clerk JWKS
_jwks_cache: Optional[Dict[str, Any]] = None


def get_clerk_jwks_url() -> str:
    """Derive Clerk JWKS URL from Publishable Key or API default"""
    pk = settings.clerk_publishable_key
    if pk:
        try:
            raw = pk.replace("pk_test_", "").replace("pk_live_", "")
            padded = raw + "=" * (-len(raw) % 4)
            import base64
            frontend_api = base64.b64decode(padded).decode("utf-8").rstrip("$")
            if frontend_api:
                return f"https://{frontend_api}/.well-known/jwks.json"
        except Exception:
            pass
    return "https://api.clerk.com/v1/jwks"


def fetch_clerk_jwks(force_refresh: bool = False) -> Optional[Dict[str, Any]]:
    global _jwks_cache
    if _jwks_cache is not None and not force_refresh:
        return _jwks_cache
    try:
        url = get_clerk_jwks_url()
        with httpx.Client(timeout=4.0) as client:
            resp = client.get(url)
            if resp.status_code == 200:
                _jwks_cache = resp.json()
                return _jwks_cache
    except Exception as e:
        logger.warning(f"Could not fetch Clerk JWKS: {e}")
    return _jwks_cache


def verify_clerk_token(token: str) -> Dict[str, Any]:
    """
    Verify Clerk JWT session token against Clerk JWKS public keys.
    """
    if not token:
        raise HTTPException(status_code=401, detail="Missing authentication token")

    try:
        unverified_header = jwt.get_unverified_header(token)
        kid = unverified_header.get("kid")

        jwks = fetch_clerk_jwks()
        key_data = None
        if jwks and "keys" in jwks:
            key_data = next((k for k in jwks["keys"] if k.get("kid") == kid), None)
            if not key_data and kid:
                # Key might have rotated, refresh JWKS once
                jwks = fetch_clerk_jwks(force_refresh=True)
                if jwks and "keys" in jwks:
                    key_data = next((k for k in jwks["keys"] if k.get("kid") == kid), None)

        if key_data:
            public_key = jwt.algorithms.RSAAlgorithm.from_jwk(key_data)
            payload = jwt.decode(
                token,
                key=public_key,
                algorithms=["RS256"],
                options={"verify_aud": False, "verify_iat": False},
                leeway=120,
            )
            return payload

        # No valid key found - token cannot be verified
        raise HTTPException(status_code=401, detail="Unable to verify token signature: public keys unavailable")

    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Authentication token has expired")
    except jwt.InvalidTokenError as e:
        raise HTTPException(status_code=401, detail=f"Invalid authentication token: {str(e)}")
    except Exception as e:
        logger.error(f"Clerk token verification error: {e}")
        raise HTTPException(status_code=401, detail=f"Authentication error: {str(e)}")


async def get_current_user_optional(
    auth: Optional[HTTPAuthorizationCredentials] = Security(security),
    db: Session = Depends(get_db)
) -> Optional[Dict[str, Any]]:
    """Return the current user when a bearer token is present and valid."""
    if not auth or not auth.credentials:
        return None
    payload = verify_clerk_token(auth.credentials)
    user_id = payload.get("sub")
    if not isinstance(user_id, str) or not user_id:
        raise HTTPException(status_code=401, detail="Authentication token has no user identity")

    # Check if user has been deleted (session revoked)
    revoked = db.query(Setting).filter(Setting.key == f"clerk_user_revoked_{user_id}").first()
    if revoked:
        raise HTTPException(status_code=401, detail="User account has been deactivated")

    setting = db.query(Setting).filter(Setting.key == f"clerk_user_{user_id}").first()
    profile = json.loads(setting.value) if setting and setting.value else {}

    email = profile.get("email") or payload.get("email") or payload.get("primary_email_address") or ""
    name = profile.get("first_name", "") + " " + profile.get("last_name", "")
    name = name.strip() or payload.get("name") or "Student"

    return {
        "id": user_id,
        "email": email,
        "name": name,
        "claims": payload,
        "authenticated": True
    }


async def require_current_user(
    auth: Optional[HTTPAuthorizationCredentials] = Security(security),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """Require a Clerk session - dev fallback in development only."""
    if auth and auth.credentials:
        user = await get_current_user_optional(auth, db)
        if user is not None:
            return user

    if settings.is_production:
        raise HTTPException(status_code=401, detail="Sign in to access this resource.")
    
    # Development fallback - return a default dev user
    return {
        "id": "dev_student_user",
        "first_name": "Dev",
        "last_name": "User",
        "email": "dev@local.test",
    }
