from cryptography.fernet import Fernet
from app.core.config import settings
import base64
import hashlib
import json
import logging

logger = logging.getLogger(__name__)

ENCRYPTION_KEY_VERSION = "v1"

def _derive_key(key_material: str) -> bytes:
    return base64.urlsafe_b64encode(hashlib.sha256(key_material.encode()).digest())

def get_encryption_key(version: str = ENCRYPTION_KEY_VERSION) -> bytes:
    if version == "v1":
        key = settings.secret_key if hasattr(settings, 'secret_key') and settings.secret_key else "default-secret-change-me"
        return _derive_key(key)
    elif version == "v2":
        if not hasattr(settings, 'encryption_key_v2') or not settings.encryption_key_v2:
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