from storage.base import *

TABLE = "projects"
SCHEMA = {
    "id": str, "name": str, "path": str, "description": str,
    "created_at": str, "updated_at": str,
    "active_channel_id": str, "active_thread_id": str,
    "git_branch": str, "last_used_by": str,
}


def add(name: str, path: str, description: str = "") -> dict:
    from utils.security import validate_project_path
    real = validate_project_path(path)
    rec = {"id": new_id(), "name": name, "path": real, "description": description, "created_at": now(), "updated_at": now()}
    upsert(TABLE, SCHEMA, "name", name, rec)
    return rec


def get(name: str) -> dict | None:
    return find_one(TABLE, SCHEMA, "name", name)


def get_by_channel(channel_id: str) -> dict | None:
    return find_one(TABLE, SCHEMA, "active_channel_id", channel_id)


def list_all() -> list[dict]:
    return find_all(TABLE, SCHEMA)


def set_active_channel(name: str, channel_id: str, thread_id: str = ""):
    for proj in find_all(TABLE, SCHEMA):
        if proj.get("active_channel_id") == channel_id and proj.get("name") != name:
            upsert(TABLE, SCHEMA, "name", proj["name"], {"active_channel_id": "", "active_thread_id": ""})
    upsert(TABLE, SCHEMA, "name", name, {"active_channel_id": channel_id, "active_thread_id": thread_id})


def remove(name: str):
    delete_where(TABLE, SCHEMA, "name", name)


def clear_active_channel(channel_id: str):
    """Remove channel→project binding so the channel has no active project."""
    proj = find_one(TABLE, SCHEMA, "active_channel_id", channel_id)
    if proj:
        upsert(TABLE, SCHEMA, "name", proj["name"], {"active_channel_id": "", "active_thread_id": ""})


def update_branch(name: str, branch: str):
    upsert(TABLE, SCHEMA, "name", name, {"git_branch": branch})
