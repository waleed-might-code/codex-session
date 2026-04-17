from datetime import datetime, timedelta, timezone

from storage.base import *

TABLE = "discord_jobs"
SCHEMA = {
    "id": str, "channel_id": str, "thread_id": str, "creator_user_id": str,
    "content": str, "run_at": str, "status": str, "message_id": str,
    "created_at": str, "updated_at": str,
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_utc(value: str) -> datetime:
    cleaned = (value or "").strip().replace("Z", "+00:00")
    if not cleaned:
        return _utc_now()
    dt = datetime.fromisoformat(cleaned)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _fmt_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def schedule(channel_id: str, content: str, run_at: datetime,
             thread_id: str = "", creator_user_id: str = "") -> dict:
    rec = {
        "id": new_id(),
        "channel_id": channel_id,
        "thread_id": thread_id,
        "creator_user_id": creator_user_id,
        "content": content,
        "run_at": _fmt_utc(run_at),
        "status": "pending",
        "message_id": "",
        "created_at": now(),
        "updated_at": now(),
    }
    upsert(TABLE, SCHEMA, "id", rec["id"], rec)
    return rec


def schedule_after_seconds(channel_id: str, content: str, delay_seconds: int,
                           thread_id: str = "", creator_user_id: str = "") -> dict:
    return schedule(
        channel_id=channel_id,
        content=content,
        run_at=_utc_now() + timedelta(seconds=max(0, int(delay_seconds))),
        thread_id=thread_id,
        creator_user_id=creator_user_id,
    )


def get(job_id: str) -> dict | None:
    return find_one(TABLE, SCHEMA, "id", job_id)


def list_jobs(channel_id: str = "", status: str = "", limit: int = 50) -> list[dict]:
    rows = find_all(TABLE, SCHEMA)
    if channel_id:
        rows = [r for r in rows if r["channel_id"] == channel_id or r["thread_id"] == channel_id]
    if status:
        rows = [r for r in rows if r["status"] == status]
    rows.sort(key=lambda r: (r.get("run_at", ""), r.get("created_at", ""), r.get("id", "")))
    if limit > 0:
        rows = rows[:limit]
    return rows


def list_due(limit: int = 20) -> list[dict]:
    now_utc = _utc_now()
    rows = [r for r in find_all(TABLE, SCHEMA) if r["status"] == "pending"]
    due = [r for r in rows if _parse_utc(r.get("run_at", "")) <= now_utc]
    due.sort(key=lambda r: (r.get("run_at", ""), r.get("created_at", ""), r.get("id", "")))
    return due[:limit]


def mark_sent(job_id: str, message_id: str = ""):
    upsert(TABLE, SCHEMA, "id", job_id, {
        "status": "sent",
        "message_id": message_id,
        "updated_at": now(),
    })


def mark_failed(job_id: str):
    upsert(TABLE, SCHEMA, "id", job_id, {
        "status": "failed",
        "updated_at": now(),
    })


def cancel(job_id: str):
    upsert(TABLE, SCHEMA, "id", job_id, {
        "status": "cancelled",
        "updated_at": now(),
    })
