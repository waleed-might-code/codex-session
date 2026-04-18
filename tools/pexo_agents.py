#!/usr/bin/env python3
"""
Project agent control surface for Codex.

Examples:
  pexo-agents spawn --name frontend --task "Build the landing page"
  pexo-agents spawn --name backend --role api --task "Wire the auth API"
  pexo-agents list
  pexo-agents status abc12345
  pexo-agents message abc12345 --prompt "Finish the login form states"
  pexo-agents wait abc12345 --timeout-seconds 600
  pexo-agents history abc12345 --limit 12
  pexo-agents stop abc12345
  pexo-agents close abc12345
"""
import argparse
import asyncio
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from storage.base import new_id
import storage.agents as agent_store
import storage.agent_ops as agent_ops_store
import storage.projects as proj_store
import storage.sessions as sess_store
import layers.codex_exec as codex_exec


MAX_AGENTS_PER_PROJECT = 10
AGENT_OP_TIMEOUT_SECONDS = 90


def _emit(data, as_json: bool = False):
    if as_json:
        print(json.dumps(data, indent=2))
        return
    if isinstance(data, str):
        print(data)
        return
    print(json.dumps(data, indent=2))


def _python_bin() -> str:
    return os.getenv("PEXO_PYTHON", "").strip() or sys.executable


def _tool_path(env_name: str, default_name: str) -> str:
    return os.getenv(env_name, "").strip() or os.path.join(ROOT, "tools", default_name)


def _channel(value: str = "") -> str:
    return value or os.getenv("PEXO_CHANNEL_ID", "")


def _user(value: str = "") -> str:
    return value or os.getenv("PEXO_USER_ID", "") or "codex"


def _parent_session(value: str = "") -> str:
    return value or os.getenv("PEXO_SESSION_ID", "")


def _current_project_name(explicit: str = "") -> str:
    if explicit:
        return explicit

    session_id = _parent_session("")
    if session_id:
        sess = sess_store.get(session_id)
        if sess and sess.get("project_name"):
            return sess["project_name"]

    channel_id = _channel("")
    if channel_id:
        proj = proj_store.get_by_channel(channel_id)
        if proj and proj.get("name"):
            return proj["name"]

    raise SystemExit("No project provided. Use --project or run this from an active project session.")


def _project(project_name: str) -> dict:
    proj = proj_store.get(project_name)
    if not proj:
        raise SystemExit(f"Project not found: {project_name}")
    path = proj.get("path", "")
    if not os.path.isdir(path):
        raise SystemExit(f"Project path does not exist: {path}")
    return proj


def _run_json_tool(script: str, args: list[str]) -> dict | list:
    cmd = [_python_bin(), script, *args]
    if "--json" not in args:
        cmd.append("--json")
    proc = subprocess.run(
        cmd,
        cwd=ROOT,
        env=os.environ.copy(),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        message = (proc.stderr or proc.stdout or "tool command failed").strip()
        raise SystemExit(message)
    payload = (proc.stdout or "").strip()
    if not payload:
        return {}
    return json.loads(payload)


def _discord_json(args: list[str]) -> dict | list:
    return _run_json_tool(_tool_path("PEXO_DISCORD", "pexo_discord.py"), args)


def _queue_agent_request(request: dict) -> dict:
    op = agent_ops_store.enqueue(request, creator_user_id=_user(""))
    deadline = time.time() + AGENT_OP_TIMEOUT_SECONDS
    while time.time() < deadline:
        row = agent_ops_store.get(op["id"])
        if not row:
            break
        status = row.get("status", "")
        if status == "done":
            raw = row.get("result_json", "")
            return json.loads(raw) if raw else {}
        if status == "failed":
            raise SystemExit(row.get("error") or "Agent operation failed.")
        time.sleep(0.25)
    raise SystemExit(
        "Timed out waiting for the bot to complete the agent operation. "
        "Make sure the bot is running and connected."
    )


def _split_chunks(text: str, limit: int = 1700) -> list[str]:
    raw = (text or "").strip()
    if not raw:
        return []
    chunks = []
    current = []
    current_len = 0
    for line in raw.splitlines():
        part = line if line else " "
        extra = len(part) + (1 if current else 0)
        if current and current_len + extra > limit:
            chunks.append("\n".join(current))
            current = [part]
            current_len = len(part)
        else:
            current.append(part)
            current_len += extra
    if current:
        chunks.append("\n".join(current))
    return chunks


def _discord_send_chunks(channel_id: str, text: str):
    if not channel_id:
        return
    for chunk in _split_chunks(text):
        _discord_json(["send", "--channel", channel_id, "--content", chunk])


def _resolve_thread_context(control_channel_id: str) -> tuple[str, str]:
    if not control_channel_id:
        return "", ""
    info = _discord_json(["channel", "info", "--channel", control_channel_id])
    if info.get("type") in (10, 11, 12):
        return info.get("parent_id", control_channel_id) or control_channel_id, control_channel_id
    return control_channel_id, control_channel_id


def _create_visible_thread(control_channel_id: str, project_name: str, agent_name: str, task: str = "") -> tuple[str, str, str]:
    if not control_channel_id:
        return "", "", ""
    parent_channel_id, announce_channel_id = _resolve_thread_context(control_channel_id)
    thread_name = f"{project_name} · {agent_name}"
    initial_message = (
        f"🤖 Agent **{agent_name}** created for project `{project_name}`.\n"
        "This thread shows the manager-to-agent task handoff and the agent's visible progress."
    )
    created = _discord_json([
        "thread", "create",
        "--channel", parent_channel_id,
        "--name", thread_name,
        "--message", initial_message,
    ])
    thread_id = created.get("thread_id", "")
    created_name = created.get("name", thread_name)
    if thread_id and task:
        _discord_send_chunks(thread_id, f"🧠 **Manager task for `{agent_name}`**\n{task}")
    return parent_channel_id, announce_channel_id, thread_id or ""


def _agent_payload(agent: dict, include_history: bool = False, history_limit: int = 8) -> dict:
    session = sess_store.get(agent.get("session_id", "")) if agent.get("session_id") else None
    summary = sess_store.get_task_summary(agent.get("session_id", "")) if agent.get("session_id") else None
    payload = {
        "agent": agent,
        "session": session,
        "summary": summary,
        "thread_mention": f"<#{agent['thread_id']}>" if agent.get("thread_id") else "",
    }
    if include_history and agent.get("session_id"):
        payload["recent_messages"] = sess_store.list_messages(session_id=agent["session_id"], limit=history_limit)
    return payload


def _running(agent: dict) -> bool:
    return agent.get("status") == "running" and bool(agent.get("pid"))


def _launch_worker_direct(agent_id: str) -> dict:
    agent = agent_store.get(agent_id)
    if not agent:
        raise SystemExit(f"Agent not found: {agent_id}")

    log_dir = Path(ROOT) / "data" / "agent_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{agent_id}.log"

    if not agent.get("current_task", "").strip():
        raise SystemExit(f"Agent `{agent_id}` has no queued task to run.")
    env = os.environ.copy()
    env["PEXO_AGENT_ID"] = agent_id
    env["PEXO_SESSION_ID"] = agent.get("session_id", "")
    if agent.get("thread_id"):
        env["PEXO_CHANNEL_ID"] = agent["thread_id"]
    elif agent.get("control_channel_id"):
        env["PEXO_CHANNEL_ID"] = agent["control_channel_id"]
    log_handle = open(log_path, "a", encoding="utf-8")
    proc = subprocess.Popen(
        [_python_bin(), os.path.abspath(__file__), "_worker", "--agent", agent_id],
        cwd=ROOT,
        env=env,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    log_handle.close()
    agent_store.update(agent_id, {
        "pid": str(proc.pid),
        "log_path": str(log_path),
    })
    return {
        "pid": proc.pid,
        "log_path": str(log_path),
    }


def _launch_worker(agent_id: str, prompt: str) -> dict:
    agent = agent_store.get(agent_id)
    if not agent:
        raise SystemExit(f"Agent not found: {agent_id}")
    agent_store.mark_running(agent_id, prompt)
    try:
        if os.getenv("PEXO_AGENTS_DIRECT", "").lower() in ("1", "true", "yes"):
            return _launch_worker_direct(agent_id)
        return _queue_agent_request({"cmd": "launch", "agent_id": agent_id})
    except Exception as exc:
        agent_store.mark_failed(agent_id, str(exc))
        raise


def _build_agent_prompt(agent: dict, prompt: str) -> str:
    lines = [
        "You are a delegated Codex worker inside a multi-agent project.",
        f"Agent name: {agent.get('name', 'worker')}",
        f"Role: {agent.get('role', '') or 'general'}",
        f"Project: {agent.get('project_name', '')}",
        "Stay focused on your assigned task. Make concrete progress in the current project.",
        "At the end, report exactly what you completed, any blockers, and the next best follow-up.",
    ]
    parent_session = agent.get("parent_session_id", "")
    if parent_session:
        lines.append(f"Coordinator session: {parent_session}")
    lines.extend(["", "Assigned task:", prompt])
    return "\n".join(lines)


def _mark_finished(agent_id: str, result: str):
    agent_store.mark_idle(agent_id, result=result)
    agent = agent_store.get(agent_id) or {}
    thread_id = agent.get("thread_id", "")
    control_channel_id = agent.get("control_channel_id", "")
    name = agent.get("name", agent_id)
    if thread_id:
        _discord_send_chunks(thread_id, f"✅ **Agent `{name}` finished**\n\n{result}")
    if control_channel_id:
        target = control_channel_id
        if thread_id:
            _discord_send_chunks(target, f"✅ Agent **{name}** finished in <#{thread_id}>.")
        else:
            _discord_send_chunks(target, f"✅ Agent **{name}** finished.")


def _mark_failed(agent_id: str, error: str):
    agent_store.mark_failed(agent_id, error)
    agent = agent_store.get(agent_id) or {}
    thread_id = agent.get("thread_id", "")
    control_channel_id = agent.get("control_channel_id", "")
    name = agent.get("name", agent_id)
    if thread_id:
        _discord_send_chunks(thread_id, f"❌ **Agent `{name}` failed**\n{error}")
    if control_channel_id:
        if thread_id:
            _discord_send_chunks(control_channel_id, f"❌ Agent **{name}** failed in <#{thread_id}>.\n{error[:400]}")
        else:
            _discord_send_chunks(control_channel_id, f"❌ Agent **{name}** failed.\n{error[:400]}")


def cmd_spawn(args):
    project_name = _current_project_name(args.project)
    _project(project_name)
    if agent_store.active_count_for_project(project_name) >= MAX_AGENTS_PER_PROJECT:
        raise SystemExit(f"Project `{project_name}` already has {MAX_AGENTS_PER_PROJECT} open agents. Close one first.")

    name = (args.name or f"agent-{new_id()}").strip()
    role = (args.role or name).strip()
    user_id = _user(args.user)
    parent_session_id = _parent_session(args.parent_session)
    control_channel_id = _channel(args.channel)

    existing_names = {
        row.get("name", "").lower()
        for row in agent_store.list_for_project(project_name, include_closed=False)
    }
    if name.lower() in existing_names:
        raise SystemExit(f"An open agent named `{name}` already exists in project `{project_name}`.")

    agent_id = new_id()
    parent_channel_id = ""
    announce_channel_id = control_channel_id
    thread_id = ""
    thread_name = ""

    if control_channel_id and not args.no_thread:
        parent_channel_id, announce_channel_id, thread_id = _create_visible_thread(
            control_channel_id,
            project_name,
            name,
            task=args.task or "",
        )
        thread_name = f"{project_name} · {name}"

    session_channel_id = thread_id or f"agent:{agent_id}"
    session = sess_store.create(project_name, session_channel_id, user_id, thread_id=thread_id)
    agent = agent_store.create(
        agent_id=agent_id,
        project_name=project_name,
        session_id=session["id"],
        parent_session_id=parent_session_id,
        name=name,
        role=role,
        user_id=user_id,
        control_channel_id=announce_channel_id,
        parent_channel_id=parent_channel_id,
        thread_id=thread_id,
        thread_name=thread_name,
    )

    if announce_channel_id and thread_id and not args.no_announce:
        _discord_send_chunks(announce_channel_id, f"🧵 Spawned agent **{name}**: <#{thread_id}>")

    worker = None
    if args.task:
        worker = _launch_worker(agent_id, args.task)
        agent = agent_store.get(agent_id) or agent

    payload = _agent_payload(agent)
    if worker:
        payload["worker"] = worker
    _emit(payload, args.json)


def cmd_list(args):
    project_name = _current_project_name(args.project) if not args.all_projects else ""
    if project_name:
        rows = agent_store.list_for_project(project_name, include_closed=args.include_closed)
    else:
        rows = agent_store.list_all(include_closed=args.include_closed)
    rows.sort(key=lambda r: (r.get("updated_at", ""), r.get("created_at", ""), r.get("id", "")), reverse=True)
    if args.json:
        return _emit(rows, True)
    if not rows:
        return _emit("No agents found.")
    lines = [f"{len(rows)} agent(s):"]
    for row in rows:
        mention = f" <#{row['thread_id']}>" if row.get("thread_id") else ""
        tail = (row.get("last_result") or row.get("last_error") or row.get("current_task") or "")[:120]
        lines.append(f"- {row['name']} [{row['status']}] id={row['id']} role={row['role']}{mention} {tail}")
    _emit("\n".join(lines))


def cmd_status(args):
    agent = agent_store.get(args.id)
    if not agent:
        raise SystemExit(f"Agent not found: {args.id}")
    _emit(_agent_payload(agent, include_history=args.include_history, history_limit=args.limit), args.json)


def cmd_message(args):
    agent = agent_store.get(args.id)
    if not agent:
        raise SystemExit(f"Agent not found: {args.id}")
    if agent.get("status") == "closed":
        raise SystemExit(f"Agent `{args.id}` is closed.")
    if _running(agent):
        raise SystemExit(f"Agent `{args.id}` is already running. Use `wait` or `status` first.")
    prompt = args.prompt.strip()
    if not prompt:
        raise SystemExit("No prompt provided.")
    if agent.get("thread_id"):
        _discord_send_chunks(agent["thread_id"], f"🧠 **Manager follow-up for `{agent['name']}`**\n{prompt}")
    worker = _launch_worker(agent["id"], prompt)
    updated = agent_store.get(agent["id"]) or agent
    payload = _agent_payload(updated)
    payload["worker"] = worker
    _emit(payload, args.json)


def cmd_wait(args):
    deadline = time.time() + args.timeout_seconds
    while time.time() < deadline:
        agent = agent_store.get(args.id)
        if not agent:
            raise SystemExit(f"Agent not found: {args.id}")
        if agent.get("status") != "running":
            return _emit(_agent_payload(agent, include_history=True, history_limit=args.limit), args.json)
        time.sleep(args.poll_seconds)
    raise SystemExit(f"Timed out waiting for agent `{args.id}`.")


def cmd_history(args):
    agent = agent_store.get(args.id)
    if not agent:
        raise SystemExit(f"Agent not found: {args.id}")
    rows = sess_store.list_messages(session_id=agent.get("session_id", ""), limit=args.limit)
    _emit(rows, args.json)


def cmd_logs(args):
    agent = agent_store.get(args.id)
    if not agent:
        raise SystemExit(f"Agent not found: {args.id}")
    log_path = agent.get("log_path", "")
    if not log_path or not os.path.exists(log_path):
        raise SystemExit("No log file found for that agent.")
    with open(log_path, "r", encoding="utf-8", errors="replace") as fh:
        lines = fh.readlines()[-args.lines:]
    text = "".join(lines).strip()
    _emit(text or "(empty log)", args.json)


def _stop_process(pid_text: str):
    if not pid_text:
        return
    try:
        pid = int(pid_text)
    except Exception:
        return
    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        return


def _stop_worker_direct(agent_id: str) -> dict:
    agent = agent_store.get(agent_id)
    if not agent:
        raise SystemExit(f"Agent not found: {agent_id}")
    if _running(agent):
        _stop_process(agent.get("pid", ""))
    return {
        "ok": True,
        "agent_id": agent_id,
        "stopped_pid": agent.get("pid", ""),
    }


def cmd_stop(args):
    agent = agent_store.get(args.id)
    if not agent:
        raise SystemExit(f"Agent not found: {args.id}")
    if _running(agent):
        if os.getenv("PEXO_AGENTS_DIRECT", "").lower() in ("1", "true", "yes"):
            _stop_worker_direct(agent["id"])
        else:
            _queue_agent_request({"cmd": "stop", "agent_id": agent["id"]})
    agent_store.mark_failed(agent["id"], "Stopped by manager.")
    updated = agent_store.get(agent["id"]) or agent
    if updated.get("thread_id"):
        _discord_send_chunks(updated["thread_id"], f"⛔ **Agent `{updated['name']}` was stopped by the manager.**")
    _emit(_agent_payload(updated), args.json)


def cmd_close(args):
    agent = agent_store.get(args.id)
    if not agent:
        raise SystemExit(f"Agent not found: {args.id}")
    if _running(agent):
        if os.getenv("PEXO_AGENTS_DIRECT", "").lower() in ("1", "true", "yes"):
            _stop_worker_direct(agent["id"])
        else:
            _queue_agent_request({"cmd": "stop", "agent_id": agent["id"]})
    sess_id = agent.get("session_id", "")
    if sess_id:
        sess_store.close(sess_id)
    agent_store.close(agent["id"])
    updated = agent_store.get(agent["id"]) or agent
    if updated.get("thread_id"):
        _discord_send_chunks(updated["thread_id"], f"🔒 **Agent `{updated['name']}` has been closed.**")
    _emit(_agent_payload(updated), args.json)


def cmd_worker(args):
    agent = agent_store.get(args.agent)
    if not agent:
        raise SystemExit(f"Agent not found: {args.agent}")
    if agent.get("status") == "closed":
        raise SystemExit(f"Agent `{args.agent}` is closed.")
    project = _project(agent.get("project_name", ""))
    prompt = agent.get("current_task", "").strip()
    if not prompt:
        agent_store.mark_idle(agent["id"], result=agent.get("last_result", ""))
        return

    thread_id = agent.get("thread_id", "")
    name = agent.get("name", agent["id"])
    if thread_id:
        _discord_send_chunks(thread_id, f"🤖 **Agent `{name}` is working...**")

    progress_state = {"last_sent": "", "last_at": 0.0}

    def on_progress(message: str):
        if not thread_id:
            return
        now = time.time()
        if message == progress_state["last_sent"]:
            return
        if now - progress_state["last_at"] < 3 and not message.startswith("⚠️"):
            return
        progress_state["last_sent"] = message
        progress_state["last_at"] = now
        try:
            _discord_send_chunks(thread_id, message)
        except Exception:
            pass

    try:
        result = asyncio.run(codex_exec.run(
            session_id=agent["session_id"],
            prompt=_build_agent_prompt(agent, prompt),
            project_path=project["path"],
            progress_cb=on_progress,
            channel_id=thread_id or f"agent:{agent['id']}",
            user_id=agent.get("user_id", ""),
        ))
        _mark_finished(agent["id"], result)
    except Exception as exc:
        _mark_failed(agent["id"], str(exc))
        raise


def execute_request(request: dict) -> dict:
    cmd = request.get("cmd", "")
    if cmd == "launch":
        return _launch_worker_direct(request.get("agent_id", ""))
    if cmd == "stop":
        return _stop_worker_direct(request.get("agent_id", ""))
    raise SystemExit(f"Unsupported agent request: {request}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pexo-agents")
    sub = parser.add_subparsers(dest="cmd", required=True)

    spawn = sub.add_parser("spawn")
    spawn.add_argument("--project", default="")
    spawn.add_argument("--channel", default="")
    spawn.add_argument("--user", default="")
    spawn.add_argument("--parent-session", default="")
    spawn.add_argument("--name", required=True)
    spawn.add_argument("--role", default="")
    spawn.add_argument("--task", default="")
    spawn.add_argument("--no-thread", action="store_true")
    spawn.add_argument("--no-announce", action="store_true")
    spawn.add_argument("--json", action="store_true")
    spawn.set_defaults(func=cmd_spawn)

    listing = sub.add_parser("list")
    listing.add_argument("--project", default="")
    listing.add_argument("--all-projects", action="store_true")
    listing.add_argument("--include-closed", action="store_true")
    listing.add_argument("--json", action="store_true")
    listing.set_defaults(func=cmd_list)

    status = sub.add_parser("status")
    status.add_argument("id")
    status.add_argument("--include-history", action="store_true")
    status.add_argument("--limit", type=int, default=8)
    status.add_argument("--json", action="store_true")
    status.set_defaults(func=cmd_status)

    message = sub.add_parser("message")
    message.add_argument("id")
    message.add_argument("--prompt", required=True)
    message.add_argument("--json", action="store_true")
    message.set_defaults(func=cmd_message)

    wait = sub.add_parser("wait")
    wait.add_argument("id")
    wait.add_argument("--timeout-seconds", type=int, default=600)
    wait.add_argument("--poll-seconds", type=float, default=2.0)
    wait.add_argument("--limit", type=int, default=8)
    wait.add_argument("--json", action="store_true")
    wait.set_defaults(func=cmd_wait)

    history = sub.add_parser("history")
    history.add_argument("id")
    history.add_argument("--limit", type=int, default=12)
    history.add_argument("--json", action="store_true")
    history.set_defaults(func=cmd_history)

    logs = sub.add_parser("logs")
    logs.add_argument("id")
    logs.add_argument("--lines", type=int, default=80)
    logs.add_argument("--json", action="store_true")
    logs.set_defaults(func=cmd_logs)

    stop = sub.add_parser("stop")
    stop.add_argument("id")
    stop.add_argument("--json", action="store_true")
    stop.set_defaults(func=cmd_stop)

    close = sub.add_parser("close")
    close.add_argument("id")
    close.add_argument("--json", action="store_true")
    close.set_defaults(func=cmd_close)

    worker = sub.add_parser("_worker", help=argparse.SUPPRESS)
    worker.add_argument("--agent", required=True)
    worker.set_defaults(func=cmd_worker)

    return parser


def main():
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
