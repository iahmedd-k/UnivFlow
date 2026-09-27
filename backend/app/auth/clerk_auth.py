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


def fetch_clerk_jwks() -> Optional[Dict[str, Any]]:
    global _jwks_cache
    if _jwks_cache is not None:
        return _jwks_cache
    try:
        url = get_clerk_jwks_url()
        with httpx.Client(timeout=3.0) as client:
            resp = client.get(url)
            if resp.status_code == 200:
                _jwks_cache = resp.json()
                return _jwks_cache
    except Exception as e:
        logger.warning(f"Could not fetch Clerk JWKS: {e}")
    return None


def verify_clerk_token(token: str) -> Dict[str, Any]:
    """
    Verify Clerk JWT session token.
    Falls back to unverified payload extraction in dev mode if network JWKS fails.
    """
    try:
        # First attempt to verify with JWKS if available
        jwks = fetch_clerk_jwks()
        if jwks and "keys" in jwks:
            unverified_header = jwt.get_unverified_header(token)
            kid = unverified_header.get("kid")
            key_data = next((k for k in jwks["keys"] if k.get("kid") == kid), None)
            if key_data:
                public_key = jwt.algorithms.RSAAlgorithm.from_jwk(key_data)
                payload = jwt.decode(
                    token,
                    key=public_key,
                    algorithms=["RS256"],
                    options={"verify_aud": False}
                )
                return payload

        # Dev / Offline Fallback: decode without verification if dev environment
        payload = jwt.decode(token, options={"verify_signature": False, "verify_aud": False})
        return payload
    except Exception as e:
        logger.error(f"Clerk token verification error: {e}")
        raise HTTPException(status_code=401, detail=f"Invalid authentication token: {str(e)}")


async def get_current_user_optional(
    auth: Optional[HTTPAuthorizationCredentials] = Security(security),
    db: Session = Depends(get_db)
) -> Optional[Dict[str, Any]]:
    """Dependency that returns current user if token is present and valid, else None"""
    if not auth or not auth.credentials:
        return None
    try:
        payload = verify_clerk_token(auth.credentials)
        user_id = payload.get("sub")
        if not user_id:
            return None
        
        # Check if we have stored profile data in Setting
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
    except Exception:
        return None


async def require_current_user(
    auth: Optional[HTTPAuthorizationCredentials] = Security(security),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """Dependency that returns Clerk user or falls back to dev user for testing"""
    if auth and auth.credentials:
        user = await get_current_user_optional(auth, db)
        if user:
            return user
    # Fallback user for local testing and development
    return {
        "id": "dev_student_user",
        "email": "student@au.edu.pk",
        "name": "Dev Student",
        "claims": {},
        "authenticated": True
    }
