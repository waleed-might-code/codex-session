"""
Codex execution layer.
Runs the local Codex CLI in JSON mode and maps its events into the existing
Discord session flow used by the bot.
"""
import asyncio
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable

import storage.cloudflare as cf_store
import storage.github as gh_store
import storage.sessions as sessions_store
from utils.security import truncate

BOT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MODEL = os.getenv("CODEX_MODEL", "")

_active_processes: dict[str, asyncio.subprocess.Process] = {}
_token_totals: dict[str, dict] = {}
_cancel_flags: dict[str, bool] = {}


class TurnLimitReached(Exception):
    def __init__(self, partial_result: str):
        super().__init__(partial_result)
        self.partial_result = partial_result


def register_bulk_session(bulk_run_id: str, session_id: str, spec_name: str,
                          spec_index: int, all_specs: list):
    # Compatibility hook used by bot.py bulk mode.
    return None


def cancel_session(session_id: str):
    _cancel_flags[session_id] = True
    proc = _active_processes.get(session_id)
    if proc and proc.returncode is None:
        proc.terminate()


def clear_cancel(session_id: str):
    _cancel_flags.pop(session_id, None)


def _tool_paths() -> dict[str, str]:
    return {
        "PEXO_PYTHON": sys.executable,
        "PEXO_SSH": str(BOT_ROOT / "tools" / "pexo_ssh.py"),
        "PEXO_GITHUB": str(BOT_ROOT / "tools" / "pexo_github.py"),
        "PEXO_TUNNEL": str(BOT_ROOT / "tools" / "pexo_tunnel.py"),
    }


def _get_env() -> dict:
    env = {**os.environ, **_tool_paths()}
    token = cf_store.get_token()
    account_id = cf_store.get_account_id()
    if token:
        env["CLOUDFLARE_API_TOKEN"] = token
        env["CLOUDFLARE_TOKEN"] = token
        env["cloudflare_token"] = token
    if account_id:
        env["CLOUDFLARE_ACCOUNT_ID"] = account_id

    gh_token = gh_store.get_token()
    gh_user = gh_store.get_username()
    if gh_token:
        env["GITHUB_TOKEN"] = gh_token
    if gh_user:
        env["GITHUB_USERNAME"] = gh_user
    return env


def _build_prompt(prompt: str, project_path: str, initial_run: bool) -> str:
    if not initial_run:
        return prompt

    return (
        "[DISCORD CONTEXT]\n"
        "You are Codex running behind a Discord bot that manages local projects, GitHub, "
        "SSH deployments, and Cloudflare tunnels.\n"
        f"Project path: {project_path}\n"
        "Keep updates concise and focused on completed work.\n"
        "Use the provided environment variables for infrastructure tasks:\n"
        "- $PEXO_PYTHON $PEXO_SSH for SSH and deploy operations\n"
        "- $PEXO_PYTHON $PEXO_GITHUB for GitHub repo, commit, branch, and PR operations\n"
        "- $PEXO_PYTHON $PEXO_TUNNEL for Cloudflare tunnel/domain operations\n"
        "Do not expose secrets in output.\n\n"
        f"User task:\n{prompt}"
    )


def _summarize_file_changes(changes: list[dict]) -> str:
    if not changes:
        return "📝 File change"
    parts = []
    for change in changes[:5]:
        kind = change.get("kind", "update")
        path = change.get("path", "")
        if path:
            parts.append(f"{kind} `{os.path.basename(path)}`")
    extra = "" if len(changes) <= 5 else f" (+{len(changes) - 5} more)"
    return "📝 " + ", ".join(parts) + extra


def _trim_command(command: str) -> str:
    command = " ".join((command or "").split())
    if len(command) <= 140:
        return command
    return command[:137] + "..."


def _maybe_progress(progress_cb: Callable[[str], None] | None, message: str):
    if progress_cb:
        progress_cb(message)


async def _run_exec(
    prompt: str,
    project_path: str,
    progress_cb: Callable[[str], None] = None,
    image_data: bytes = None,
    image_media_type: str = "image/png",
    session_id: str = "",
    resume_thread_id: str = "",
    ephemeral: bool = False,
    sandbox: str = "workspace-write",
) -> tuple[str, str, dict]:
    env = _get_env()
    output_path = Path(tempfile.gettempdir()) / f"codex_last_{session_id or 'ephemeral'}.txt"
    image_path = None
    stderr_chunks = []
    usage = {"input": 0, "output": 0}
    final_text = ""
    thread_id = resume_thread_id
    initial_run = not bool(resume_thread_id)

    if image_data:
        suffix = ".png"
        if image_media_type.endswith("jpeg") or image_media_type.endswith("jpg"):
            suffix = ".jpg"
        fd, temp_path = tempfile.mkstemp(prefix="codex_image_", suffix=suffix)
        os.close(fd)
        with open(temp_path, "wb") as f:
            f.write(image_data)
        image_path = temp_path

    cmd = ["codex", "exec"]
    if resume_thread_id:
        cmd.extend(["resume", resume_thread_id])
        if DEFAULT_MODEL:
            cmd.extend(["-m", DEFAULT_MODEL])
        cmd.extend([
            "--json",
            "--skip-git-repo-check",
            "-o", str(output_path),
        ])
        if ephemeral:
            cmd.append("--ephemeral")
    else:
        if DEFAULT_MODEL:
            cmd.extend(["-m", DEFAULT_MODEL])
        cmd.extend([
            "--json",
            "--skip-git-repo-check",
            "--sandbox", sandbox,
            "-C", project_path,
            "--add-dir", str(BOT_ROOT),
            "-o", str(output_path),
        ])
        if ephemeral:
            cmd.append("--ephemeral")
    if image_path:
        cmd.extend(["-i", image_path])
    cmd.append("-")

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=project_path,
        env=env,
    )

    if session_id:
        _active_processes[session_id] = proc

    prepared_prompt = _build_prompt(prompt, project_path, initial_run)
    proc.stdin.write(prepared_prompt.encode("utf-8"))
    await proc.stdin.drain()
    proc.stdin.close()

    async def read_stdout():
        nonlocal final_text, thread_id, usage
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            raw = line.decode("utf-8", errors="replace").strip()
            if not raw:
                continue
            try:
                event = json.loads(raw)
            except json.JSONDecodeError:
                continue

            etype = event.get("type", "")
            if etype == "thread.started":
                thread_id = event.get("thread_id", thread_id)
                if session_id and thread_id:
                    sessions_store.set_backend_session_id(session_id, thread_id)
                _maybe_progress(progress_cb, f"🤖 Codex session `{thread_id}` started")
                continue

            if etype == "turn.started":
                _maybe_progress(progress_cb, "🤔 Codex is working...")
                continue

            if etype == "error":
                _maybe_progress(progress_cb, f"⚠️ {event.get('message', 'Codex reported an error')}")
                continue

            if not etype.startswith("item."):
                if etype == "turn.completed":
                    usage["input"] += int(event.get("usage", {}).get("input_tokens", 0) or 0)
                    usage["output"] += int(event.get("usage", {}).get("output_tokens", 0) or 0)
                continue

            item = event.get("item", {})
            item_type = item.get("type", "")
            if item_type == "command_execution":
                command = _trim_command(item.get("command", ""))
                status = item.get("status", "")
                if etype == "item.started":
                    _maybe_progress(progress_cb, f"▶ {command}")
                elif etype == "item.completed":
                    code = item.get("exit_code")
                    output = (item.get("aggregated_output") or "").strip()
                    summary = f"✔ {command} (exit {code})"
                    if output:
                        first_line = output.splitlines()[0]
                        summary += f" — {truncate(first_line, 120)}"
                    _maybe_progress(progress_cb, summary)
                continue

            if item_type == "file_change":
                _maybe_progress(progress_cb, _summarize_file_changes(item.get("changes", [])))
                continue

            if item_type == "agent_message" and etype == "item.completed":
                text = item.get("text", "").strip()
                if text:
                    final_text = text
                continue

    async def read_stderr():
        while True:
            line = await proc.stderr.readline()
            if not line:
                break
            stderr_chunks.append(line.decode("utf-8", errors="replace"))

    await asyncio.gather(read_stdout(), read_stderr())
    return_code = await proc.wait()

    if session_id:
        _active_processes.pop(session_id, None)

    if output_path.exists():
        try:
            saved = output_path.read_text(encoding="utf-8").strip()
            if saved:
                final_text = saved
        except Exception:
            pass

    if image_path:
        try:
            os.unlink(image_path)
        except Exception:
            pass

    stderr_text = "".join(stderr_chunks).strip()
    if return_code != 0:
        if _cancel_flags.get(session_id):
            clear_cancel(session_id)
            if final_text:
                final_text += "\n\n⛔ Stopped by user."
            else:
                final_text = "⛔ Stopped by user."
        else:
            if "cannot access session files" in stderr_text.lower():
                raise RuntimeError(
                    stderr_text +
                    "\nHint: run the bot with a writable Codex home, or set CODEX_HOME to a writable directory."
                )
            raise RuntimeError(stderr_text or f"Codex exited with code {return_code}")

    return final_text or "(no response)", thread_id, usage


async def run(
    session_id: str,
    prompt: str,
    project_path: str,
    progress_cb: Callable[[str], None] = None,
    max_turns: int = 20,
    image_data: bytes = None,
    image_media_type: str = "image/png",
    channel_id: str = "",
    bulk_run_id: str = "",
) -> str:
    backend_session_id = sessions_store.get_backend_session_id(session_id)
    final_text, thread_id, usage = await _run_exec(
        prompt=prompt,
        project_path=project_path,
        progress_cb=progress_cb,
        image_data=image_data,
        image_media_type=image_media_type,
        session_id=session_id,
        resume_thread_id=backend_session_id,
    )

    sessions_store.append_history(session_id, "user", prompt)
    sessions_store.append_history(session_id, "assistant", final_text)
    sessions_store.update_last_prompt(session_id, prompt)
    if thread_id:
        sessions_store.set_backend_session_id(session_id, thread_id)

    totals = _token_totals.setdefault(session_id, {"input": 0, "output": 0})
    totals["input"] += usage["input"]
    totals["output"] += usage["output"]
    clear_cancel(session_id)
    return final_text


async def run_once(
    prompt: str,
    project_path: str,
    image_data: bytes = None,
    image_media_type: str = "image/png",
    sandbox: str = "read-only",
) -> tuple[str, dict]:
    text, _, usage = await _run_exec(
        prompt=prompt,
        project_path=project_path,
        image_data=image_data,
        image_media_type=image_media_type,
        ephemeral=True,
        sandbox=sandbox,
    )
    return text, usage


def get_token_usage(session_id: str) -> dict:
    return _token_totals.get(session_id, {"input": 0, "output": 0})


def close_session_shell(session_id: str):
    cancel_session(session_id)
    _active_processes.pop(session_id, None)


async def get_diff(project_path: str) -> str:
    proc = await asyncio.create_subprocess_shell(
        "git diff -- .",
        cwd=project_path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    output = (stdout + stderr).decode("utf-8", errors="replace").strip()
    return truncate(output or "(no diff)", 3500)


async def get_status(project_path: str) -> str:
    proc = await asyncio.create_subprocess_shell(
        "git status --short --branch",
        cwd=project_path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    output = (stdout + stderr).decode("utf-8", errors="replace").strip()
    return truncate(output or "(no status)", 3500)


def extract_json(text: str) -> dict:
    cleaned = (text or "").strip()
    if "```" in cleaned:
        parts = cleaned.split("```")
        if len(parts) >= 2:
            cleaned = parts[1]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
            cleaned = cleaned.strip()
    return json.loads(cleaned)
