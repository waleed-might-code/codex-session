"""
Codex execution layer.
Runs the local Codex CLI in JSON mode and maps its events into the existing
Discord session flow used by the bot.
"""
import asyncio
import json
import os
import shutil
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
        "PEXO_CONTEXT": str(BOT_ROOT / "tools" / "pexo_context.py"),
        "PEXO_DISCORD": str(BOT_ROOT / "tools" / "pexo_discord.py"),
    }


def _resolve_codex_home() -> str:
    configured = os.getenv("CODEX_HOME", "").strip()
    source_home = Path(configured).expanduser() if configured else (Path.home() / ".codex")

    def ensure_writable(path: Path) -> bool:
        try:
            path.mkdir(parents=True, exist_ok=True)
            (path / "sessions").mkdir(parents=True, exist_ok=True)
            probe = path / ".write_test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            return True
        except Exception:
            return False

    def sync_runtime_auth(source: Path, target: Path):
        for name in ("auth.json", "config.toml", "installation_id", "version.json", ".codex-global-state.json"):
            src = source / name
            dst = target / name
            if not src.exists():
                continue
            if not dst.exists() or src.stat().st_mtime > dst.stat().st_mtime:
                shutil.copy2(src, dst)

    if ensure_writable(source_home):
        return str(source_home) if configured else ""

    runtime_home = BOT_ROOT / ".codex-runtime"
    runtime_home.mkdir(parents=True, exist_ok=True)
    (runtime_home / "sessions").mkdir(parents=True, exist_ok=True)
    sync_runtime_auth(source_home, runtime_home)
    if not ensure_writable(runtime_home):
        raise RuntimeError(
            f"Codex cannot access session files at {source_home} and fallback runtime home "
            f"{runtime_home} is also not writable."
        )
    return str(runtime_home)


def _get_env() -> dict:
    env = {**os.environ, **_tool_paths()}
    codex_home = _resolve_codex_home()
    if codex_home:
        env["CODEX_HOME"] = codex_home
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
        "SSH deployments, Discord workflows, and Cloudflare tunnels.\n"
        f"Project path: {project_path}\n"
        "Keep updates concise and focused on completed work.\n"
        "Use the provided environment variables for infrastructure tasks:\n"
        "- $PEXO_PYTHON $PEXO_SSH for SSH and deploy operations\n"
        "- $PEXO_PYTHON $PEXO_GITHUB for GitHub repo, commit, branch, and PR operations\n"
        "- $PEXO_PYTHON $PEXO_TUNNEL for Cloudflare tunnel/domain operations\n"
        "- $PEXO_PYTHON $PEXO_CONTEXT for project/session/history inspection and switching\n"
        "- $PEXO_PYTHON $PEXO_DISCORD for Discord messages, scheduling, and thread creation\n"
        "Default to the current project/session/channel scope. Only inspect or switch other "
        "projects or histories when the user explicitly asks.\n"
        "If you switch projects, confirm the change and stop there; the new project binding "
        "takes effect on the next bot turn.\n"
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


def _friendly_exec_error(stderr_text: str) -> str:
    lower = (stderr_text or "").lower()
    if "401 unauthorized" in lower or "missing bearer or basic authentication" in lower:
        return (
            "Codex CLI is not authenticated for the user running the bot. "
            "Run `codex login` in the same shell/user context, then retry."
        )
    if "failed to lookup address information" in lower or "name resolution" in lower:
        return (
            "Codex CLI could not reach the OpenAI API. "
            "Check outbound network/DNS for this machine, then retry."
        )
    if "cannot access session files" in lower:
        return (
            stderr_text +
            "\nHint: run the bot with a writable Codex home, or set CODEX_HOME to a writable directory."
        )
    if "connection error" in lower:
        return "Codex lost its connection to the API. Retrying usually fixes this."
    return stderr_text or "Codex exited with an unknown error."


def _is_retryable_exec_error(message: str) -> bool:
    lower = (message or "").lower()
    if any(bad in lower for bad in (
        "401 unauthorized",
        "missing bearer or basic authentication",
        "not authenticated",
        "cannot access session files",
        "active project path does not exist",
    )):
        return False
    return any(pattern in lower for pattern in (
        "connection error",
        "transport error",
        "timed out",
        "timeout",
        "temporarily unavailable",
        "502 bad gateway",
        "503 service unavailable",
        "504 gateway timeout",
        "server disconnected",
    ))


async def _run_exec(
    prompt: str,
    project_path: str,
    progress_cb: Callable[[str], None] = None,
    image_data: bytes = None,
    image_media_type: str = "image/png",
    session_id: str = "",
    channel_id: str = "",
    resume_thread_id: str = "",
    ephemeral: bool = False,
    sandbox: str = "workspace-write",
) -> tuple[str, str, dict]:
    if not os.path.isdir(project_path):
        raise RuntimeError(
            f"Active project path does not exist on this machine: {project_path}. "
            "Use /project use or /project add to select a valid local path."
        )

    env = _get_env()
    if channel_id:
        env["PEXO_CHANNEL_ID"] = channel_id
    if session_id:
        env["PEXO_SESSION_ID"] = session_id
    env["PEXO_PROJECT_PATH"] = project_path
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
                message = event.get("message", "Codex reported an error")
                lower = message.lower()
                if "reconnecting..." in lower and (
                    "401 unauthorized" in lower
                    or "missing bearer or basic authentication" in lower
                    or "failed to lookup address information" in lower
                ):
                    continue
                _maybe_progress(progress_cb, f"⚠️ {message}")
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
            raise RuntimeError(_friendly_exec_error(stderr_text))

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
    final_text = ""
    thread_id = ""
    usage = {"input": 0, "output": 0}
    last_error = None
    pending_prompt = prompt

    for attempt in range(2):
        backend_session_id = sessions_store.get_backend_session_id(session_id)
        try:
            final_text, thread_id, usage = await _run_exec(
                prompt=pending_prompt,
                project_path=project_path,
                progress_cb=progress_cb,
                image_data=image_data,
                image_media_type=image_media_type,
                session_id=session_id,
                channel_id=channel_id,
                resume_thread_id=backend_session_id,
            )
            break
        except RuntimeError as e:
            last_error = e
            if attempt == 0 and _is_retryable_exec_error(str(e)):
                stale_backend_id = sessions_store.get_backend_session_id(session_id)
                if stale_backend_id:
                    sessions_store.clear_backend_session_id(session_id)
                    pending_prompt = sessions_store.build_recovery_prompt(session_id, prompt)
                    _maybe_progress(progress_cb, "⚠️ Previous Codex backend thread became unusable. Starting a fresh backend session with preserved context...")
                _maybe_progress(progress_cb, "⚠️ Codex connection dropped. Retrying once...")
                await asyncio.sleep(2)
                continue
            raise
    else:
        raise last_error

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
