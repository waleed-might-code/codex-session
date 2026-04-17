#!/usr/bin/env python3
"""
Discord control surface for Codex.

Examples:
  pexo-discord send --content "hello"
  pexo-discord schedule --delay-seconds 3600 --content "check back in an hour"
  pexo-discord jobs
  pexo-discord cancel <job_id>
  pexo-discord thread create --name "Release thread" --message "Work starts here"
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from dotenv import load_dotenv

load_dotenv(os.path.join(ROOT, ".env"))

import storage.discord_jobs as jobs_store
import utils.discord_helpers as dh


def _init_discord():
    token = os.getenv("DISCORD_BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit("DISCORD_BOT_TOKEN is not configured.")
    dh.init(token)


def _channel(value: str = "") -> str:
    return value or os.getenv("PEXO_CHANNEL_ID", "")


def _emit(data, as_json: bool = False):
    if as_json:
        print(json.dumps(data, indent=2))
        return
    if isinstance(data, str):
        print(data)
        return
    print(json.dumps(data, indent=2))


async def _send(args):
    _init_discord()
    channel_id = _channel(args.channel)
    if not channel_id:
        raise SystemExit("No channel id provided.")
    result = await dh.send_message(channel_id, args.content)
    _emit({"ok": True, "channel_id": channel_id, "message_id": result.get("id", "")}, args.json)


def _parse_at(raw: str) -> datetime:
    cleaned = raw.strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(cleaned)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _schedule(args):
    channel_id = _channel(args.channel)
    if not channel_id:
        raise SystemExit("No channel id provided.")
    if args.at:
        run_at = _parse_at(args.at)
        job = jobs_store.schedule(channel_id, args.content, run_at)
    else:
        delay = args.delay_seconds + (args.delay_minutes * 60)
        job = jobs_store.schedule_after_seconds(channel_id, args.content, delay)
    _emit(job, args.json)


def _jobs(args):
    channel_id = _channel(args.channel)
    rows = jobs_store.list_jobs(channel_id=channel_id if args.current_channel else "", status=args.status, limit=args.limit)
    _emit(rows, args.json)


def _cancel(args):
    jobs_store.cancel(args.id)
    _emit({"ok": True, "cancelled_job_id": args.id}, args.json)


async def _thread_create(args):
    _init_discord()
    channel_id = _channel(args.channel)
    if not channel_id:
        raise SystemExit("No channel id provided.")
    result = await dh.create_thread_standalone(channel_id, args.name, initial_message=args.message)
    _emit(result, args.json)


def main():
    parser = argparse.ArgumentParser(prog="pexo-discord")
    sub = parser.add_subparsers(dest="cmd", required=True)

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

    args = parser.parse_args()

    if args.cmd == "send":
        import asyncio
        asyncio.run(_send(args))
        return
    if args.cmd == "schedule":
        _schedule(args)
        return
    if args.cmd == "jobs":
        _jobs(args)
        return
    if args.cmd == "cancel":
        _cancel(args)
        return
    if args.cmd == "thread":
        import asyncio
        asyncio.run(_thread_create(args))
        return


if __name__ == "__main__":
    main()
