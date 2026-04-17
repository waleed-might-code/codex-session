#!/usr/bin/env python3
"""
Project/session/history control surface for Codex.

Examples:
  pexo-context snapshot --json
  pexo-context projects list
  pexo-context projects use my-app --channel "$PEXO_CHANNEL_ID" --user "$PEXO_USER_ID"
  pexo-context sessions current --channel "$PEXO_CHANNEL_ID"
  pexo-context history show --project my-app --limit 20
"""
import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import storage.projects as proj_store
import storage.sessions as sess_store
from storage.base import find_all


def _channel(value: str = "") -> str:
    return value or os.getenv("PEXO_CHANNEL_ID", "")


def _user(value: str = "") -> str:
    return value or os.getenv("PEXO_USER_ID", "") or "codex"


def _session(value: str = "") -> str:
    return value or os.getenv("PEXO_SESSION_ID", "")


def _emit(data, as_json: bool = False):
    if as_json:
        print(json.dumps(data, indent=2))
        return
    if isinstance(data, str):
        print(data)
        return
    print(json.dumps(data, indent=2))


def _current_project(channel_id: str) -> dict | None:
    if not channel_id:
        return None
    return proj_store.get_by_channel(channel_id)


def _current_session(channel_id: str) -> dict | None:
    if not channel_id:
        return None
    sess = sess_store.get_active_for_channel(channel_id)
    if sess:
        return sess
    proj = _current_project(channel_id)
    if proj:
        return sess_store.get_active_root_for_project(proj["name"])
    return None


def cmd_snapshot(args):
    channel_id = _channel(args.channel)
    proj = _current_project(channel_id)
    sess = _current_session(channel_id)
    history = []
    if sess:
        history = sess_store.list_messages(session_id=sess["id"], limit=args.limit)
    data = {
        "channel_id": channel_id,
        "project_count": len(proj_store.list_all()),
        "current_project": proj,
        "current_session": sess,
        "recent_history": history,
    }
    _emit(data, args.json)


def cmd_projects_list(args):
    projects = proj_store.list_all()
    if args.json:
        return _emit(projects, True)
    lines = [f"{len(projects)} project(s):"]
    for proj in projects:
        root_sess = sess_store.get_active_root_for_project(proj["name"])
        extra = f" | session={root_sess['id']}" if root_sess else ""
        active = " active" if proj.get("active_channel_id") else ""
        lines.append(f"- {proj['name']} [{proj['path']}]{extra}{active}")
    _emit("\n".join(lines))


def cmd_projects_current(args):
    channel_id = _channel(args.channel)
    proj = _current_project(channel_id)
    data = {
        "channel_id": channel_id,
        "project": proj,
    }
    if args.json:
        return _emit(data, True)
    if not proj:
        return _emit("No active project for this channel.")
    _emit(f"{proj['name']} -> {proj['path']}")


def cmd_projects_use(args):
    channel_id = _channel(args.channel)
    user_id = _user(args.user)
    proj = proj_store.get(args.name)
    if not proj:
        raise SystemExit(f"Project not found: {args.name}")
    proj_store.set_active_channel(args.name, channel_id)
    sess = sess_store.get_active_root_for_project(args.name)
    if sess:
        sess_store.attach_channel(sess["id"], channel_id)
    else:
        sess = sess_store.create(args.name, channel_id, user_id)
    data = {
        "ok": True,
        "effective_next_turn": True,
        "channel_id": channel_id,
        "project": proj,
        "session": sess,
        "note": "Project switch takes effect for the next bot turn because the current Codex process keeps its existing working directory.",
    }
    _emit(data, args.json)


def cmd_sessions_list(args):
    if args.project:
        sessions = sess_store.list_for_project(args.project, include_closed=args.include_closed)
    else:
        sessions = sess_store.list_active() if not args.include_closed else find_all(sess_store.TABLE, sess_store.SCHEMA)
    _emit(sessions, args.json)


def cmd_sessions_current(args):
    channel_id = _channel(args.channel)
    sess = _current_session(channel_id)
    _emit(sess or {"channel_id": channel_id, "session": None}, args.json)


def cmd_sessions_close(args):
    session_id = args.id or _session()
    if not session_id:
        raise SystemExit("No session id provided.")
    sess = sess_store.get(session_id)
    if not sess:
        raise SystemExit(f"Session not found: {session_id}")
    sess_store.close(session_id)
    _emit({"ok": True, "closed_session_id": session_id}, args.json)


def cmd_history_show(args):
    session_id = args.session or _session()
    project_name = args.project
    channel_id = args.channel
    if not any((session_id, project_name, channel_id)):
        channel_id = _channel("")
    if not any((session_id, project_name, channel_id)):
        raise SystemExit("Specify --session, --project, or --channel.")
    rows = sess_store.list_messages(
        session_id=session_id,
        project_name=project_name,
        channel_id=channel_id,
        limit=args.limit,
    )
    if args.json:
        return _emit(rows, True)
    if not rows:
        return _emit("No stored transcript messages matched that scope.")
    lines = []
    for row in rows:
        lines.append(f"[{row['created_at']}] ({row['session_id']}) {row['role']}: {row['content']}")
    _emit("\n".join(lines))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="pexo-context")
    sub = p.add_subparsers(dest="cmd", required=True)

    snapshot = sub.add_parser("snapshot")
    snapshot.add_argument("--channel", default="")
    snapshot.add_argument("--limit", type=int, default=10)
    snapshot.add_argument("--json", action="store_true")
    snapshot.set_defaults(func=cmd_snapshot)

    projects = sub.add_parser("projects")
    projects_sub = projects.add_subparsers(dest="projects_cmd", required=True)

    projects_list = projects_sub.add_parser("list")
    projects_list.add_argument("--json", action="store_true")
    projects_list.set_defaults(func=cmd_projects_list)

    projects_current = projects_sub.add_parser("current")
    projects_current.add_argument("--channel", default="")
    projects_current.add_argument("--json", action="store_true")
    projects_current.set_defaults(func=cmd_projects_current)

    projects_use = projects_sub.add_parser("use")
    projects_use.add_argument("name")
    projects_use.add_argument("--channel", default="")
    projects_use.add_argument("--user", default="")
    projects_use.add_argument("--json", action="store_true")
    projects_use.set_defaults(func=cmd_projects_use)

    sessions = sub.add_parser("sessions")
    sessions_sub = sessions.add_subparsers(dest="sessions_cmd", required=True)

    sessions_list = sessions_sub.add_parser("list")
    sessions_list.add_argument("--project", default="")
    sessions_list.add_argument("--include-closed", action="store_true")
    sessions_list.add_argument("--json", action="store_true")
    sessions_list.set_defaults(func=cmd_sessions_list)

    sessions_current = sessions_sub.add_parser("current")
    sessions_current.add_argument("--channel", default="")
    sessions_current.add_argument("--json", action="store_true")
    sessions_current.set_defaults(func=cmd_sessions_current)

    sessions_close = sessions_sub.add_parser("close")
    sessions_close.add_argument("id", nargs="?", default="")
    sessions_close.add_argument("--json", action="store_true")
    sessions_close.set_defaults(func=cmd_sessions_close)

    history = sub.add_parser("history")
    history_sub = history.add_subparsers(dest="history_cmd", required=True)

    history_show = history_sub.add_parser("show")
    history_show.add_argument("--session", default="")
    history_show.add_argument("--project", default="")
    history_show.add_argument("--channel", default="")
    history_show.add_argument("--limit", type=int, default=20)
    history_show.add_argument("--json", action="store_true")
    history_show.set_defaults(func=cmd_history_show)

    return p


def main():
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
