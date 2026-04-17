"""
Encrypted JSON storage for hosts and service records.
All sensitive fields (passwords, keys) are encrypted with Fernet before writing to disk.
"""
import json
import os
from cryptography.fernet import Fernet

STORAGE_FILE = os.path.join(os.path.dirname(__file__), "data.json")
KEY_FILE = os.path.join(os.path.dirname(__file__), ".storage_key")

DEFAULT_HOST = {
    "id": "default",
    "host": "",
    "username": "root",
    "password": "DEFAULT_HOST_PASSWORD",  # replaced at runtime
    "ssh_key": None,
    "is_default": True,
    "status": "unknown",
    "port": None,
}


def _get_fernet() -> Fernet:
    if os.path.exists(KEY_FILE):
        key = open(KEY_FILE, "rb").read()
    else:
        key = Fernet.generate_key()
        with open(KEY_FILE, "wb") as f:
            f.write(key)
        os.chmod(KEY_FILE, 0o600)
    return Fernet(key)


def _encrypt(value: str) -> str:
    return _get_fernet().encrypt(value.encode()).decode()


def _decrypt(value: str) -> str:
    return _get_fernet().decrypt(value.encode()).decode()


def _load() -> dict:
    if not os.path.exists(STORAGE_FILE):
        return {"hosts": [], "services": []}
    with open(STORAGE_FILE) as f:
        return json.load(f)


def _save(data: dict):
    with open(STORAGE_FILE, "w") as f:
        json.dump(data, f, indent=2)
    os.chmod(STORAGE_FILE, 0o600)


# ── Bootstrap default host ────────────────────────────────────────────────────

def seed_default_host(password: str):
    """Called once on startup to seed the default host if no hosts exist."""
    data = _load()
    if data["hosts"]:
        return  # already seeded
    host = DEFAULT_HOST.copy()
    host["password"] = _encrypt(password)
    data["hosts"].append(host)
    _save(data)


# ── Host operations ───────────────────────────────────────────────────────────

def list_hosts() -> list[dict]:
    return _load()["hosts"]


def get_host(host_id: str) -> dict | None:
    for h in _load()["hosts"]:
        if h["id"] == host_id or h["host"] == host_id:
            return h
    return None


def get_default_host() -> dict | None:
    for h in _load()["hosts"]:
        if h.get("is_default"):
            return h
    hosts = _load()["hosts"]
    return hosts[0] if hosts else None


def decrypt_password(host: dict) -> str | None:
    p = host.get("password")
    return _decrypt(p) if p else None


def add_host(host: str, username: str, password: str = None, ssh_key: str = None) -> dict:
    data = _load()
    host_id = host.replace(".", "-")
    record = {
        "id": host_id,
        "host": host,
        "username": username,
        "password": _encrypt(password) if password else None,
        "ssh_key": _encrypt(ssh_key) if ssh_key else None,
        "is_default": len(data["hosts"]) == 0,
        "status": "unknown",
        "port": None,
    }
    # Remove existing entry with same host if present
    data["hosts"] = [h for h in data["hosts"] if h["host"] != host]
    data["hosts"].append(record)
    _save(data)
    return record


def update_host(host_id: str, **kwargs):
    data = _load()
    for h in data["hosts"]:
        if h["id"] == host_id or h["host"] == host_id:
            if "password" in kwargs and kwargs["password"]:
                kwargs["password"] = _encrypt(kwargs["password"])
            if "ssh_key" in kwargs and kwargs["ssh_key"]:
                kwargs["ssh_key"] = _encrypt(kwargs["ssh_key"])
            h.update(kwargs)
            break
    _save(data)


def set_default_host(host_id: str):
    data = _load()
    for h in data["hosts"]:
        h["is_default"] = (h["id"] == host_id or h["host"] == host_id)
    _save(data)


# ── Service port operations ───────────────────────────────────────────────────

def get_service_port(service_name: str, host_id: str) -> int | None:
    for s in _load()["services"]:
        if s["service"] == service_name and s["host_id"] == host_id:
            return s["port"]
    return None


def save_service_port(service_name: str, host_id: str, port: int):
    data = _load()
    data["services"] = [s for s in data["services"] if not (s["service"] == service_name and s["host_id"] == host_id)]
    data["services"].append({"service": service_name, "host_id": host_id, "port": port})
    _save(data)
