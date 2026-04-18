from storage.base import *

TABLE = "agents"
SCHEMA = {
    "id": str,
    "project_name": str,
    "session_id": str,
    "parent_session_id": str,
    "control_channel_id": str,
    "parent_channel_id": str,
    "thread_id": str,
    "thread_name": str,
    "name": str,
    "role": str,
    "status": str,          # idle | running | failed | closed
    "current_task": str,
    "last_result": str,
    "last_error": str,
    "pid": str,
    "log_path": str,
    "user_id": str,
    "created_at": str,
    "updated_at": str,
}


def create(agent_id: str, project_name: str, session_id: str, parent_session_id: str,
           name: str, role: str, user_id: str, control_channel_id: str = "",
           parent_channel_id: str = "", thread_id: str = "", thread_name: str = "") -> dict:
    rec = {
        "id": agent_id,
        "project_name": project_name,
        "session_id": session_id,
        "parent_session_id": parent_session_id,
        "control_channel_id": control_channel_id,
        "parent_channel_id": parent_channel_id,
        "thread_id": thread_id,
        "thread_name": thread_name,
        "name": name,
        "role": role,
        "status": "idle",
        "current_task": "",
        "last_result": "",
        "last_error": "",
        "pid": "",
        "log_path": "",
        "user_id": user_id,
        "created_at": now(),
        "updated_at": now(),
    }
    upsert(TABLE, SCHEMA, "id", agent_id, rec)
    return rec


def get(agent_id: str) -> dict | None:
    return find_one(TABLE, SCHEMA, "id", agent_id)


def get_by_session(session_id: str) -> dict | None:
    return find_one(TABLE, SCHEMA, "session_id", session_id)


def list_all(include_closed: bool = False) -> list[dict]:
    rows = find_all(TABLE, SCHEMA)
    rows.sort(key=lambda r: (r.get("updated_at", ""), r.get("created_at", ""), r.get("id", "")))
    if include_closed:
        return rows
    return [r for r in rows if r.get("status") != "closed"]


def list_for_project(project_name: str, include_closed: bool = False) -> list[dict]:
    rows = [r for r in list_all(include_closed=True) if r.get("project_name") == project_name]
    if include_closed:
        return rows
    return [r for r in rows if r.get("status") != "closed"]


def list_for_parent(parent_session_id: str, include_closed: bool = False) -> list[dict]:
    rows = [r for r in list_all(include_closed=True) if r.get("parent_session_id") == parent_session_id]
    if include_closed:
        return rows
    return [r for r in rows if r.get("status") != "closed"]


def active_count_for_project(project_name: str) -> int:
    return len([r for r in list_for_project(project_name, include_closed=False)])


def update(agent_id: str, fields: dict):
    payload = dict(fields)
    payload["updated_at"] = now()
    upsert(TABLE, SCHEMA, "id", agent_id, payload)


def mark_running(agent_id: str, task: str, pid: str = "", log_path: str = ""):
    update(agent_id, {
        "status": "running",
        "current_task": task[:4000],
        "last_error": "",
        "pid": pid,
        "log_path": log_path,
    })


def mark_idle(agent_id: str, result: str = ""):
    update(agent_id, {
        "status": "idle",
        "current_task": "",
        "last_result": result[:4000],
        "last_error": "",
        "pid": "",
    })


def mark_failed(agent_id: str, error: str):
    update(agent_id, {
        "status": "failed",
        "last_error": error[:4000],
        "pid": "",
    })


def close(agent_id: str):
    update(agent_id, {
        "status": "closed",
        "current_task": "",
        "pid": "",
    })
