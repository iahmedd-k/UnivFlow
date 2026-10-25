import base64
import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from cryptography.fernet import Fernet
from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

logger = logging.getLogger(__name__)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(
    subject: str | int,
    extra_claims: dict[str, Any] | None = None,
    expires_delta: timedelta | None = None,
) -> str:
    expires_delta = expires_delta or timedelta(
        minutes=getattr(settings, "jwt_access_token_expire_minutes", 60)
    )
    expire = datetime.now(timezone.utc) + expires_delta
    to_encode: dict[str, Any] = {
        "sub": str(subject),
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "type": "access",
    }
    if extra_claims:
        to_encode.update(extra_claims)
    secret = getattr(settings, "jwt_secret_key", settings.secret_key or "default-secret-change-me")
    algorithm = getattr(settings, "jwt_algorithm", "HS256")
    return jwt.encode(to_encode, secret, algorithm=algorithm)


def decode_access_token(token: str) -> dict[str, Any]:
    secret = getattr(settings, "jwt_secret_key", settings.secret_key or "default-secret-change-me")
    algorithm = getattr(settings, "jwt_algorithm", "HS256")
    return jwt.decode(
        token,
        secret,
        algorithms=[algorithm],
    )


ENCRYPTION_KEY_VERSION = "v1"


def _derive_key(key_material: str) -> bytes:
    return base64.urlsafe_b64encode(hashlib.sha256(key_material.encode()).digest())


def get_encryption_key(version: str = ENCRYPTION_KEY_VERSION) -> bytes:
    if version == "v1":
        key = settings.secret_key if hasattr(settings, "secret_key") and settings.secret_key else "default-secret-change-me"
        return _derive_key(key)
    elif version == "v2":
        if not hasattr(settings, "encryption_key_v2") or not settings.encryption_key_v2:
            raise ValueError("encryption_key_v2 not configured in settings")
        return _derive_key(settings.encryption_key_v2)
    else:
        raise ValueError(f"Unknown encryption key version: {version}")


def get_current_key_version() -> str:
    return ENCRYPTION_KEY_VERSION


def encrypt_token(token: str, version: str = None) -> str:
    version = version or get_current_key_version()
    f = Fernet(get_encryption_key(version))
    encrypted = f.encrypt(token.encode()).decode()
    return json.dumps({"v": version, "data": encrypted})


def is_encrypted_token(value: str) -> bool:
    if not value:
        return False
    try:
        payload = json.loads(value)
        return isinstance(payload, dict) and payload.get("v") in {"v1", "v2"} and bool(payload.get("data"))
    except (json.JSONDecodeError, TypeError):
        return False


def encrypt_token_if_needed(value: str | None) -> str | None:
    if not value or is_encrypted_token(value):
        return value
    return encrypt_token(value)


def decrypt_token_if_encrypted(value: str | None) -> str | None:
    if not value:
        return value
    if is_encrypted_token(value):
        return decrypt_token(value)
    return value


def get_google_credential_tokens(db, credential) -> tuple[str | None, str | None]:
    """Read OAuth tokens and transparently migrate a legacy plaintext row."""
    access = decrypt_token_if_encrypted(credential.access_token)
    refresh = decrypt_token_if_encrypted(credential.refresh_token)
    changed = False
    if access != credential.access_token:
        credential.access_token = encrypt_token_if_needed(access)
        changed = True
    if refresh != credential.refresh_token:
        credential.refresh_token = encrypt_token_if_needed(refresh)
        changed = True
    if changed:
        db.commit()
    return access, refresh


def decrypt_token(encrypted_token: str) -> str:
    try:
        payload = json.loads(encrypted_token)
        version = payload.get("v", "v1")
        data = payload["data"]
    except (json.JSONDecodeError, KeyError):
        version = "v1"
        data = encrypted_token
    
    f = Fernet(get_encryption_key(version))
    return f.decrypt(data.encode()).decode()


def reencrypt_token(encrypted_token: str, target_version: str = None) -> str:
    plaintext = decrypt_token(encrypted_token)
    return encrypt_token(plaintext, target_version or get_current_key_version())
