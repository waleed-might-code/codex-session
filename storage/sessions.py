from storage.base import *

TABLE = "sessions"
SCHEMA = {
    "id": str, "project_name": str, "channel_id": str, "thread_id": str,
    "user_id": str, "created_at": str, "updated_at": str,
    "status": str,   # active | closed
    "model": str, "message_count": str, "last_prompt": str,
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

# In-memory message history: {session_id: [{"role": ..., "content": ...}]}
_history: dict[str, list] = {}

# Resume context saved when step limit is hit (also persisted to CSV)
_resume_ctx: dict[str, str] = {}


def create(project_name: str, channel_id: str, user_id: str, thread_id: str = "", model: str = "") -> dict:
    rec = {
        "id": new_id(), "project_name": project_name,
        "channel_id": channel_id, "thread_id": thread_id,
        "user_id": user_id, "created_at": now(), "updated_at": now(),
        "status": "active", "model": model or "claude-sonnet-4-6",
        "message_count": "0", "last_prompt": "",
    }
    upsert(TABLE, SCHEMA, "id", rec["id"], rec)
    _history[rec["id"]] = []
    return rec


def get(session_id: str) -> dict | None:
    return find_one(TABLE, SCHEMA, "id", session_id)


def get_active_for_channel(channel_id: str) -> dict | None:
    rows = find_all(TABLE, SCHEMA, "channel_id", channel_id)
    active = [r for r in rows if r["status"] == "active"]
    if not active:
        return None
    # If somehow multiple active sessions exist, close the older ones
    if len(active) > 1:
        print(f"[sessions] WARNING: {len(active)} active sessions for channel {channel_id} — closing older ones")
        for s in active[:-1]:
            upsert(TABLE, SCHEMA, "id", s["id"], {"status": "closed"})
            _history.pop(s["id"], None)
    return active[-1]


def list_active() -> list[dict]:
    return [r for r in find_all(TABLE, SCHEMA) if r["status"] == "active"]


def close(session_id: str):
    upsert(TABLE, SCHEMA, "id", session_id, {"status": "closed"})
    _history.pop(session_id, None)
    _resume_ctx.pop(session_id, None)
    delete_where(TABLE_SUMMARIES, SUMMARY_SCHEMA, "session_id", session_id)
    delete_where(TABLE_RESUME, RESUME_SCHEMA, "session_id", session_id)


def get_history(session_id: str) -> list:
    return _history.get(session_id, [])


def append_history(session_id: str, role: str, content):
    if session_id not in _history:
        _history[session_id] = []
    _history[session_id].append({"role": role, "content": content})
    count = len(_history[session_id])
    upsert(TABLE, SCHEMA, "id", session_id, {"message_count": str(count), "updated_at": now()})


def update_last_prompt(session_id: str, prompt: str):
    upsert(TABLE, SCHEMA, "id", session_id, {"last_prompt": prompt[:500], "updated_at": now()})


def get_last_prompt(session_id: str) -> str:
    row = find_one(TABLE, SCHEMA, "id", session_id)
    return row.get("last_prompt", "") if row else ""


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
