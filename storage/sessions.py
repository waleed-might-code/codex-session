from storage.base import *

TABLE = "sessions"
SCHEMA = {
    "id": str, "project_name": str, "channel_id": str, "thread_id": str,
    "user_id": str, "created_at": str, "updated_at": str,
    "status": str,   # active | closed
    "model": str, "message_count": str, "last_prompt": str,
    "backend": str, "backend_session_id": str,
}

TABLE_SUMMARIES = "session_summaries"
SUMMARY_SCHEMA = {
    "id": str, "session_id": str, "summary": str,
    "task_requested": str, "task_completed": str, "task_remaining": str,
    "created_at": str,
}

TABLE_RESUME = "session_resume"
RESUME_SCHEMA = {
    "id": str, "session_id": str, "context": str, "created_at": str,
}

TABLE_MESSAGES = "session_messages"
MESSAGE_SCHEMA = {
    "id": str, "session_id": str, "project_name": str, "channel_id": str,
    "role": str, "content": str, "created_at": str,
}

# In-memory message history: {session_id: [{"role": ..., "content": ...}]}
_history: dict[str, list] = {}

# Resume context saved when step limit is hit (also persisted to CSV)
_resume_ctx: dict[str, str] = {}


def create(project_name: str, channel_id: str, user_id: str, thread_id: str = "", model: str = "") -> dict:
    rec = {
        "id": new_id(), "project_name": project_name,
        "channel_id": channel_id, "thread_id": thread_id,
        "user_id": user_id, "created_at": now(), "updated_at": now(),
        "status": "active", "model": model or "codex-cli",
        "message_count": "0", "last_prompt": "",
        "backend": "codex", "backend_session_id": "",
    }
    upsert(TABLE, SCHEMA, "id", rec["id"], rec)
    _history[rec["id"]] = []
    return rec


def _select_latest_active(rows: list[dict]) -> dict | None:
    active = [r for r in rows if r["status"] == "active"]
    if not active:
        return None
    active.sort(key=lambda r: (r.get("updated_at", ""), r.get("created_at", ""), r.get("id", "")))
    return active[-1]


def get(session_id: str) -> dict | None:
    return find_one(TABLE, SCHEMA, "id", session_id)


def get_active_for_channel(channel_id: str) -> dict | None:
    rows = find_all(TABLE, SCHEMA, "channel_id", channel_id)
    latest = _select_latest_active(rows)
    if not latest:
        return None
    active = [r for r in rows if r["status"] == "active"]
    if len(active) > 1:
        print(f"[sessions] WARNING: {len(active)} active sessions for channel {channel_id} — closing older ones")
        for s in active:
            if s["id"] != latest["id"]:
                upsert(TABLE, SCHEMA, "id", s["id"], {"status": "closed"})
                _history.pop(s["id"], None)
    return latest


def get_active_root_for_project(project_name: str) -> dict | None:
    rows = find_all(TABLE, SCHEMA, "project_name", project_name)
    rows = [r for r in rows if not r.get("thread_id")]
    latest = _select_latest_active(rows)
    if not latest:
        return None
    active = [r for r in rows if r["status"] == "active"]
    if len(active) > 1:
        print(f"[sessions] WARNING: {len(active)} active root sessions for project {project_name} — closing older ones")
        for s in active:
            if s["id"] != latest["id"]:
                upsert(TABLE, SCHEMA, "id", s["id"], {"status": "closed"})
                _history.pop(s["id"], None)
    return latest


def list_active() -> list[dict]:
    return [r for r in find_all(TABLE, SCHEMA) if r["status"] == "active"]


def list_for_project(project_name: str, include_closed: bool = False) -> list[dict]:
    rows = find_all(TABLE, SCHEMA, "project_name", project_name)
    if include_closed:
        return rows
    return [r for r in rows if r["status"] == "active"]


def attach_channel(session_id: str, channel_id: str, thread_id: str = ""):
    upsert(TABLE, SCHEMA, "id", session_id, {
        "channel_id": channel_id,
        "thread_id": thread_id,
        "updated_at": now(),
    })


def close(session_id: str):
    upsert(TABLE, SCHEMA, "id", session_id, {"status": "closed"})
    _history.pop(session_id, None)
    _resume_ctx.pop(session_id, None)
    delete_where(TABLE_SUMMARIES, SUMMARY_SCHEMA, "session_id", session_id)
    delete_where(TABLE_RESUME, RESUME_SCHEMA, "session_id", session_id)


def get_history(session_id: str) -> list:
    if session_id not in _history:
        rows = find_all(TABLE_MESSAGES, MESSAGE_SCHEMA, "session_id", session_id)
        rows.sort(key=lambda r: (r.get("created_at", ""), r.get("id", "")))
        _history[session_id] = [{"role": r["role"], "content": r["content"]} for r in rows]
    return _history.get(session_id, [])


def append_history(session_id: str, role: str, content):
    history = get_history(session_id)
    record = get(session_id)
    if record:
        message_id = new_id()
        upsert(TABLE_MESSAGES, MESSAGE_SCHEMA, "id", message_id, {
            "id": message_id,
            "session_id": session_id,
            "project_name": record.get("project_name", ""),
            "channel_id": record.get("channel_id", ""),
            "role": role,
            "content": str(content),
            "created_at": now(),
        })
    _history[session_id].append({"role": role, "content": content})
    count = len(history)
    upsert(TABLE, SCHEMA, "id", session_id, {"message_count": str(count), "updated_at": now()})


def update_last_prompt(session_id: str, prompt: str):
    upsert(TABLE, SCHEMA, "id", session_id, {"last_prompt": prompt[:500], "updated_at": now()})


def get_last_prompt(session_id: str) -> str:
    row = find_one(TABLE, SCHEMA, "id", session_id)
    return row.get("last_prompt", "") if row else ""


def set_backend_session_id(session_id: str, backend_session_id: str):
    upsert(TABLE, SCHEMA, "id", session_id, {
        "backend_session_id": backend_session_id,
        "backend": "codex",
        "updated_at": now(),
    })


def get_backend_session_id(session_id: str) -> str:
    row = find_one(TABLE, SCHEMA, "id", session_id)
    return row.get("backend_session_id", "") if row else ""


def clear_backend_session_id(session_id: str):
    upsert(TABLE, SCHEMA, "id", session_id, {
        "backend_session_id": "",
        "backend": "codex",
        "updated_at": now(),
    })


# ── Resume context (in-memory + CSV for restart resilience) ───────────────────

def save_resume_context(session_id: str, ctx: str):
    _resume_ctx[session_id] = ctx
    upsert(TABLE_RESUME, RESUME_SCHEMA, "session_id", session_id, {
        "id": session_id, "session_id": session_id,
        "context": ctx[:3000], "created_at": now(),
    })


def pop_resume_context(session_id: str) -> str | None:
    ctx = _resume_ctx.pop(session_id, None)
    if not ctx:
        row = find_one(TABLE_RESUME, RESUME_SCHEMA, "session_id", session_id)
        ctx = row.get("context") if row else None
    if ctx:
        delete_where(TABLE_RESUME, RESUME_SCHEMA, "session_id", session_id)
    return ctx


# ── Task summaries (persistent) ──────────────────────────────────────────────

def save_task_summary(session_id: str, summary: str,
                      requested: str = "", completed: str = "", remaining: str = ""):
    upsert(TABLE_SUMMARIES, SUMMARY_SCHEMA, "session_id", session_id, {
        "id": session_id, "session_id": session_id,
        "summary": summary[:3000],
        "task_requested": requested[:500],
        "task_completed": completed[:1000],
        "task_remaining": remaining[:1000],
        "created_at": now(),
    })


def get_task_summary(session_id: str) -> dict | None:
    return find_one(TABLE_SUMMARIES, SUMMARY_SCHEMA, "session_id", session_id)


def list_messages(session_id: str = "", project_name: str = "", channel_id: str = "", limit: int = 50) -> list[dict]:
    rows = find_all(TABLE_MESSAGES, MESSAGE_SCHEMA)
    if session_id:
        rows = [r for r in rows if r["session_id"] == session_id]
    if project_name:
        rows = [r for r in rows if r["project_name"] == project_name]
    if channel_id:
        rows = [r for r in rows if r["channel_id"] == channel_id]
    rows.sort(key=lambda r: (r.get("created_at", ""), r.get("id", "")))
    if limit > 0:
        rows = rows[-limit:]
    return rows


def build_recovery_prompt(session_id: str, latest_prompt: str, limit: int = 12) -> str:
    transcript = get_history(session_id)[-limit:]
    if not transcript:
        return latest_prompt

    lines = [
        "The previous Codex backend thread failed or disconnected.",
        "Resume this same task in a fresh backend thread.",
        "Preserve prior context, avoid repeating finished work, and continue from the latest user instruction below.",
        "",
        "Recent session transcript:",
    ]
    for msg in transcript:
        role = (msg.get("role") or "unknown").upper()
        content = str(msg.get("content", "")).strip()
        if content:
            lines.append(f"{role}: {content[:2500]}")
    lines.extend(["", "Latest user instruction:", latest_prompt])
    return "\n".join(lines)
