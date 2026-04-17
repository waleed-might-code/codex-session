"""
Fernet-based encryption for credentials at rest.
Key is stored in .storage_key; auto-generated on first run.
"""
import os
from cryptography.fernet import Fernet

_KEY_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".storage_key")
_fernet: Fernet | None = None


def _get() -> Fernet:
    global _fernet
    if _fernet:
        return _fernet
    env_key = os.getenv("ENCRYPTION_KEY", "").strip()
    if env_key:
        key = env_key.encode()
    elif os.path.exists(_KEY_FILE):
        key = open(_KEY_FILE, "rb").read().strip()
    else:
        key = Fernet.generate_key()
        with open(_KEY_FILE, "wb") as f:
            f.write(key)
        os.chmod(_KEY_FILE, 0o600)
    _fernet = Fernet(key)
    return _fernet


def encrypt(value: str) -> str:
    if not value:
        return ""
    return _get().encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    if not value:
        return ""
    return _get().decrypt(value.encode()).decode()


def is_encrypted(value: str) -> bool:
    return value.startswith("gAAAAA")
