import json

from storage.base import *

TABLE = "discord_ops"
SCHEMA = {
    "id": str,
    "request_json": str,
    "status": str,
    "result_json": str,
    "error": str,
    "creator_user_id": str,
    "created_at": str,
    "updated_at": str,
}


def enqueue(request: dict, creator_user_id: str = "") -> dict:
    rec = {
        "id": new_id(),
        "request_json": json.dumps(request),
        "status": "pending",
        "result_json": "",
        "error": "",
        "creator_user_id": creator_user_id,
        "created_at": now(),
        "updated_at": now(),
    }
    upsert(TABLE, SCHEMA, "id", rec["id"], rec)
    return rec


def get(op_id: str) -> dict | None:
    return find_one(TABLE, SCHEMA, "id", op_id)


def list_pending(limit: int = 20) -> list[dict]:
    rows = [r for r in find_all(TABLE, SCHEMA) if r["status"] == "pending"]
    rows.sort(key=lambda r: (r.get("created_at", ""), r.get("id", "")))
    return rows[:limit]


def mark_processing(op_id: str):
    upsert(TABLE, SCHEMA, "id", op_id, {
        "status": "processing",
        "updated_at": now(),
    })


def mark_done(op_id: str, result: dict | list | str):
    upsert(TABLE, SCHEMA, "id", op_id, {
        "status": "done",
        "result_json": json.dumps(result),
        "error": "",
        "updated_at": now(),
    })


def mark_failed(op_id: str, error: str):
    upsert(TABLE, SCHEMA, "id", op_id, {
        "status": "failed",
        "error": error[:2000],
        "updated_at": now(),
    })
