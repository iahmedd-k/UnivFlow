from cryptography.fernet import Fernet
from app.core.config import settings
import base64
import hashlib


def get_encryption_key() -> bytes:
    key = settings.secret_key if hasattr(settings, 'secret_key') else "default-secret-change-me"
    return base64.urlsafe_b64encode(hashlib.sha256(key.encode()).digest())


def encrypt_token(token: str) -> str:
    f = Fernet(get_encryption_key())
    return f.encrypt(token.encode()).decode()


def decrypt_token(encrypted_token: str) -> str:
    f = Fernet(get_encryption_key())
    return f.decrypt(encrypted_token.encode()).decode()