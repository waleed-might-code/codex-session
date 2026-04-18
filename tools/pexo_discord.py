#!/usr/bin/env python3
"""
Discord control surface for Codex.

By default this tool proxies Discord operations through the running bot process
via a local storage queue, so Codex can manage Discord even when its own
subprocess network access is restricted.

Examples:
  pexo-discord send --content "hello"
  pexo-discord schedule --delay-seconds 3600 --content "check back in an hour"
  pexo-discord jobs
  pexo-discord cancel <job_id>
  pexo-discord thread create --name "Release thread" --message "Work starts here"
  pexo-discord thread list --channel "$PEXO_CHANNEL_ID"
  pexo-discord session move-to-thread --name "Backend fixes"
  pexo-discord session find-thread --text "deploy fix"
  pexo-discord session find-and-tag --text "deploy fix" --message "Continue here:"
"""
import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from dotenv import load_dotenv

load_dotenv(os.path.join(ROOT, ".env"))

import storage.discord_jobs as jobs_store
import storage.discord_ops as ops_store
import storage.projects as proj_store
import storage.sessions as sess_store
import utils.discord_helpers as dh


def _init_discord():
    token = os.getenv("DISCORD_BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit("DISCORD_BOT_TOKEN is not configured.")
    dh.init(token)


def _channel(value: str = "") -> str:
    return value or os.getenv("PEXO_CHANNEL_ID", "")


def _user(value: str = "") -> str:
    return value or os.getenv("PEXO_USER_ID", "") or "codex"


def _emit(data, as_json: bool = False):
    if as_json:
        print(json.dumps(data, indent=2))
        return
    if isinstance(data, str):
        print(data)
        return
    print(json.dumps(data, indent=2))


async def _channel_scope(channel_id: str) -> tuple[str, dict]:
    info = await dh.get_channel(channel_id)
    if info.get("type") in (10, 11, 12):
        return info.get("parent_id", channel_id) or channel_id, info
    return channel_id, info


def _current_project_for_channels(*channel_ids: str) -> dict | None:
    for channel_id in channel_ids:
        if not channel_id:
            continue
        proj = proj_store.get_by_channel(channel_id)
        if proj:
            return proj
    for channel_id in channel_ids:
        if not channel_id:
            continue
        sess = sess_store.get_active_for_channel(channel_id)
        if sess and sess.get("project_name"):
            proj = proj_store.get(sess["project_name"])
            if proj:
                return proj
    return None


def _current_session_for_channels(*channel_ids: str) -> dict | None:
    for channel_id in channel_ids:
        if not channel_id:
            continue
        sess = sess_store.get_active_for_channel(channel_id)
        if sess:
            return sess
    return None


async def _channel_info(args) -> dict:
    _init_discord()
    channel_id = _channel(args.channel)
    if not channel_id:
        raise SystemExit("No channel id provided.")
    return await dh.get_channel(channel_id)


async def _send(args) -> dict:
    _init_discord()
    channel_id = _channel(args.channel)
    if not channel_id:
        raise SystemExit("No channel id provided.")
    result = await dh.send_message(channel_id, args.content)
    return {"ok": True, "channel_id": channel_id, "message_id": result.get("id", "")}


def _parse_at(raw: str) -> datetime:
    cleaned = raw.strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(cleaned)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _schedule(args) -> dict:
    channel_id = _channel(args.channel)
    if not channel_id:
        raise SystemExit("No channel id provided.")
    if args.at:
        run_at = _parse_at(args.at)
        return jobs_store.schedule(channel_id, args.content, run_at)
    delay = args.delay_seconds + (args.delay_minutes * 60)
    return jobs_store.schedule_after_seconds(channel_id, args.content, delay)


def _jobs(args) -> list[dict]:
    channel_id = _channel(args.channel)
    return jobs_store.list_jobs(channel_id=channel_id if args.current_channel else "", status=args.status, limit=args.limit)


def _cancel(args) -> dict:
    jobs_store.cancel(args.id)
    return {"ok": True, "cancelled_job_id": args.id}


async def _thread_create(args) -> dict:
    _init_discord()
    channel_id = _channel(args.channel)
    if not channel_id:
        raise SystemExit("No channel id provided.")
    return await dh.create_thread_standalone(channel_id, args.name, initial_message=args.message)


async def _thread_info(args) -> dict:
    _init_discord()
    thread_id = args.thread or _channel(args.channel)
    if not thread_id:
        raise SystemExit("No thread id provided.")
    return await dh.get_channel(thread_id)


async def _thread_list(args) -> dict:
    _init_discord()
    channel_id = _channel(args.channel)
    if not channel_id:
        raise SystemExit("No channel id provided.")
    channel_info = await dh.get_channel(channel_id)
    parent_channel_id = channel_info.get("parent_id") if channel_info.get("type") in (10, 11, 12) else channel_id
    if not parent_channel_id:
        parent_channel_id = channel_id
    payload = await dh.list_active_threads(parent_channel_id)
    return {
        "channel_id": channel_id,
        "parent_channel_id": parent_channel_id,
        "threads": payload.get("threads", []),
        "current_channel": channel_info,
    }


async def _thread_mention(args) -> dict:
    _init_discord()
    thread_id = args.thread
    if not thread_id:
        raise SystemExit("No thread id provided.")
    target_channel = _channel(args.channel)
    if not target_channel:
        raise SystemExit("No target channel id provided.")
    prefix = (args.message or "").strip()
    content = f"{prefix} <#{thread_id}>".strip()
    result = await dh.send_message(target_channel, content)
    return {
        "ok": True,
        "channel_id": target_channel,
        "thread_id": thread_id,
        "message_id": result.get("id", ""),
    }


async def _session_move_to_thread(args) -> dict:
    _init_discord()
    channel_id = _channel(args.channel)
    if not channel_id:
        raise SystemExit("No channel id provided.")

    parent_channel_id, current_info = await _channel_scope(channel_id)
    user_id = _user(getattr(args, "user", ""))
    existing_session = _current_session_for_channels(channel_id, parent_channel_id)
    project = _current_project_for_channels(channel_id, parent_channel_id)

    if current_info.get("type") in (10, 11, 12) and not args.force_new:
        if existing_session and not existing_session.get("thread_id"):
            sess_store.attach_channel(existing_session["id"], channel_id, thread_id=channel_id)
            existing_session = sess_store.get(existing_session["id"])
        return {
            "ok": True,
            "already_thread": True,
            "thread_id": channel_id,
            "parent_channel_id": parent_channel_id,
            "session": existing_session,
            "project": project,
            "mention": f"<#{channel_id}>",
        }

    thread_name = (args.name or "").strip()
    if not thread_name:
        if project:
            thread_name = f"{project['name']} session"
        elif existing_session and existing_session.get("project_name"):
            thread_name = f"{existing_session['project_name']} session"
        else:
            thread_name = "codex session"

    initial_message = (args.message or "").strip()
    if not initial_message:
        initial_message = f"Continuing this Codex session from <#{parent_channel_id}>."

    created = await dh.create_thread_standalone(parent_channel_id, thread_name, initial_message=initial_message)
    thread_id = created.get("thread_id", "")
    if not thread_id:
        raise SystemExit("Failed to create thread.")

    session = None
    if existing_session and not args.new_session:
        sess_store.attach_channel(existing_session["id"], thread_id, thread_id=thread_id)
        session = sess_store.get(existing_session["id"])
    else:
        project_name = args.project or (project["name"] if project else "") or (existing_session.get("project_name", "") if existing_session else "")
        if project_name:
            session = sess_store.create(project_name, thread_id, user_id, thread_id=thread_id)

    announcement_message_id = ""
    if not args.no_announce:
        announcement = (args.announce_message or "").strip() or f"Continue here: <#{thread_id}>"
        sent = await dh.send_message(parent_channel_id, announcement)
        announcement_message_id = sent.get("id", "")

    return {
        "ok": True,
        "thread_id": thread_id,
        "thread_name": created.get("name", thread_name),
        "parent_channel_id": parent_channel_id,
        "session": session,
        "project": project,
        "mention": f"<#{thread_id}>",
        "announcement_message_id": announcement_message_id,
        "moved_existing_session": bool(existing_session and not args.new_session),
    }


async def _session_find_thread(args) -> list[dict]:
    _init_discord()
    matches = sess_store.search_messages(
        text=args.text,
        project_name=args.project,
        channel_id=args.channel_scope,
        limit=max(args.limit * 3, args.limit),
    )
    grouped = []
    seen = set()
    for row in reversed(matches):
        thread_id = row.get("thread_id") or row.get("channel_id", "")
        if not thread_id or thread_id in seen:
            continue
        seen.add(thread_id)
        grouped.append(row)
        if len(grouped) >= args.limit:
            break

    enriched = []
    for row in grouped:
        thread_id = row.get("thread_id") or row.get("channel_id", "")
        channel_info = await dh.get_channel(thread_id) if thread_id else {}
        enriched.append({
            "thread_id": thread_id,
            "thread_name": channel_info.get("name", ""),
            "parent_channel_id": channel_info.get("parent_id", ""),
            "session_id": row.get("session_id", ""),
            "project_name": row.get("project_name", ""),
            "created_at": row.get("created_at", ""),
            "excerpt": row.get("excerpt", row.get("content", "")),
        })
    return enriched


async def _session_find_and_tag(args) -> dict:
    _init_discord()
    rows = sess_store.search_messages(
        text=args.text,
        project_name=args.project,
        channel_id=args.channel_scope,
        limit=max(args.limit * 3, args.limit),
    )
    chosen = None
    for row in reversed(rows):
        thread_id = row.get("thread_id") or row.get("channel_id", "")
        if thread_id:
            chosen = row
            break
    if not chosen:
        raise SystemExit("No matching thread-backed session found.")

    target_channel = _channel(args.channel)
    if not target_channel:
        raise SystemExit("No target channel id provided.")
    thread_id = chosen.get("thread_id") or chosen.get("channel_id", "")
    prefix = (args.message or "").strip() or "Continue here:"
    result = await dh.send_message(target_channel, f"{prefix} <#{thread_id}>")
    return {
        "ok": True,
        "channel_id": target_channel,
        "thread_id": thread_id,
        "session_id": chosen.get("session_id", ""),
        "message_id": result.get("id", ""),
    }


async def execute_request(request: dict):
    args = SimpleNamespace(**request)
    cmd = request.get("cmd", "")

    if cmd == "channel" and request.get("channel_cmd") == "info":
        return await _channel_info(args)
    if cmd == "send":
        return await _send(args)
    if cmd == "schedule":
        return _schedule(args)
    if cmd == "jobs":
        return _jobs(args)
    if cmd == "cancel":
        return _cancel(args)
    if cmd == "thread":
        if request.get("thread_cmd") == "create":
            return await _thread_create(args)
        if request.get("thread_cmd") == "info":
            return await _thread_info(args)
        if request.get("thread_cmd") == "list":
            return await _thread_list(args)
        if request.get("thread_cmd") == "mention":
            return await _thread_mention(args)
    if cmd == "session":
        if request.get("session_cmd") == "move-to-thread":
            return await _session_move_to_thread(args)
        if request.get("session_cmd") == "find-thread":
            return await _session_find_thread(args)
        if request.get("session_cmd") == "find-and-tag":
            return await _session_find_and_tag(args)
    raise SystemExit(f"Unsupported discord request: {request}")


def _request_from_args(args) -> dict:
    request = {k: v for k, v in vars(args).items() if k != "json"}
    return request


def _queue_request(request: dict):
    timeout = int(os.getenv("PEXO_DISCORD_OP_TIMEOUT_SECONDS", "45"))
    op = ops_store.enqueue(request, creator_user_id=_user(request.get("user", "")))
    deadline = time.time() + timeout
    while time.time() < deadline:
        row = ops_store.get(op["id"])
        if not row:
            break
        status = row.get("status", "")
        if status == "done":
            raw = row.get("result_json", "")
            return json.loads(raw) if raw else {}
        if status == "failed":
            raise SystemExit(row.get("error") or "Discord operation failed.")
        time.sleep(0.25)
    raise SystemExit(
        "Timed out waiting for the bot to complete the Discord operation. "
        "Make sure the bot is running and connected."
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pexo-discord")
    sub = parser.add_subparsers(dest="cmd", required=True)

    channel = sub.add_parser("channel")
    channel_sub = channel.add_subparsers(dest="channel_cmd", required=True)
    channel_info = channel_sub.add_parser("info")
    channel_info.add_argument("--channel", default="")
    channel_info.add_argument("--json", action="store_true")

    send = sub.add_parser("send")
    send.add_argument("--channel", default="")
    send.add_argument("--content", required=True)
    send.add_argument("--json", action="store_true")

    schedule = sub.add_parser("schedule")
    schedule.add_argument("--channel", default="")
    schedule.add_argument("--content", required=True)
    schedule.add_argument("--delay-seconds", type=int, default=0)
    schedule.add_argument("--delay-minutes", type=int, default=0)
    schedule.add_argument("--at", default="")
    schedule.add_argument("--json", action="store_true")

    jobs = sub.add_parser("jobs")
    jobs.add_argument("--channel", default="")
    jobs.add_argument("--current-channel", action="store_true")
    jobs.add_argument("--status", default="")
    jobs.add_argument("--limit", type=int, default=20)
    jobs.add_argument("--json", action="store_true")

    cancel = sub.add_parser("cancel")
    cancel.add_argument("id")
    cancel.add_argument("--json", action="store_true")

    thread = sub.add_parser("thread")
    thread_sub = thread.add_subparsers(dest="thread_cmd", required=True)
    thread_create = thread_sub.add_parser("create")
    thread_create.add_argument("--channel", default="")
    thread_create.add_argument("--name", required=True)
    thread_create.add_argument("--message", default="")
    thread_create.add_argument("--json", action="store_true")

    thread_info = thread_sub.add_parser("info")
    thread_info.add_argument("--channel", default="")
    thread_info.add_argument("--thread", default="")
    thread_info.add_argument("--json", action="store_true")

    thread_list = thread_sub.add_parser("list")
    thread_list.add_argument("--channel", default="")
    thread_list.add_argument("--json", action="store_true")

    thread_mention = thread_sub.add_parser("mention")
    thread_mention.add_argument("--channel", default="")
    thread_mention.add_argument("--thread", required=True)
    thread_mention.add_argument("--message", default="")
    thread_mention.add_argument("--json", action="store_true")

    session = sub.add_parser("session")
    session_sub = session.add_subparsers(dest="session_cmd", required=True)

    session_move = session_sub.add_parser("move-to-thread")
    session_move.add_argument("--channel", default="")
    session_move.add_argument("--project", default="")
    session_move.add_argument("--user", default="")
    session_move.add_argument("--name", default="")
    session_move.add_argument("--message", default="")
    session_move.add_argument("--announce-message", default="")
    session_move.add_argument("--new-session", action="store_true")
    session_move.add_argument("--force-new", action="store_true")
    session_move.add_argument("--no-announce", action="store_true")
    session_move.add_argument("--json", action="store_true")

    session_find = session_sub.add_parser("find-thread")
    session_find.add_argument("--text", required=True)
    session_find.add_argument("--project", default="")
    session_find.add_argument("--channel-scope", default="")
    session_find.add_argument("--limit", type=int, default=5)
    session_find.add_argument("--json", action="store_true")

    session_find_and_tag = session_sub.add_parser("find-and-tag")
    session_find_and_tag.add_argument("--channel", default="")
    session_find_and_tag.add_argument("--text", required=True)
    session_find_and_tag.add_argument("--project", default="")
    session_find_and_tag.add_argument("--channel-scope", default="")
    session_find_and_tag.add_argument("--message", default="")
    session_find_and_tag.add_argument("--limit", type=int, default=5)
    session_find_and_tag.add_argument("--json", action="store_true")

    return parser


def main():
    args = build_parser().parse_args()
    request = _request_from_args(args)
    direct = os.getenv("PEXO_DISCORD_DIRECT", "").lower() in ("1", "true", "yes")
    if direct:
        result = asyncio.run(execute_request(request))
    else:
        result = _queue_request(request)
    _emit(result, getattr(args, "json", False))


if __name__ == "__main__":
    main()
