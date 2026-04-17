from storage.base import *
from utils.crypto import encrypt, decrypt

TABLE = "github_config"
SCHEMA = {"id": str, "token_enc": str, "username": str, "created_at": str, "updated_at": str}


def save(token: str, username: str):
    upsert(TABLE, SCHEMA, "id", "singleton", {
        "id": "singleton", "token_enc": encrypt(token),
        "username": username, "created_at": now(), "updated_at": now(),
    })


def get_config() -> dict | None:
    return find_one(TABLE, SCHEMA, "id", "singleton")


def get_token() -> str | None:
    cfg = get_config()
    return decrypt(cfg["token_enc"]) if cfg and cfg.get("token_enc") else None


def get_username() -> str | None:
    cfg = get_config()
    return cfg.get("username") if cfg else None
