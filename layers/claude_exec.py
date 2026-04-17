"""
Claude execution layer.
Features: persistent bash session, web fetch, CLAUDE.md loading,
git context injection, token tracking, context compaction, extended thinking.
"""
import asyncio
import sys
import json
import os
import subprocess
from pathlib import Path
from typing import Callable

import anthropic
import httpx

import storage.sessions as sessions_store
from utils.security import safe_relative, truncate, CMD_TIMEOUT
from layers.persistent_shell import PersistentShell

MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-5-20250514")
ENABLE_THINKING = os.getenv("ENABLE_THINKING", "false").lower() == "true"

# Per-session persistent shells
_shells: dict[str, PersistentShell] = {}

# Per-session token totals: {session_id: {"input": int, "output": int}}
_token_totals: dict[str, dict] = {}

# Cancellation flags: {session_id: True} means "stop after current turn"
_cancel_flags: dict[str, bool] = {}

# Context compaction threshold (~120k chars of message history)
COMPACTION_THRESHOLD = 120_000

# ── Multi-agent bulk coordination ─────────────────────────────────────────────
# session_id → {bulk_run_id, spec_name, spec_index, all_specs}
_session_bulk_ctx: dict[str, dict] = {}

# bulk_run_id → {session_id: spec_name}  — all sessions in this run
_bulk_run_sessions: dict[str, dict] = {}

# (project_path, rel_file_path) → {bulk_run_id, session_id, spec_name}
# Tracks which session last *wrote* each file so other agents can avoid blind overwrites
_bulk_file_claims: dict[tuple, dict] = {}


def register_bulk_session(bulk_run_id: str, session_id: str, spec_name: str,
                           spec_index: int, all_specs: list):
    """Register a session as part of a bulk run. Called from bot.py before each run()."""
    _session_bulk_ctx[session_id] = {
        "bulk_run_id": bulk_run_id,
        "spec_name": spec_name,
        "spec_index": spec_index,
        "all_specs": all_specs,
    }
    _bulk_run_sessions.setdefault(bulk_run_id, {})[session_id] = spec_name


def cancel_session(session_id: str):
    _cancel_flags[session_id] = True


def clear_cancel(session_id: str):
    _cancel_flags.pop(session_id, None)


TOOLS = [
    {
        "name": "bash",
        "description": "Run a shell command. CWD persists across calls — cd, exports, and variable assignments carry over within a session.",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "timeout": {"type": "integer", "description": "Timeout in seconds (default 120)"},
            },
            "required": ["command"],
        },
    },
    {
        "name": "read_file",
        "description": "Read a file in the project.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Path relative to project root"}},
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "Write, append, or patch a file. HARD LIMIT: content MUST be under 3000 chars per call — larger calls WILL fail. For big files: write first ~2500 chars, then append the rest in ~2500 char chunks. For edits: use mode='patch' with old_str/new_str.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path relative to project root"},
                "content": {"type": "string", "description": "File content — MUST be under 3000 chars. Split larger files into multiple append calls."},
                "mode": {"type": "string", "description": "write (default), append, or patch"},
                "old_str": {"type": "string", "description": "Text to find (patch mode)"},
                "new_str": {"type": "string", "description": "Replacement text (patch mode)"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "list_directory",
        "description": "List files and directories in the project.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Directory relative to project root (default: .)"},
                "depth": {"type": "integer", "description": "Max depth (default 2)"},
            },
            "required": [],
        },
    },
    {
        "name": "search_files",
        "description": "Search for text across project files.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "file_pattern": {"type": "string", "description": "Glob pattern e.g. '*.py'"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "fetch_url",
        "description": "Fetch a URL and return the response body. Use for reading docs, APIs, or checking live endpoints.",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "method": {"type": "string", "description": "GET or POST (default: GET)"},
                "body": {"type": "string", "description": "Request body for POST"},
            },
            "required": ["url"],
        },
    },
    {
        "name": "send_file",
        "description": (
            "Send any file from the project directly to Discord as a downloadable attachment. "
            "Use this to share source code files, logs, CSVs, ZIPs, PDFs, config files, or any output. "
            "The file appears in Discord exactly as named — users can click to download or view it inline. "
            "For images use send_image instead. For large outputs that won't fit in a message, use this."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path relative to project root"},
                "caption": {"type": "string", "description": "Optional message to send alongside the file"},
                "filename": {"type": "string", "description": "Override the filename shown in Discord (default: same as path)"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "send_image",
        "description": "Send any image file or image URL directly to Discord. Use this to share generated images, charts, diagrams, downloaded images, or any visual without needing a browser.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Local file path to the image (relative to project root)"},
                "url": {"type": "string", "description": "Public image URL to download and send"},
                "caption": {"type": "string", "description": "Caption for the image"},
            },
            "required": [],
        },
    },
    {
        "name": "screenshot",
        "description": "Start the local dev server (if needed) and take a screenshot of the UI. The image is sent directly to Discord. Use this whenever you create or modify frontend code to show the result.",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to screenshot (default: auto-detect from project)"},
                "mobile": {"type": "boolean", "description": "Take mobile viewport screenshot"},
                "caption": {"type": "string", "description": "Caption to send with the image"},
            },
            "required": [],
        },
    },
    {
        "name": "browser_console",
        "description": "Get captured browser console logs (console.log, console.error, warnings, JS exceptions). Call after screenshot to see what happened in the browser. Essential for debugging React/HTML/JS apps.",
        "input_schema": {
            "type": "object",
            "properties": {
                "clear": {"type": "boolean", "description": "Clear logs after reading (default: false)"},
            },
            "required": [],
        },
    },
    {
        "name": "browser_action",
        "description": "Interact with the browser page: click buttons, fill forms, type text, upload files, press keys, scroll. Use this to test the app like a real user. The action screenshot is sent to Discord.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "description": "click, fill, type, select, upload, press, scroll, navigate, wait, evaluate_js"},
                "selector": {"type": "string", "description": "CSS selector for the target element"},
                "value": {"type": "string", "description": "Value for fill/type/select, file path for upload, key for press, JS code for evaluate_js"},
                "url": {"type": "string", "description": "URL for navigate action"},
                "pixels": {"type": "integer", "description": "Pixels for scroll action"},
            },
            "required": ["action"],
        },
    },
    {
        "name": "test_flow",
        "description": (
            "Run a sequence of browser test steps with per-step screenshots, assertions, "
            "URL tracking, console error capture, and video recording. "
            "Each step screenshot is sent to Discord so you can see exactly what happened. "
            "Actions: click, fill, type, select, upload, press, navigate, scroll, wait, hover, screenshot. "
            "Assertions (abort on fail): assert_text (element contains text), "
            "assert_visible (element exists), assert_url (URL contains string), "
            "assert_not_text (element does NOT contain forbidden text). "
            "Use assert_* steps after every important interaction to verify the app responded correctly."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to test (default: auto-detect from project)"},
                "steps": {
                    "type": "array",
                    "description": "Array of test steps. Each step is executed in order.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "action": {
                                "type": "string",
                                "description": "click|fill|type|select|upload|press|navigate|scroll|wait|hover|screenshot|assert_text|assert_visible|assert_url|assert_not_text",
                            },
                            "selector": {"type": "string", "description": "CSS selector for the target element"},
                            "value": {"type": "string", "description": "Text to type/fill, or expected value for assert actions"},
                            "expected": {"type": "string", "description": "Alias for value in assert actions"},
                            "description": {"type": "string", "description": "Human-readable label shown in step result"},
                            "fallback_selectors": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Alternative selectors to try if primary selector fails (for click)",
                            },
                            "key": {"type": "string", "description": "Key name for press action (Enter, Tab, Escape, etc.)"},
                            "file_path": {"type": "string", "description": "Absolute path to file for upload action"},
                            "url": {"type": "string", "description": "URL for navigate action"},
                            "pixels": {"type": "integer", "description": "Pixels to scroll for scroll action"},
                            "seconds": {"type": "number", "description": "Seconds to wait for wait action"},
                            "abort_on_fail": {"type": "boolean", "description": "Stop test if this step fails (default: true for asserts, false for others)"},
                        },
                        "required": ["action"],
                    },
                },
                "record": {"type": "boolean", "description": "Record video of the entire flow (default: true)"},
            },
            "required": ["steps"],
        },
    },
    {
        "name": "deploy_update",
        "description": "Update an already-deployed service: git pull → reinstall deps → restart → health check. Reports progress and auto-rolls back on failure.",
        "input_schema": {
            "type": "object",
            "properties": {
                "service_name": {"type": "string", "description": "Name of the systemd service to update"},
                "server": {"type": "string", "description": "Server alias (default: default server)"},
                "branch": {"type": "string", "description": "Git branch (default: main)"},
                "start_cmd": {"type": "string", "description": "Override the start command"},
            },
            "required": ["service_name"],
        },
    },
    {
        "name": "list_projects",
        "description": "List all registered projects with their paths, git branches, and which channel they're active in. Use this to see what projects exist.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "list_deployments",
        "description": "List all deployed services across all servers — shows service name, server, port, status, deploy type, and URL. Use this to see what's running.",
        "input_schema": {
            "type": "object",
            "properties": {
                "server": {"type": "string", "description": "Filter by server name (optional — shows all if omitted)"},
            },
            "required": [],
        },
    },
    {
        "name": "service_health",
        "description": "Check the health of a deployed service: active state, PID, memory usage, uptime, and recent logs. Use this to diagnose issues with a running service.",
        "input_schema": {
            "type": "object",
            "properties": {
                "service_name": {"type": "string", "description": "Name of the systemd service to check"},
                "server": {"type": "string", "description": "Server alias (default: default server)"},
            },
            "required": ["service_name"],
        },
    },
    {
        "name": "allocate_port",
        "description": (
            "Reserve the next available port for a new service on a server. "
            "Checks the port registry to avoid conflicts. "
            "ALWAYS call this before starting any new service — never pick a port manually. "
            "Returns the allocated port number."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "server_name": {"type": "string", "description": "Server name (leave blank for default)"},
                "service_name": {"type": "string", "description": "Name for the service (e.g. 'myapp-api')"},
            },
            "required": ["service_name"],
        },
    },
    {
        "name": "free_port",
        "description": "Release a port allocation when a service is removed or stopped.",
        "input_schema": {
            "type": "object",
            "properties": {
                "server_name": {"type": "string", "description": "Server name"},
                "service_name": {"type": "string", "description": "Service name to release"},
            },
            "required": ["service_name"],
        },
    },
    {
        "name": "list_infrastructure",
        "description": (
            "Show FULL infrastructure map: all servers, allocated ports, domain→service→port mappings, "
            "tunnels, and live port usage. ALWAYS call this before deploying, exposing, or managing "
            "domains/tunnels to avoid port conflicts and domain overwrites."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "server": {"type": "string", "description": "Filter by server (optional — shows all if omitted)"},
                "check_live": {"type": "boolean", "description": "Also check live ports via ss on the server (slower but accurate)"},
            },
            "required": [],
        },
    },
]

SYSTEM_PROMPT_BASE = """You are Claude Code, an expert full-stack software engineer and systems architect.
You are operating inside a Discord-based coding workspace. The user sends you tasks via Discord.

═══════════════════════════════════════════════════════════
CURRENT TASK: {current_task}
═══════════════════════════════════════════════════════════
^^^ THIS IS YOUR #1 PRIORITY. Every tool call must make progress toward this task.
Do NOT get distracted by exploration. Do NOT list directories unless you need a specific file you can't find.

CURRENT PROJECT:
  Name: {project_name}
  Path: {project_path}
  Shell CWD starts here. ALL your work happens here.

{project_files}

{session_recap}

{claude_md}

TASK EXECUTION RULES (most important):
1. START WORKING IMMEDIATELY. Your FIRST tool call must write code, run a build command, or fix something. NOT explore.
2. You ALREADY HAVE the full project file tree above — NEVER run ls, find, pwd, or tree via bash. NEVER call list_directory. You already know what files exist.
3. READ ONLY FILES YOU WILL ACTUALLY EDIT. Do not read files "just to understand the codebase". Read a file only if you need its content to write something.
4. NEVER run the same bash command twice. If a command gives you the information you need, use it and move on.
5. After every tool call, ask: "Did this directly produce code or output for the task?" If not, you wasted a turn. Refocus.
6. When the task is done, summarize what changed. Do not keep exploring or validating beyond what was asked.

DIRECTORY RULES:
- Working directory: {project_path}. ALL files live here.
- BEFORE any git command: `cd {project_path}` first.
- NEVER use `pwd`, `ls`, `find`, or `tree` — you already have the full file tree above.
- If you need to check a subdirectory not in the tree, use list_directory — but only once, only if truly needed.

General Rules:
- Read files before editing. Make targeted, precise edits.
- bash CWD persists across calls. Use cd freely within the project.
- When continuing a previous task, check the session recap above.
- Never expose passwords, tokens, or keys.
- Keep responses concise but complete.
- NEVER use ssh, sshpass, or raw SSH commands. Use $PEXO_SSH.
- NEVER guess or hardcode credentials.
- NEVER start dev servers in bash. Use the screenshot tool.
- When asked for UI/preview/screenshot: call screenshot immediately.
- SELF-TESTING IS MANDATORY after creating/modifying web apps:
  1. Screenshot to verify UI renders. Console logs are auto-captured — fix errors immediately.
  2. Use browser_action for quick single interactions. Use test_flow for full end-to-end flows.
  3. test_flow sends a screenshot per step to Discord — use it to prove the app works.
  4. Always include assert_* steps after interactions: assert_text to verify responses,
     assert_url to verify navigation, assert_visible to verify elements appeared.
     Example: fill a form → click submit → assert_text on result element → assert_url if redirect expected.
  5. Use fallback_selectors on click steps for resilience (e.g. try button text, then ID, then class).
  6. Do NOT tell the user to test — YOU test it.
- Page audit detects: DEAD_LINK, DEAD_BUTTON, BROKEN_IMG, ORPHAN_FORM, EMPTY_CONTAINER, etc. Fix ALL.
- HTML files get auto-instrumented. [PEXO] errors in console = fix immediately.
- INFRASTRUCTURE RULES (MANDATORY):
  1. Call `list_infrastructure` BEFORE ANY deployment or domain change.
  2. Call `allocate_port` to get a port for every new service — NEVER pick one manually.
  3. NEVER use a port already shown in list_infrastructure output.
  4. NEVER attach a subdomain/hostname already shown in list_infrastructure output.
  5. One tunnel per server — all services on the same server share the tunnel with different hostnames.
  6. Use `free_port` when removing/stopping a service.
- WRITING FILES — use write_file tool, NOT bash cat/heredoc:
  ⚠️ HARD LIMIT: Each write_file call must have content UNDER 3000 characters. This is enforced — larger content WILL be rejected.
  Small files (<3000 chars): write_file with mode "write" and full content — one call.
  Larger files (CSS, HTML, JS, etc.): You MUST split across multiple calls:
    1. write_file mode="write" with first ~2500 chars (creates/overwrites)
    2. write_file mode="append" with next ~2500 chars
    3. Continue appending until complete
  For CSS/styling: break at logical section boundaries (variables, layout, components, animations).
  Editing existing files: use write_file mode="patch" with old_str and new_str. Preferred for any change.
  NEVER use cat > or cat >> or heredoc in bash. Always use write_file.
  NEVER try to write a complete CSS, HTML, or JS file in one call if it's more than ~80 lines.

INFRASTRUCTURE — already configured:
{infra_context}

DEPLOYMENT RULES:

BACKEND (Flask, FastAPI, Django, any server process):
- ALWAYS deploy to SSH server via systemd. NEVER use Vercel, Railway, Render, Heroku, Workers.
- After deploy, backend is private (127.0.0.1:<port>). Use Cloudflare Tunnel to expose publicly.
- Pattern: SSH deploy → systemd → Cloudflare Tunnel → public HTTPS URL.

FRONTEND (React, Vue, HTML/CSS/JS, static):
- ALWAYS deploy to Cloudflare Pages. NEVER use SSH/http.server for frontend.
- CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID are already in your bash environment.
- Correct deploy sequence (both steps required):
    # Step 1: create project (only needed once per project name)
    wrangler pages project create <name> --production-branch=main 2>&1 || true
    # Step 2: deploy
    wrangler pages deploy <dist_dir> --project-name=<name> --commit-dirty=true 2>&1
- If "project not found" error: run step 1 first, then step 2.
- If "limit of projects" error: tell the user their CF Pages limit is full (max 10 on free plan) and ask them to delete old projects via /cloudflare or the CF dashboard.
- After deploy, share the .pages.dev URL printed by wrangler.

WORKERS: Only for edge JS/TS. Never for Python. Never as a backend substitute.

TUNNEL TOOL — use $PEXO_PYTHON $PEXO_TUNNEL for ALL Cloudflare Tunnel operations. NEVER use raw curl or cloudflared commands directly.
Public domain comes from $PEXO_CF_DOMAIN. Format: <service-name>.<your-domain>

  # Expose a backend service publicly (creates tunnel + DNS + installs cloudflared on server)
  $PEXO_PYTHON $PEXO_TUNNEL expose <service-name> <port>
  # Example: after deploying Flask API on port 5022:
  $PEXO_PYTHON $PEXO_TUNNEL expose my-api 5022
  # → live at https://my-api.<your-domain>

  # Check status
  $PEXO_PYTHON $PEXO_TUNNEL status <service-name>

  # List all tunnels
  $PEXO_PYTHON $PEXO_TUNNEL list

  # Remove tunnel + DNS + service
  $PEXO_PYTHON $PEXO_TUNNEL delete <service-name>

  # Tail tunnel logs
  $PEXO_PYTHON $PEXO_TUNNEL logs <service-name>

Rules:
- Always run pexo-tunnel AFTER the backend service is confirmed running.
- Share the PUBLIC_URL printed by the tool with the user.
- NEVER use cloudflared CLI directly, NEVER use raw CF API curl for tunnels.

SSH TOOL — $PEXO_SSH is available in your bash environment. Use it for ALL SSH operations:

  # List configured servers
  $PEXO_PYTHON $PEXO_SSH list

  # Run a command on a server
  $PEXO_PYTHON $PEXO_SSH <server_name> exec "apt-get install -y python3"

  # Deploy/restart a backend service (handles venv, pip, systemd automatically)
  $PEXO_PYTHON $PEXO_SSH <server_name> deploy <service_name> \
    --start-cmd "venv/bin/python app.py" \
    --env PORT=5022 --env FLASK_ENV=production

  # Deploy from a git repo
  $PEXO_PYTHON $PEXO_SSH <server_name> deploy <service_name> --repo https://github.com/...

  # Upload a local file to server
  $PEXO_PYTHON $PEXO_SSH <server_name> upload ./local_file.py /root/services/app/app.py

  # Tail service logs
  $PEXO_PYTHON $PEXO_SSH <server_name> logs <service_name> --lines 50

SSH reliability: pexo-ssh handles retries and timeouts automatically.

GITHUB — use $PEXO_PYTHON $PEXO_GITHUB for ALL GitHub operations. NEVER use raw curl or gh CLI.
ALWAYS use --dir {project_path} when pushing/committing. NEVER omit --dir. NEVER guess the path.

  # Push entire project to new/existing repo (handles git init, commit, remote, auth)
  $PEXO_PYTHON $PEXO_GITHUB push <repo> --dir {project_path} --msg "Initial commit"
  $PEXO_PYTHON $PEXO_GITHUB push <repo> --dir {project_path} --private  # private repo

  # Commit + push changes
  $PEXO_PYTHON $PEXO_GITHUB commit --msg "Add feature" --dir {project_path}

  # Repo management
  $PEXO_PYTHON $PEXO_GITHUB repo create <name> [--private] [--desc "..."]
  $PEXO_PYTHON $PEXO_GITHUB repo list
  $PEXO_PYTHON $PEXO_GITHUB repo info <name>
  $PEXO_PYTHON $PEXO_GITHUB repo set <name> --desc "..." --topics tag1,tag2

  # Links — always works, just constructs URLs
  $PEXO_PYTHON $PEXO_GITHUB link <repo>                        # repo homepage
  $PEXO_PYTHON $PEXO_GITHUB link <repo> src/index.html         # file on main
  $PEXO_PYTHON $PEXO_GITHUB link <repo> src/index.html --branch dev  # specific branch
  $PEXO_PYTHON $PEXO_GITHUB link <repo> style.css --raw        # raw content URL
  $PEXO_PYTHON $PEXO_GITHUB link <repo> --releases             # releases page

  # File operations via API (no git needed)
  $PEXO_PYTHON $PEXO_GITHUB file get <repo> <path>             # read file from GitHub
  $PEXO_PYTHON $PEXO_GITHUB file put <repo> <path> <local>     # upload/update file
  $PEXO_PYTHON $PEXO_GITHUB file delete <repo> <path>

  # Branches
  $PEXO_PYTHON $PEXO_GITHUB branch list <repo>
  $PEXO_PYTHON $PEXO_GITHUB branch create <repo> <branch> --from main
  $PEXO_PYTHON $PEXO_GITHUB branch delete <repo> <branch>

  # Releases & PRs
  $PEXO_PYTHON $PEXO_GITHUB release create <repo> v1.0.0 --name "Launch" --notes "..."
  $PEXO_PYTHON $PEXO_GITHUB pr create <repo> --title "..." --head feature --base main
  $PEXO_PYTHON $PEXO_GITHUB pr list <repo>

  # Search code
  $PEXO_PYTHON $PEXO_GITHUB search <repo> "function name"

Rules:
- After every push, always share the REPO_URL printed by the tool with the user.
- Use `link` to get file URLs — always share direct links when user asks for them.
- The tool prints FILE_URL and RAW_URL after file uploads — share them.
"""


def _load_claude_md(project_path: str) -> str:
    """Load CLAUDE.md from project root if it exists."""
    for name in ["CLAUDE.md", "claude.md", ".claude.md"]:
        p = Path(project_path) / name
        if p.exists():
            content = p.read_text(errors="replace")[:3000]
            return f"PROJECT INSTRUCTIONS (from CLAUDE.md):\n{content}"
    return ""


def _git_context(project_path: str) -> str:
    """Get current git status, branch, and recent commits."""
    try:
        result = subprocess.run(
            "git branch --show-current && git status --short && git log --oneline -3",
            shell=True, cwd=project_path, capture_output=True, text=True, timeout=5
        )
        out = result.stdout.strip()
        return f"Git context:\n{out}" if out else ""
    except Exception:
        return ""


def _session_recap(history: list, max_actions: int = 15) -> str:
    """Extract a brief recap of recent actions from session history for context continuity."""
    actions = []
    for msg in history:
        if msg.get("role") != "assistant":
            continue
        content = msg.get("content")
        if isinstance(content, str):
            continue
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                name = block.get("name", "")
                inp = block.get("input", {})
                if name == "bash":
                    cmd = inp.get("command", "").split("\n")[0][:100]
                    actions.append(f"  ran: {cmd}")
                elif name == "write_file":
                    mode = inp.get("mode", "write")
                    actions.append(f"  {mode}: {inp.get('path', '')}")
                elif name == "read_file":
                    actions.append(f"  read: {inp.get('path', '')}")
                elif name == "screenshot":
                    actions.append(f"  screenshot: {inp.get('url', '')}")
                elif name in ("deploy_update", "browser_action", "test_flow"):
                    actions.append(f"  {name}: {json.dumps(inp)[:80]}")
    if not actions:
        return ""
    recent = actions[-max_actions:]
    return "SESSION RECAP (recent actions in this session):\n" + "\n".join(recent)


def _project_file_tree(project_path: str, max_depth: int = 2, max_files: int = 50) -> str:
    """Generate a concise file tree of the project for context injection."""
    if not project_path or not os.path.isdir(project_path):
        return "(no project files)"
    skip_dirs = {"node_modules", "__pycache__", "venv", ".venv", ".git", ".next", "dist", "build", ".cache"}
    lines = []
    count = 0
    for root, dirs, files in os.walk(project_path):
        dirs[:] = [d for d in sorted(dirs) if not d.startswith(".") and d not in skip_dirs]
        level = root.replace(project_path, "").count(os.sep)
        if level > max_depth:
            continue
        indent = "  " * level
        dirname = os.path.basename(root) or os.path.basename(project_path)
        lines.append(f"{indent}{dirname}/")
        for f in sorted(files):
            if f.startswith(".") and f not in {".env", ".gitignore"}:
                continue
            lines.append(f"{indent}  {f}")
            count += 1
            if count >= max_files:
                lines.append(f"{indent}  ... (truncated)")
                return "\n".join(lines)
    return "\n".join(lines) if lines else "(empty project)"


def _recent_file_changes(project_path: str, limit: int = 8) -> str:
    """List recently modified files in the project (last 30 min)."""
    if not project_path or not os.path.isdir(project_path):
        return ""
    import time
    skip_dirs = {"node_modules", "__pycache__", "venv", ".venv", ".git"}
    cutoff = time.time() - 1800
    recent = []
    for root, dirs, files in os.walk(project_path):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        for f in files:
            full = os.path.join(root, f)
            try:
                mtime = os.path.getmtime(full)
                if mtime > cutoff:
                    rel = os.path.relpath(full, project_path)
                    recent.append((mtime, rel))
            except OSError:
                pass
    if not recent:
        return ""
    recent.sort(reverse=True)
    lines = ["Recently modified files:"]
    for _, path in recent[:limit]:
        lines.append(f"  - {path}")
    return "\n".join(lines)


def _bulk_agent_context(session_id: str, project_path: str) -> str:
    """Build a multi-agent awareness block for bulk-run sessions."""
    ctx = _session_bulk_ctx.get(session_id)
    if not ctx:
        return ""
    bulk_run_id = ctx["bulk_run_id"]
    spec_name = ctx["spec_name"]
    spec_index = ctx["spec_index"]
    all_specs = ctx.get("all_specs", [])

    peers = [s for s in all_specs if s["index"] != spec_index]
    peer_lines = "\n".join(f"  - #{s['index']} {s['name']}" for s in peers)

    # Files claimed by OTHER agents in this run
    claimed_lines = []
    for (cwd, rel), claim in _bulk_file_claims.items():
        if claim["bulk_run_id"] == bulk_run_id and claim["session_id"] != session_id \
                and cwd == project_path:
            claimed_lines.append(f"  - {rel}  (owned by '{claim['spec_name']}')")
    claimed_block = "\n".join(claimed_lines) if claimed_lines else "  (none yet)"

    return (
        f"\n\nMULTI-AGENT CONTEXT:\n"
        f"You are agent #{spec_index} '{spec_name}' in a {len(all_specs)}-agent parallel bulk run.\n"
        f"Other agents working in parallel on the SAME project:\n{peer_lines or '  (none)'}\n"
        f"\nFiles already written by other agents (DO NOT overwrite with mode='write'):\n{claimed_block}\n"
        f"RULES:\n"
        f"- Each agent owns its own feature area. Work ONLY on your spec.\n"
        f"- If you need to edit a file owned by another agent, use mode='patch' — never mode='write'.\n"
        f"- For shared files (requirements.txt, config.py, .env, README): use mode='patch' or mode='append'.\n"
        f"- Do NOT re-read files that are irrelevant to your spec. Stay focused."
    )


def _build_system_prompt(project_path: str = "", project_name: str = "", history: list = None, current_task: str = "", session_id: str = "") -> str:
    import storage.cloudflare as cf_store
    import storage.servers as srv_store

    lines = []
    cf_token = cf_store.get_token()
    cf_account = cf_store.get_account_id()
    if cf_token:
        lines.append(f"- Cloudflare: CONNECTED (account: {cf_account}). CLOUDFLARE_API_TOKEN in bash env.")
        zones = cf_store.list_zones()
        if zones:
            lines.append(f"  Zones: {', '.join(z['zone_name'] for z in zones[:5])}")
        # Show ALL hostname mappings — critical for conflict avoidance
        hostnames = cf_store.list_all_hostnames()
        if hostnames:
            lines.append("  TAKEN hostnames (DO NOT reuse these subdomains or ports):")
            for h in sorted(hostnames, key=lambda x: x.get("hostname", "")):
                lines.append(f"    https://{h['hostname']} → {h['service_name']} port:{h['port']} server:{h['server_name']}")
        else:
            # Fallback to old domain_map
            domain_map = cf_store.list_domain_map()
            if domain_map:
                lines.append("  TAKEN domain mappings (DO NOT reuse):")
                for dm in domain_map:
                    port_str = str(dm['port']) if dm['port'] else '???'
                    lines.append(f"    https://{dm['hostname']} → {dm['service']} port:{port_str} server:{dm['server']}")
    else:
        lines.append("- Cloudflare: not connected.")

    for s in srv_store.list_all():
        lines.append(f"- SSH Server '{s['name']}': {s['username']}@{s['host']} (auth: {'key' if s.get('auth_type') == 'key' else 'password'})")
        ports = srv_store.list_services_for_server(s['name'])
        if ports:
            port_list = ", ".join(f"{p['service_name']}:{p['port']}" for p in ports)
            lines.append(f"  TAKEN ports: {port_list}")
        # Show next free port
        used = {int(p["port"]) for p in ports if p.get("port")}
        avoid = used | {22, 80, 443, 3306, 5432, 6379, 5000, 8080}
        next_p = 5100
        while next_p in avoid:
            next_p += 1
        lines.append(f"  NEXT FREE PORT: {next_p} — use this for new services on this server")

    wrangler_ok = subprocess.run("which wrangler", shell=True, capture_output=True).returncode == 0
    lines.append(f"- wrangler: {'installed' if wrangler_ok else 'not installed'}")

    import storage.github as gh_store
    gh_token = gh_store.get_token()
    gh_user = gh_store.get_username()
    if gh_token:
        lines.append(f"- GitHub: CONNECTED as @{gh_user}. GITHUB_TOKEN and GITHUB_USERNAME are in your bash environment.")
    else:
        lines.append("- GitHub: not connected. Use /github connect.")

    claude_md = _load_claude_md(project_path) if project_path else ""

    file_tree = _project_file_tree(project_path)
    recent = _recent_file_changes(project_path)
    project_files_section = f"PROJECT FILES (you already have this — do NOT call list_directory):\n{file_tree}"
    if recent:
        project_files_section += f"\n\n{recent}"

    recap = _session_recap(history or [])

    task_display = current_task[:2000] if current_task else "(awaiting user instruction)"

    base = SYSTEM_PROMPT_BASE.format(
        current_task=task_display,
        project_name=project_name or os.path.basename(project_path) or "unknown",
        project_path=project_path or "(not set)",
        project_files=project_files_section,
        session_recap=recap,
        infra_context="\n".join(lines) or "None configured.",
        claude_md=claude_md,
    )

    # Append multi-agent context for bulk-run sessions
    if session_id:
        bulk_ctx_block = _bulk_agent_context(session_id, project_path)
        if bulk_ctx_block:
            base += bulk_ctx_block

    return base


# ── Tool execution ─────────────────────────────────────────────────────────────

def _get_infra_env() -> dict:
    import storage.cloudflare as cf_store
    env = {**os.environ}
    token = cf_store.get_token()
    account = cf_store.get_account_id()
    if token:
        env["CLOUDFLARE_API_TOKEN"] = token
    if account:
        env["CLOUDFLARE_ACCOUNT_ID"] = account
    # Inject pexo-ssh path so Claude can call it via bash
    pexo_ssh = str(Path(__file__).parent.parent / "tools" / "pexo_ssh.py")
    env["PEXO_SSH"] = pexo_ssh
    env["PEXO_PYTHON"] = sys.executable
    pexo_github = str(Path(__file__).parent.parent / "tools" / "pexo_github.py")
    env["PEXO_GITHUB"] = pexo_github
    env["PEXO_TUNNEL"] = str(Path(__file__).parent.parent / "tools" / "pexo_tunnel.py")

    # GitHub credentials
    import storage.github as gh_store
    gh_token = gh_store.get_token()
    gh_user = gh_store.get_username()
    if gh_token:
        env["GITHUB_TOKEN"] = gh_token
        env["GITHUB_USERNAME"] = gh_user or ""
        # Configure git to use token for HTTPS pushes (no password prompt)
        env["GIT_ASKPASS"] = "echo"
        env["GIT_USERNAME"] = gh_user or ""
        env["GIT_PASSWORD"] = gh_token

    return env


_DEBUG_SNIPPET = '''<script data-pexo-debug>
(function(){
  window.__PEXO_ERRORS__=[];
  window.onerror=function(m,s,l,c,e){window.__PEXO_ERRORS__.push({type:'error',msg:m,src:s,line:l,col:c});console.error('[PEXO]',m,s+':'+l);};
  window.addEventListener('unhandledrejection',function(e){window.__PEXO_ERRORS__.push({type:'promise',msg:String(e.reason)});console.error('[PEXO] Unhandled:',e.reason);});
  var _ce=console.error;console.error=function(){_ce.apply(console,arguments);window.__PEXO_ERRORS__.push({type:'console.error',msg:Array.from(arguments).join(' ')});};
})();
</script>'''


def _inject_debug_snippet(filepath: str) -> bool:
    """Inject error-capture script into HTML files. Returns True if injected."""
    if not filepath.endswith(".html"):
        return False
    try:
        content = open(filepath, errors="replace").read()
        if "data-pexo-debug" in content:
            return False
        # Inject right after <head> or at start of <body> or at top of file
        if "<head>" in content:
            content = content.replace("<head>", "<head>\n" + _DEBUG_SNIPPET, 1)
        elif "<head " in content:
            idx = content.index("<head ")
            end = content.index(">", idx)
            content = content[:end+1] + "\n" + _DEBUG_SNIPPET + content[end+1:]
        elif "<body" in content:
            idx = content.index("<body")
            end = content.index(">", idx)
            content = content[:end+1] + "\n" + _DEBUG_SNIPPET + content[end+1:]
        elif "<!DOCTYPE" in content or "<html" in content:
            content = _DEBUG_SNIPPET + "\n" + content
        else:
            content = _DEBUG_SNIPPET + "\n" + content
        open(filepath, "w").write(content)
        return True
    except Exception:
        return False


def _run_tool(name: str, inputs: dict, cwd: str, shell: PersistentShell,
              session_id: str = "") -> str:
    if name == "bash":
        cmd = inputs.get("command") or inputs.get("cmd", "")
        timeout = inputs.get("timeout") or CMD_TIMEOUT
        result = shell.run(cmd, timeout=timeout, extra_env=_get_infra_env())
        return truncate(result, 3000)

    elif name == "read_file":
        try:
            full = safe_relative(cwd, inputs["path"])
            return truncate(open(full, errors="replace").read(), 6000)
        except Exception as e:
            return f"[read error: {e}]"

    elif name == "write_file":
        try:
            full = safe_relative(cwd, inputs["path"])
            os.makedirs(os.path.dirname(full), exist_ok=True)
            mode = inputs.get("mode", "write")
            file_path_lower = inputs.get("path", "").lower()
            rel_path = inputs.get("path", "")

            # ── Multi-agent conflict detection ──────────────────────────────
            # If this session is part of a bulk run, check whether another agent
            # in the same run has already written this file.  A full "write"
            # (mode="write") would silently destroy the other agent's work, so
            # we block it and ask Claude to use patch mode instead.
            if session_id and mode == "write":
                bulk_ctx = _session_bulk_ctx.get(session_id)
                if bulk_ctx:
                    claim_key = (cwd, rel_path)
                    existing = _bulk_file_claims.get(claim_key)
                    if existing and existing["session_id"] != session_id \
                            and existing["bulk_run_id"] == bulk_ctx["bulk_run_id"]:
                        return (
                            f"⚠️ MULTI-AGENT CONFLICT: `{rel_path}` was already written "
                            f"by agent '{existing['spec_name']}' in this bulk run.\n"
                            f"To avoid destroying their work:\n"
                            f"1. Call read_file('{rel_path}') to get the CURRENT version\n"
                            f"2. Use write_file mode='patch' with old_str/new_str to add ONLY your changes\n"
                            f"   OR use mode='append' if adding new content to the end.\n"
                            f"Do NOT overwrite — merge your additions instead."
                        )

            # Detect truncated content from API proxy
            content_raw = inputs.get("content", "")
            if mode in ("write", "append") and not content_raw:
                return (
                    "[write_file FAILED: content was empty — likely truncated by the API. "
                    "The file was too large for a single call. "
                    "Split it: use mode='write' with the first ~3500 chars, "
                    "then mode='append' for the rest. Keep each call under 4000 chars.]"
                )

            if mode == "append":
                content = inputs.get("content", "")
                with open(full, "a") as f:
                    f.write(content)
                total = os.path.getsize(full)
                return f"Appended {len(content)} bytes to {inputs['path']} (total: {total} bytes)"

            elif mode == "patch":
                old_str = inputs.get("old_str", "")
                new_str = inputs.get("new_str", "")
                if not old_str:
                    return "[patch error: old_str is required]"
                existing = open(full, errors="replace").read()
                count = existing.count(old_str)
                if count == 0:
                    # Try stripped match for whitespace tolerance
                    lines = existing.split("\n")
                    old_lines = old_str.split("\n")
                    old_stripped = [l.strip() for l in old_lines]
                    match_start = -1
                    for i in range(len(lines) - len(old_lines) + 1):
                        if [l.strip() for l in lines[i:i+len(old_lines)]] == old_stripped:
                            match_start = i
                            break
                    if match_start >= 0:
                        lines[match_start:match_start+len(old_lines)] = new_str.split("\n")
                        open(full, "w").write("\n".join(lines))
                        return f"Patched {inputs['path']} (fuzzy match at line {match_start+1})"
                    return f"[patch error: old_str not found in {inputs['path']}]"
                if count > 1:
                    existing = existing.replace(old_str, new_str, 1)
                    open(full, "w").write(existing)
                    if file_path_lower.endswith(".html"):
                        _inject_debug_snippet(full)
                    return f"Patched first occurrence in {inputs['path']} ({count} total matches)"
                existing = existing.replace(old_str, new_str)
                open(full, "w").write(existing)
                if file_path_lower.endswith(".html"):
                    _inject_debug_snippet(full)
                return f"Patched {inputs['path']}"

            else:
                content = inputs.get("content", "")
                open(full, "w").write(content)
                result_msg = f"Written {len(content)} bytes to {inputs['path']}"
                if file_path_lower.endswith(".html") and _inject_debug_snippet(full):
                    result_msg += " (debug instrumentation auto-injected)"
                # Register this file as claimed by this session in the bulk run
                if session_id:
                    bulk_ctx = _session_bulk_ctx.get(session_id)
                    if bulk_ctx:
                        _bulk_file_claims[(cwd, rel_path)] = {
                            "session_id": session_id,
                            "spec_name": bulk_ctx["spec_name"],
                            "bulk_run_id": bulk_ctx["bulk_run_id"],
                        }
                return result_msg
        except Exception as e:
            return f"[write error: {e}]"

    elif name == "list_directory":
        try:
            target = safe_relative(cwd, inputs.get("path") or ".")
            depth = inputs.get("depth", 2)
            lines = []
            for root, dirs, files in os.walk(target):
                dirs[:] = [d for d in sorted(dirs) if not d.startswith(".") and d not in {"node_modules", "__pycache__", "venv", ".git"}]
                level = root.replace(target, "").count(os.sep)
                if level > depth:
                    continue
                lines.append(f"{'  ' * level}{os.path.basename(root)}/")
                for f in sorted(files):
                    lines.append(f"{'  ' * level}  {f}")
            return "\n".join(lines[:200]) or "(empty)"
        except Exception as e:
            return f"[list error: {e}]"

    elif name == "search_files":
        query = json.dumps(inputs["query"])
        pat = inputs.get("file_pattern", "")
        inc = f"--include='{pat}'" if pat else ""
        cmd = f"grep -rn {inc} --color=never {query} . 2>/dev/null | head -30"
        return shell.run(cmd)

    elif name == "fetch_url":
        try:
            url = inputs["url"]
            method = inputs.get("method", "GET").upper()
            body = inputs.get("body")
            with httpx.Client(timeout=15, follow_redirects=True) as c:
                r = c.request(method, url, content=body)
            text = r.text[:4000]
            return f"[{r.status_code}] {text}"
        except Exception as e:
            return f"[fetch error: {e}]"

    return f"[unknown tool: {name}]"


async def _run_send_file(inputs: dict, project_path: str, channel_id: str) -> str:
    from utils.discord_helpers import send_file
    from utils.security import safe_relative
    import mimetypes

    if not channel_id:
        return "[send_file: no channel_id available]"

    path = inputs.get("path", "")
    caption = inputs.get("caption", "")
    filename_override = inputs.get("filename", "")

    if not path:
        return "[send_file: path is required]"

    try:
        full = safe_relative(project_path, path)
        file_bytes = open(full, "rb").read()
        fname = filename_override or os.path.basename(full)
        mime, _ = mimetypes.guess_type(fname)
        content_type = mime or "application/octet-stream"
        size_kb = len(file_bytes) / 1024

        await send_file(channel_id, file_bytes, fname, caption=caption, content_type=content_type)
        return f"File '{fname}' ({size_kb:.1f} KB) sent to Discord."
    except Exception as e:
        return f"[send_file error: {e}]"


async def _run_send_image(inputs: dict, project_path: str, channel_id: str) -> str:
    from utils.discord_helpers import send_image_to_channel
    caption = inputs.get("caption", "")
    path = inputs.get("path", "")
    url = inputs.get("url", "")

    if not channel_id:
        return "[send_image: no channel_id available]"

    try:
        if path:
            from utils.security import safe_relative
            import mimetypes
            full = safe_relative(project_path, path)
            img = open(full, "rb").read()
            fname = os.path.basename(full)
        elif url:
            async with httpx.AsyncClient(timeout=20, follow_redirects=True) as c:
                r = await c.get(url)
            img = r.content
            fname = url.split("/")[-1].split("?")[0] or "image.png"
            if "." not in fname:
                fname += ".png"
        else:
            return "[send_image: provide either path or url]"

        await send_image_to_channel(channel_id, img, fname, caption)
        return f"Image '{fname}' sent to Discord."
    except Exception as e:
        return f"[send_image error: {e}]"


async def _run_screenshot(inputs: dict, project_path: str, channel_id: str) -> str:
    """Kill stale servers, start fresh dev server, screenshot, send to Discord."""
    import layers.browser_layer as browser
    from utils.discord_helpers import send_image_to_channel
    import subprocess as _sp

    url = inputs.get("url")
    mobile = inputs.get("mobile", False)
    caption = inputs.get("caption", "📸 Screenshot")

    try:
        if not url:
            # Always start/reuse via start_server — it tracks _dev_project and reuses
            # if the same project server is already running. Don't rely on port checks
            # (false positives from other processes cause blank screenshots).
            url = await browser.start_server(project_path)
            print(f"[screenshot] server at {url}")

        print(f"[screenshot] navigating to {url}")
        if mobile:
            img = await browser.screenshot_mobile(url)
        else:
            img = await browser.screenshot(url)

        print(f"[screenshot] got {len(img)} bytes")
        if channel_id:
            await send_image_to_channel(channel_id, img, "screenshot.png", caption)

        # Auto-capture console logs so Claude sees errors immediately
        await asyncio.sleep(0.5)
        console = browser.format_console_logs(browser.get_console_logs(clear=False))
        error_lines = []
        warn_lines = []
        if console and console != "(no console output)":
            for line in console.split("\n"):
                ll = line.lower()
                if "error" in ll or "uncaught" in ll or "failed" in ll:
                    error_lines.append(line)
                elif "warn" in ll:
                    warn_lines.append(line)

        result_text = f"Screenshot taken and sent to Discord. URL: {url}"
        if error_lines:
            result_text += f"\n\n⚠️ CONSOLE ERRORS DETECTED ({len(error_lines)}):\n" + "\n".join(error_lines[:10])
            result_text += "\n\n→ You MUST fix these errors before proceeding."
        if warn_lines:
            result_text += f"\n\nWarnings ({len(warn_lines)}):\n" + "\n".join(warn_lines[:5])
        if not error_lines and not warn_lines and console and console != "(no console output)":
            result_text += f"\n\nConsole output (clean):\n{console[:500]}"
        elif not error_lines and not warn_lines:
            result_text += "\n\n✅ No console errors."

        # Run page health audit to detect hidden issues
        try:
            audit = await browser.audit_page()
            audit_text = browser.format_audit(audit)
            result_text += f"\n\n--- PAGE AUDIT ---\n{audit_text}"
        except Exception as ae:
            print(f"[screenshot] audit error: {ae}")

        return result_text
    except Exception as e:
        import traceback
        print(f"[screenshot error] {e}\n{traceback.format_exc()}")
        return (
            f"[screenshot failed: {e}]\n\n"
            "→ The server did not start or crashed. Fix the error above, then call screenshot again.\n"
            "→ Common causes: missing import, wrong port, dependencies not installed, syntax error in app.py."
        )


async def _run_browser_console(inputs: dict) -> str:
    import layers.browser_layer as browser
    clear = inputs.get("clear", False)
    logs = browser.get_console_logs(clear=clear)
    if not logs:
        return "(no console logs captured — take a screenshot first to start capturing)"
    return browser.format_console_logs(logs)


async def _run_browser_action(inputs: dict, project_path: str, channel_id: str) -> str:
    import layers.browser_layer as browser
    from utils.discord_helpers import send_image_to_channel

    action = inputs.get("action", "")
    selector = inputs.get("selector", "")
    value = inputs.get("value", "")

    try:
        if action == "click":
            img = await browser.click(selector)
        elif action == "fill":
            img = await browser.fill_input(selector, value)
        elif action == "type":
            img = await browser.type_text(selector, value)
        elif action == "select":
            img = await browser.select_option(selector, value)
        elif action == "upload":
            from utils.security import safe_relative
            full = safe_relative(project_path, value)
            img = await browser.upload_file(selector, full)
        elif action == "press":
            img = await browser.press_key(value or selector)
        elif action == "scroll":
            pixels = inputs.get("pixels", 500)
            img = await browser.scroll(pixels)
        elif action == "navigate":
            url = inputs.get("url", value)
            img = await browser.navigate(url)
        elif action == "wait":
            await asyncio.sleep(float(value) if value else 2)
            page = await browser._ensure_browser()
            img = await page.screenshot()
        elif action == "evaluate_js":
            result = await browser.evaluate_js(value or selector)
            return f"JS result: {result}"
        else:
            return f"[unknown action: {action}]"

        if channel_id and img:
            await send_image_to_channel(channel_id, img, f"action_{action}.png", f"🖱️ {action}: {selector or value}")

        # Capture console state after the action
        await asyncio.sleep(0.3)
        console = browser.format_console_logs(browser.get_console_logs(clear=False))
        error_lines = []
        if console and console != "(no console output)":
            for line in console.split("\n"):
                ll = line.lower()
                if "error" in ll or "uncaught" in ll or "failed" in ll or "[pexo]" in ll:
                    error_lines.append(line)

        result_text = f"Action '{action}' on '{selector or value}' completed."
        if img:
            result_text += " Screenshot sent to Discord."
        if error_lines:
            result_text += f"\n\n⚠️ ERRORS AFTER ACTION ({len(error_lines)}):\n" + "\n".join(error_lines[:8])
            result_text += "\n\n→ Fix these errors before continuing."
        else:
            result_text += "\n✅ No console errors."

        # Run page health audit to catch dead elements, broken images, etc.
        try:
            audit = await browser.audit_page()
            audit_text = browser.format_audit(audit)
            result_text += f"\n\n--- PAGE AUDIT ---\n{audit_text}"
        except Exception:
            pass

        return result_text

    except Exception as e:
        return f"[browser_action error: {e}]"


async def _run_test_flow(inputs: dict, project_path: str, channel_id: str) -> str:
    import layers.browser_layer as browser
    from utils.discord_helpers import send_image_to_channel

    steps = inputs.get("steps", [])
    url = inputs.get("url")
    record = inputs.get("record", True)

    if not steps:
        return "[test_flow: no steps provided]"

    try:
        if not url:
            # Reuse running Flask app if detected, else start server
            import socket as _sock
            flask_info = browser._detect_flask_app(__import__("pathlib").Path(project_path))
            flask_port = flask_info[2] if flask_info else None
            if flask_port:
                try:
                    s = _sock.create_connection(("localhost", flask_port), timeout=0.5)
                    s.close()
                    url = f"http://localhost:{flask_port}"
                except OSError:
                    pass
            if not url:
                url = await browser.start_server(project_path)

        # Per-step screenshot sender
        async def send_step(img: bytes, caption: str):
            if channel_id:
                try:
                    await send_image_to_channel(channel_id, img, "step.png", caption)
                except Exception:
                    pass

        result = await browser.run_test_flow(
            url=url, steps=steps, record=record,
            send_step_screenshots=send_step,
        )

        # Send video if recorded and non-empty
        if result.get("video_path") and channel_id:
            try:
                video_data = open(result["video_path"], "rb").read()
                if len(video_data) > 1000:  # skip empty/stub files
                    await send_image_to_channel(channel_id, video_data, "test.webm", "🎥 Test recording")
                else:
                    print(f"[test_flow] video too small ({len(video_data)} bytes), skipping")
            except Exception as ve:
                print(f"[test_flow] video send error: {ve}")

        passed = result["passed"]
        failed = result["failed"]
        total = passed + failed
        parts = [f"{'✅' if failed == 0 else '⚠️'} Test flow: {passed}/{total} steps passed, {failed} failed."]

        # Per-step summary
        step_results = result.get("step_results", [])
        if step_results:
            parts.append("\nStep-by-step results:")
            for r in step_results:
                icon = "✅" if r["ok"] else "❌"
                url_note = f" → {r['url_after']}" if r.get("url_changed") else ""
                err_note = f" | {r['error']}" if r.get("error") else ""
                console_note = f" | {len(r['console_errors'])} console err(s)" if r.get("console_errors") else ""
                parts.append(f"  {icon} [{r['step']}] {r['desc']}{url_note}{err_note}{console_note}")

        if failed > 0:
            parts.append("\n→ You MUST fix these failures before proceeding.")

        # Console error summary
        console = result.get("console_logs", "")
        if console and console != "(no console output)":
            error_lines = [l for l in console.split("\n") if any(k in l.lower() for k in ("error", "uncaught", "failed", "[pexo]"))]
            if error_lines:
                parts.append(f"\n⚠️ CONSOLE ERRORS ({len(error_lines)}):")
                parts.extend(error_lines[:8])
            else:
                parts.append("\n✅ Console clean.")
        else:
            parts.append("\n✅ No console output.")

        # Page audit on final state
        try:
            audit = await browser.audit_page()
            audit_text = browser.format_audit(audit)
            parts.append(f"\n--- PAGE AUDIT ---\n{audit_text}")
        except Exception:
            pass

        return "\n".join(parts)

    except Exception as e:
        import traceback
        print(f"[test_flow error] {e}\n{traceback.format_exc()}")
        return f"[test_flow error: {e}]"


async def _run_deploy_update(inputs: dict) -> str:
    import layers.ssh_layer as ssh
    import storage.servers as srv_store

    service_name = inputs.get("service_name", "")
    server_alias = inputs.get("server", "")
    branch = inputs.get("branch", "main")
    start_cmd = inputs.get("start_cmd")

    if not service_name:
        return "[deploy_update: service_name is required]"

    server = srv_store.get(server_alias) if server_alias else srv_store.get_default()
    if not server:
        return "[deploy_update: no server configured]"

    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, lambda: ssh.update_service(
            server=server, service_name=service_name,
            branch=branch, start_cmd=start_cmd,
        ))

        text = "\n".join(result["steps"])
        if result["healthy"]:
            srv_store.record_deploy(
                project_name=service_name, server_name=server["name"],
                service_name=service_name, port=result.get("port", 0),
                deploy_type="update", status="healthy",
                url=f"http://{server['host']}:{result.get('port', 0)}",
            )
        return text
    except Exception as e:
        return f"[deploy_update error: {e}]"


async def _run_list_projects() -> str:
    import storage.projects as proj_store
    projects = proj_store.list_all()
    if not projects:
        return "(no projects registered — use /project add to create one)"
    lines = []
    for p in projects:
        branch = p.get("git_branch", "")
        channel = p.get("active_channel", "")
        line = f"• {p['name']} — {p['path']}"
        if branch:
            line += f" (branch: {branch})"
        if channel:
            line += f" [active in channel {channel}]"
        lines.append(line)
    return "Registered projects:\n" + "\n".join(lines)


async def _run_list_deployments(inputs: dict) -> str:
    import storage.servers as srv_store
    server_filter = inputs.get("server", "")
    deploys = srv_store.list_deploys()
    if not deploys:
        return "(no deployments recorded)"
    if server_filter:
        deploys = [d for d in deploys if d.get("server_name") == server_filter]
        if not deploys:
            return f"(no deployments on server '{server_filter}')"
    lines = []
    for d in deploys[-15:]:
        status_icon = {"healthy": "✅", "unhealthy": "❌", "partial": "⚠️"}.get(d.get("status", ""), "❓")
        line = (
            f"{status_icon} {d['service_name']} — "
            f"server: {d.get('server_name', '?')} — "
            f"port: {d.get('port', '?')} — "
            f"type: {d.get('deploy_type', '?')} — "
            f"{d.get('url', '')}"
        )
        if d.get("created_at"):
            line += f" — {d['created_at'][:16]}"
        lines.append(line)
    return "Deployments (most recent last):\n" + "\n".join(lines)


async def _run_service_health(inputs: dict) -> str:
    import layers.ssh_layer as ssh
    import storage.servers as srv_store

    service_name = inputs.get("service_name", "")
    server_alias = inputs.get("server", "")
    if not service_name:
        return "[service_health: service_name is required]"

    server = srv_store.get(server_alias) if server_alias else srv_store.get_default()
    if not server:
        return "[service_health: no server configured]"

    try:
        loop = asyncio.get_event_loop()
        status = await loop.run_in_executor(None, lambda: ssh.get_service_status(server, service_name))
        icon = "✅" if status["active"] else "❌"
        parts = [
            f"{icon} {service_name} — {status['state']} ({status['sub_state']})",
        ]
        if status["pid"]:
            parts.append(f"PID: {status['pid']}")
        if status["memory"]:
            parts.append(f"Memory: {status['memory']}")
        if status["started_at"]:
            parts.append(f"Started: {status['started_at']}")
        if status["recent_logs"]:
            logs = status["recent_logs"][:1500]
            parts.append(f"\nRecent logs:\n{logs}")
        return "\n".join(parts)
    except Exception as e:
        return f"[service_health error: {e}]"


async def _run_allocate_port(inputs: dict) -> str:
    import storage.servers as srv_store
    service_name = inputs.get("service_name", "")
    server_name = inputs.get("server_name", "")
    if not service_name:
        return "[allocate_port: service_name required]"
    if not server_name:
        srv = srv_store.get_default()
        server_name = srv["name"] if srv else "default"
    port = srv_store.allocate_port(server_name, service_name)
    return f"Allocated port {port} for service '{service_name}' on server '{server_name}'. This port is now reserved — use it when starting the service."


async def _run_free_port(inputs: dict) -> str:
    import storage.servers as srv_store
    service_name = inputs.get("service_name", "")
    server_name = inputs.get("server_name", "")
    if not service_name:
        return "[free_port: service_name required]"
    if not server_name:
        srv = srv_store.get_default()
        server_name = srv["name"] if srv else "default"
    srv_store.free_port(server_name, service_name)
    return f"Port for service '{service_name}' on server '{server_name}' has been released."


async def _run_list_infrastructure(inputs: dict) -> str:
    import storage.servers as srv_store
    import storage.cloudflare as cf_store
    import socket as _socket

    server_filter = inputs.get("server", "")

    def _port_open_local(port: int) -> bool:
        try:
            s = _socket.create_connection(("localhost", port), timeout=0.3)
            s.close()
            return True
        except OSError:
            return False

    parts = ["# Infrastructure Map\n"]

    # ── Servers & ports ────────────────────────────────────────────────────────
    servers = srv_store.list_all()
    if server_filter:
        servers = [s for s in servers if s["name"] == server_filter]
    if not servers:
        parts.append("No servers configured.\n")

    for srv in servers:
        parts.append(f"## Server: {srv['name']} ({srv['username']}@{srv['host']})")

        services = srv_store.list_services_for_server(srv["name"])
        used_ports = {int(s["port"]) for s in services if s.get("port")}

        if services:
            parts.append("  Registered services & ports:")
            for svc in sorted(services, key=lambda x: int(x.get("port", 0))):
                parts.append(f"    port {svc['port']:>5} → {svc['service_name']}")
        else:
            parts.append("  No registered services yet.")

        # Try live port check via SSH
        try:
            import layers.ssh_layer as ssh
            out, _, code = await asyncio.get_event_loop().run_in_executor(
                None, lambda s=srv: ssh.run(s, "ss -tlnp 2>/dev/null | awk 'NR>1 {print $4}' | grep -oP '(?<=:)\\d+' | sort -n | uniq")
            )
            if code == 0 and out.strip():
                live_ports = set(int(p) for p in out.strip().split() if p.isdigit())
                unregistered = live_ports - used_ports - {22, 80, 443}
                if unregistered:
                    parts.append(f"  ⚠️  Live but UNREGISTERED ports: {sorted(unregistered)}")
                    parts.append("     (These ports are in use but not tracked — call list_infrastructure to see them)")
        except Exception:
            pass

        # Next free port
        avoid = used_ports | {22, 80, 443, 3306, 5432, 6379, 5000, 8080}
        p = 5100
        while p in avoid:
            p += 1
        next_port = p
        parts.append(f"  ✅ Next free port: {next_port}")
        parts.append("")

    # ── Domain / hostname mappings ─────────────────────────────────────────────
    hostnames = cf_store.list_all_hostnames()
    if hostnames:
        parts.append("## Hostname → Service → Port Mappings (DO NOT reuse these)")
        for h in sorted(hostnames, key=lambda x: x.get("hostname", "")):
            parts.append(
                f"  https://{h['hostname']} → {h['service_name']} "
                f"(port:{h['port']}, server:{h['server_name']})"
            )
    else:
        # Fallback to old domain_map for backwards compatibility
        domain_map = cf_store.list_domain_map()
        if domain_map:
            parts.append("## Domain → Service → Port Mappings (DO NOT reuse these)")
            for dm in domain_map:
                port_str = str(dm['port']) if dm['port'] else '???'
                parts.append(
                    f"  https://{dm['hostname']} → {dm['service']} "
                    f"(server: {dm['server']}, port: {port_str})"
                )
        else:
            parts.append("## Domains: No hostname mappings configured yet.")

    # ── Tunnels ───────────────────────────────────────────────────────────────
    tunnels = cf_store.list_tunnels()
    if tunnels:
        parts.append("\n## Tunnels")
        for t in tunnels:
            t_hostnames = cf_store.list_hostnames_for_tunnel(t["tunnel_id"])
            route_summary = ", ".join(h["hostname"] for h in t_hostnames) or "no hostnames yet"
            parts.append(
                f"  {t['tunnel_name']} (id:{t['tunnel_id'][:8]}...) "
                f"→ server:{t['server_name']} | routes: {route_summary}"
            )

    # ── Cloudflare Pages ──────────────────────────────────────────────────────
    # (No list_pages in storage yet, skip)

    # ── Deploy history ────────────────────────────────────────────────────────
    deploys = srv_store.list_deploys()
    if deploys:
        parts.append("\n## Recent Deployments")
        for d in deploys[-8:]:
            parts.append(
                f"  {d['service_name']} | server:{d.get('server_name','?')} "
                f"| port:{d.get('port','?')} | {d.get('status','?')} | {d.get('url','')} | {d.get('created_at','')[:16]}"
            )

    parts.append(
        "\n⚠️  RULES — read before acting:\n"
        "  1. NEVER use a port already listed above\n"
        "  2. NEVER attach a hostname already listed above to a different service\n"
        "  3. Use the 'Next free port' shown above when deploying a new service\n"
        "  4. Register every new port with: save_service_port(server_name, service_name, port)\n"
        "     (or it won't appear here next time)"
    )
    return "\n".join(parts)


class TurnLimitReached(Exception):
    def __init__(self, partial_result: str):
        self.partial_result = partial_result
        super().__init__("Turn limit reached")


# ── Context compaction ─────────────────────────────────────────────────────────

async def _compact_history(client, messages: list, system: str) -> list:
    """Summarize old messages when context gets too large."""
    history_size = sum(len(json.dumps(m)) for m in messages)
    if history_size < COMPACTION_THRESHOLD:
        return messages

    keep = messages[-8:]
    to_summarize = messages[:-8]
    if not to_summarize:
        return messages

    summary_prompt = (
        "Summarize this conversation history. You MUST preserve:\n"
        "1. The original user request/task\n"
        "2. ALL files created, modified, or deleted (with paths)\n"
        "3. ALL commands run and their outcomes\n"
        "4. Current project state and any errors encountered\n"
        "5. What has been completed vs what remains\n"
        "6. Any deployment details (ports, domains, services)\n"
        "Be concise but comprehensive. This summary will be used to continue the session.\n\n"
        + json.dumps(to_summarize)[:12000]
    )

    def _call():
        return client.messages.create(
            model=MODEL, max_tokens=1500,
            messages=[{"role": "user", "content": summary_prompt}],
        )

    try:
        resp = await asyncio.wait_for(
            asyncio.get_event_loop().run_in_executor(None, _call),
            timeout=60.0,
        )
        summary = resp.content[0].text
        compacted = [{"role": "user", "content": f"[Previous session summary]: {summary}"},
                     {"role": "assistant", "content": "Understood. I have the full context of what was done and what remains. Continuing from that point."}]
        return compacted + keep
    except Exception:
        return messages


async def _generate_task_summary(client, messages: list, original_prompt: str, session_id: str) -> dict:
    """Generate a structured summary of what was done vs what was requested.
    Returns {summary, requested, completed, remaining} and persists it."""
    recent_actions = []
    for msg in messages[-20:]:
        if msg.get("role") != "assistant":
            continue
        content = msg.get("content")
        if isinstance(content, str) and content.strip():
            recent_actions.append(f"[text] {content[:200]}")
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    name = block.get("name", "")
                    inp = block.get("input", {})
                    if name == "bash":
                        recent_actions.append(f"[bash] {inp.get('command', '')[:100]}")
                    elif name == "write_file":
                        recent_actions.append(f"[write] {inp.get('path', '')} ({inp.get('mode', 'write')})")
                    elif name == "read_file":
                        recent_actions.append(f"[read] {inp.get('path', '')}")
                    else:
                        recent_actions.append(f"[{name}] {json.dumps(inp)[:80]}")

    prompt = (
        "Analyze this task execution and generate a structured summary.\n\n"
        f"ORIGINAL REQUEST: {original_prompt[:500]}\n\n"
        f"ACTIONS TAKEN (most recent):\n" + "\n".join(recent_actions[-15:]) + "\n\n"
        "Respond in EXACTLY this format (no markdown, no extra text):\n"
        "REQUESTED: <1-2 sentence summary of what was asked>\n"
        "COMPLETED: <bullet list of what was accomplished>\n"
        "REMAINING: <bullet list of what still needs to be done, or 'Nothing - task complete'>\n"
        "SUMMARY: <2-3 sentence overall summary for context continuity>"
    )

    def _call():
        return client.messages.create(
            model=MODEL, max_tokens=800,
            messages=[{"role": "user", "content": prompt}],
        )

    try:
        resp = await asyncio.wait_for(
            asyncio.get_event_loop().run_in_executor(None, _call),
            timeout=45.0,
        )
        text = resp.content[0].text
        result = {"summary": text, "requested": "", "completed": "", "remaining": ""}
        for line in text.split("\n"):
            if line.startswith("REQUESTED:"):
                result["requested"] = line[10:].strip()
            elif line.startswith("COMPLETED:"):
                result["completed"] = line[10:].strip()
            elif line.startswith("REMAINING:"):
                result["remaining"] = line[10:].strip()
            elif line.startswith("SUMMARY:"):
                result["summary"] = line[8:].strip()

        sessions_store.save_task_summary(
            session_id, result["summary"],
            result["requested"], result["completed"], result["remaining"]
        )
        return result
    except Exception as e:
        print(f"[task_summary] generation failed: {e}")
        return {"summary": "", "requested": original_prompt[:200], "completed": "", "remaining": "unknown"}


# ── Progress formatting ────────────────────────────────────────────────────────

def _format_tool_progress(name: str, inp: dict) -> str:
    if name == "bash":
        display = inp.get("command", "").replace("\n", " ").strip()
        if len(display) > 120:
            display = display[:117] + "..."
        return f"```\n$ {display}\n```"
    elif name == "read_file":
        return f"📖 Reading `{inp.get('path', '')}`"
    elif name == "write_file":
        mode = inp.get("mode", "write")
        path = inp.get("path", "")
        if mode == "append":
            return f"📎 Appending to `{path}` ({len(inp.get('content', ''))} bytes)"
        elif mode == "patch":
            return f"🩹 Patching `{path}`"
        return f"✏️ Writing `{path}` ({len(inp.get('content', ''))} bytes)"
    elif name == "list_directory":
        return f"📂 Listing `{inp.get('path', '.') or '.'}`"
    elif name == "search_files":
        return f"🔍 Searching `{inp.get('query', '')}`"
    elif name == "fetch_url":
        return f"🌐 Fetching `{inp.get('url', '')}`"
    elif name == "send_file":
        return f"📎 Sending file `{inp.get('path', '')}`"
    elif name == "send_image":
        src = inp.get("path") or inp.get("url") or "image"
        return f"🖼️ Sending image `{src}`"
    elif name == "screenshot":
        return f"📸 Taking screenshot..."
    elif name == "browser_console":
        return f"🖥️ Reading browser console logs..."
    elif name == "browser_action":
        return f"🖱️ Browser: {inp.get('action', '')} `{inp.get('selector', '')}`"
    elif name == "test_flow":
        steps = inp.get("steps", [])
        return f"🧪 Running test flow ({len(steps)} steps)..."
    elif name == "deploy_update":
        return f"🔄 Updating service `{inp.get('service_name', '')}`..."
    elif name == "list_projects":
        return f"📋 Listing projects..."
    elif name == "list_deployments":
        return f"📋 Listing deployments..."
    elif name == "service_health":
        return f"🏥 Checking health of `{inp.get('service_name', '')}`..."
    elif name == "allocate_port":
        return f"🔢 Allocating port for `{inp.get('service_name', '')}`..."
    elif name == "free_port":
        return f"🔓 Releasing port for `{inp.get('service_name', '')}`..."
    elif name == "list_infrastructure":
        return f"🗺️ Loading infrastructure map..."
    return f"🔧 {name}"


# ── Main agent loop ────────────────────────────────────────────────────────────

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
    base_url = os.getenv("ANTHROPIC_BASE_URL")
    client = anthropic.Anthropic(
        api_key=os.getenv("ANTHROPIC_API_KEY"),
        timeout=180.0,
        **({"base_url": base_url} if base_url else {}),
    )

    # Persistent shell for this session (lock prevents duplicate creation on concurrent calls)
    import threading as _threading
    _shells_lock = getattr(run, "_shells_lock", None)
    if _shells_lock is None:
        _shells_lock = _threading.Lock()
        run._shells_lock = _shells_lock
    with _shells_lock:
        if session_id not in _shells:
            _shells[session_id] = PersistentShell(project_path, session_id)
        shell = _shells[session_id]

    # Build user message — support image attachments
    if image_data:
        import base64, io
        # Compress image to max 800KB before sending to avoid API context limits
        try:
            from PIL import Image
            pil = Image.open(io.BytesIO(image_data))
            pil.thumbnail((1024, 1024))
            buf = io.BytesIO()
            fmt = "JPEG" if image_media_type != "image/png" else "PNG"
            pil.save(buf, format=fmt, quality=82, optimize=True)
            compressed = buf.getvalue()
            # Only use compressed if it's smaller
            if len(compressed) < len(image_data):
                image_data = compressed
                image_media_type = "image/jpeg" if fmt == "JPEG" else "image/png"
            print(f"[vision] image ready: {len(image_data)} bytes ({image_media_type})")
        except Exception as e:
            print(f"[vision] compression skipped: {e}")

        user_content = [
            {"type": "image", "source": {
                "type": "base64",
                "media_type": image_media_type,
                "data": base64.b64encode(image_data).decode(),
            }},
            {"type": "text", "text": prompt},
        ]
    else:
        user_content = prompt

    # Inject git context on first turn of session
    history = sessions_store.get_history(session_id)
    if not history:
        git_ctx = _git_context(project_path)
        if git_ctx:
            sessions_store.append_history(session_id, "user", f"[Context] {git_ctx}")
            sessions_store.append_history(session_id, "assistant", "Got it, I have the git context.")
            history = sessions_store.get_history(session_id)

    # Check for saved resume context (set when previous run hit step limit)
    resume_ctx = sessions_store.pop_resume_context(session_id)
    if resume_ctx:
        prompt = resume_ctx + f"\n\nUser instruction: {prompt}"
    else:
        # Check for persistent task summary from a previous run
        task_summary = sessions_store.get_task_summary(session_id)
        if task_summary and task_summary.get("task_remaining") and not history:
            prompt = (
                f"[PREVIOUS SESSION CONTEXT]\n"
                f"What was requested: {task_summary.get('task_requested', '')}\n"
                f"What was completed: {task_summary.get('task_completed', '')}\n"
                f"What remains: {task_summary.get('task_remaining', '')}\n"
                f"Summary: {task_summary.get('summary', '')}\n\n"
                f"User instruction: {prompt}"
            )

    sessions_store.append_history(session_id, "user", prompt)
    sessions_store.update_last_prompt(session_id, prompt)

    messages = history + [{"role": "user", "content": user_content}]

    # Extract the raw user task for system prompt injection (strip resume/context prefixes)
    raw_task = prompt
    for prefix in ("[RESUME CONTEXT]", "[PREVIOUS SESSION CONTEXT]", "[SYSTEM]"):
        if raw_task.startswith(prefix):
            # Pull out the "User instruction:" part if present
            if "User instruction:" in raw_task:
                raw_task = raw_task.split("User instruction:")[-1].strip()
            break

    # Compact history if too large
    system = _build_system_prompt(
        project_path,
        project_name=os.path.basename(project_path) if project_path else "",
        history=messages,
        current_task=raw_task,
        session_id=session_id,
    )
    messages = await _compact_history(client, messages, system)

    clear_cancel(session_id)
    final_text = ""
    turn = 0
    response = None

    while turn < max_turns:
        turn += 1

        if _cancel_flags.get(session_id):
            clear_cancel(session_id)
            sessions_store.append_history(session_id, "assistant", final_text)
            return (final_text or "") + "\n\n⛔ Stopped by user."

        if progress_cb:
            await asyncio.get_event_loop().run_in_executor(None, lambda: None)
            progress_cb("🤔 Thinking..." if turn == 1 else f"🔄 Step {turn}")

        extra_kwargs = {}
        if ENABLE_THINKING:
            extra_kwargs["thinking"] = {"type": "enabled", "budget_tokens": 8000}

        def _call(msgs=messages):
            return client.messages.create(
                model=MODEL,
                max_tokens=8096,
                system=system,
                tools=TOOLS,
                messages=msgs,
                **extra_kwargs,
            )

        try:
            response = await asyncio.wait_for(
                asyncio.get_event_loop().run_in_executor(None, _call),
                timeout=200.0,
            )
        except asyncio.TimeoutError:
            if progress_cb:
                progress_cb("⚠️ API call timed out (200s). Retrying...")
            # Append a continuation nudge so Claude doesn't re-plan from scratch on retry
            _retry_messages = messages + [{"role": "user", "content":
                "[TIMEOUT RECOVERY] The previous API call timed out. "
                "Resume immediately from where you left off. "
                "Make your next tool call NOW — do not re-read files you already read, "
                "do not re-explain the plan. Just continue."
            }] if messages and messages[-1].get("role") != "user" else messages
            try:
                response = await asyncio.wait_for(
                    asyncio.get_event_loop().run_in_executor(None, lambda: _call(_retry_messages)),
                    timeout=200.0,
                )
            except asyncio.TimeoutError:
                return final_text or "❌ Claude API timed out after retrying. Try again with `/claude continue`."

        # Track tokens
        if hasattr(response, "usage"):
            t = _token_totals.setdefault(session_id, {"input": 0, "output": 0})
            t["input"] += getattr(response.usage, "input_tokens", 0)
            t["output"] += getattr(response.usage, "output_tokens", 0)

        text_parts = [b.text for b in response.content if hasattr(b, "text") and b.type == "text"]
        if text_parts:
            final_text = "\n".join(text_parts)

        # Detect proxy truncation error — the proxy strips the tool_use block and
        # injects an error as text, then sets stop_reason to end_turn.
        # We intercept this and inject a forced retry instruction so Claude splits the file.
        _truncation_markers = ["content too large", "truncated by API", "splitting into 2-3 smaller writes"]
        _is_truncated = any(m in (final_text or "") for m in _truncation_markers)
        if _is_truncated:
            print(f"[claude] ⚠️ Proxy truncation detected — forcing split retry")
            if progress_cb:
                progress_cb("⚠️ File too large for API — forcing Claude to split into chunks...")
            # Strip the proxy error from final text
            for m in _truncation_markers:
                if m in (final_text or ""):
                    final_text = (final_text or "").split(m)[0].strip()
                    break
            # Inject a user message that forces Claude to retry with smaller writes
            messages.append({"role": "assistant", "content": final_text or "I'll write the file now."})
            messages.append({"role": "user", "content": (
                "[SYSTEM] Your last write_file call FAILED because the content was too large for the API. "
                "The file was NOT written. You MUST retry NOW by splitting into smaller chunks:\n"
                "1. write_file mode='write' path='<same path>' — first ~2500 chars of the file\n"
                "2. write_file mode='append' path='<same path>' — next ~2500 chars\n"
                "3. Continue appending until the full file is written\n"
                "Each chunk MUST be under 2500 characters. Do NOT try the full file again. "
                "Start writing the first chunk NOW."
            )})
            turn += 1
            continue

        if response.stop_reason == "end_turn":
            # ── Ghost completion detection ──────────────────────────────────
            # After a timeout retry (or any turn), Claude sometimes returns
            # planning-only text ("I'll implement...", "Let me start...") with
            # zero tool calls — claiming it's done without having done anything.
            # Detect this and force Claude to actually start working.
            _planning_phrases = [
                "i'll implement", "i will implement",
                "let me start", "let me begin", "let me examine", "let me analyze",
                "i'll create", "i'll build", "i'll now", "i'll design",
                "i'll develop", "i will create", "i will build", "i will now",
            ]
            _text_lower = (final_text or "").lower()[:300]
            _looks_like_planning = any(p in _text_lower for p in _planning_phrases)

            # Count tool calls in the CURRENT response only (not historical)
            _tool_calls_made = sum(1 for b in response.content if b.type == "tool_use")

            if _looks_like_planning and _tool_calls_made == 0 and turn < max_turns:
                # Claude announced it would work but hasn't — force it to act
                if progress_cb:
                    progress_cb("⚠️ Ghost completion detected — forcing Claude to actually start...")
                messages.append({"role": "assistant", "content": final_text or "I'll start now."})
                messages.append({"role": "user", "content": (
                    "[SYSTEM] You said you would implement something but you haven't made any tool calls yet. "
                    "STOP PLANNING. Make your FIRST tool call RIGHT NOW — write_file, bash, or read_file. "
                    "Do not write any more explanatory text. Just call a tool immediately."
                )})
                turn += 1
                continue

            break

        if response.stop_reason == "tool_use":
            tool_results = []
            # Loop detection: track recent tool calls
            recent_calls = [
                (b.name, json.dumps(b.input, sort_keys=True))
                for msg in messages[-6:]
                if isinstance(msg.get("content"), list)
                for b in (msg["content"] if isinstance(msg["content"], list) else [])
                if isinstance(b, dict) and b.get("type") == "tool_use"
            ]
            current_calls = [
                (b.name, json.dumps(b.input, sort_keys=True))
                for b in response.content if b.type == "tool_use"
            ]
            # If the exact same tool+input appeared 3+ times recently, break the loop
            for call in current_calls:
                if recent_calls.count(call) >= 2:
                    sessions_store.append_history(session_id, "assistant", final_text)
                    return (final_text or "") + "\n\n⚠️ Stopped: detected a repeated action loop. Please rephrase your request or start a new session."

            # Check for proxy-injected truncation errors in text blocks
            _proxy_error = False
            for block in response.content:
                if hasattr(block, "text") and block.type == "text":
                    if "content too large" in (block.text or "") or "truncated by API" in (block.text or ""):
                        _proxy_error = True
                        break

            for block in response.content:
                if block.type != "tool_use":
                    continue

                # Detect truncated write_file: proxy stripped the content
                if block.name == "write_file" and block.input.get("mode", "write") in ("write", "append"):
                    content = block.input.get("content", "")
                    if _proxy_error or not content:
                        result = (
                            "[FAILED: File content was too large and got truncated by the API proxy. "
                            "You MUST split this into smaller pieces:\n"
                            "1. write_file mode='write' with the FIRST ~3000 chars of the file\n"
                            "2. write_file mode='append' with the NEXT ~3000 chars\n"
                            "3. Continue appending until complete\n"
                            "Each call MUST have content under 3500 characters. Do this NOW.]"
                        )
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result,
                        })
                        if progress_cb:
                            progress_cb("⚠️ write_file too large — instructing Claude to split...")
                        continue

                if progress_cb:
                    progress_cb(_format_tool_progress(block.name, block.input))

                # Async tools run directly; sync tools in executor
                if block.name == "send_file":
                    result = await _run_send_file(block.input, project_path, channel_id)
                elif block.name == "send_image":
                    result = await _run_send_image(block.input, project_path, channel_id)
                elif block.name == "screenshot":
                    result = await _run_screenshot(block.input, project_path, channel_id)
                elif block.name == "browser_console":
                    result = await _run_browser_console(block.input)
                elif block.name == "browser_action":
                    result = await _run_browser_action(block.input, project_path, channel_id)
                elif block.name == "test_flow":
                    result = await _run_test_flow(block.input, project_path, channel_id)
                elif block.name == "deploy_update":
                    result = await _run_deploy_update(block.input)
                elif block.name == "list_projects":
                    result = await _run_list_projects()
                elif block.name == "list_deployments":
                    result = await _run_list_deployments(block.input)
                elif block.name == "service_health":
                    result = await _run_service_health(block.input)
                elif block.name == "allocate_port":
                    result = await _run_allocate_port(block.input)
                elif block.name == "free_port":
                    result = await _run_free_port(block.input)
                elif block.name == "list_infrastructure":
                    result = await _run_list_infrastructure(block.input)
                else:
                    result = await asyncio.get_event_loop().run_in_executor(
                        None, lambda b=block: _run_tool(b.name, b.input, project_path, shell,
                                                        session_id=session_id)
                    )
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result,
                })
            messages.append({"role": "assistant", "content": response.content})

            # Inject task reminder every 5 turns to prevent goal drift
            if turn % 5 == 0 and turn < max_turns and tool_results:
                reminder = (
                    f"\n\n[TASK REMINDER — step {turn}/{max_turns}] "
                    f"Your current task: {raw_task[:200]}\n"
                    f"Stay focused on this goal. If you've been exploring without building, start NOW."
                )
                tool_results[-1]["content"] = (tool_results[-1].get("content", "") or "") + reminder

            messages.append({"role": "user", "content": tool_results})
        else:
            break

    sessions_store.append_history(session_id, "assistant", final_text)

    if turn >= max_turns and response and response.stop_reason == "tool_use":
        # Generate structured task summary
        original_prompt = sessions_store.get_last_prompt(session_id) or prompt
        task_summary = await _generate_task_summary(client, messages, original_prompt, session_id)

        last_tools = [
            f"- {b.name}: {json.dumps(b.input)[:120]}"
            for b in response.content if b.type == "tool_use"
        ]
        resume_ctx = (
            f"[RESUME CONTEXT] You hit the step limit. Here is your task state:\n"
            f"ORIGINAL REQUEST: {original_prompt[:300]}\n"
            f"COMPLETED SO FAR: {task_summary.get('completed', 'unknown')}\n"
            f"REMAINING: {task_summary.get('remaining', 'unknown')}\n"
            f"Last actions you were about to take:\n" + "\n".join(last_tools) + "\n"
            f"Continue EXACTLY from where you left off. Focus on the REMAINING items. "
            f"Do NOT re-analyze, re-read files you already read, or restart from scratch."
        )
        sessions_store.save_resume_context(session_id, resume_ctx)

        exc = TurnLimitReached(final_text or "(no response)")
        exc.task_summary = task_summary
        raise exc

    return final_text or "(no response)"


def get_token_usage(session_id: str) -> dict:
    return _token_totals.get(session_id, {"input": 0, "output": 0})


def close_session_shell(session_id: str):
    shell = _shells.pop(session_id, None)
    if shell:
        shell.cleanup()
    # Clean up bulk coordination state
    bulk_ctx = _session_bulk_ctx.pop(session_id, None)
    if bulk_ctx:
        bulk_run = _bulk_run_sessions.get(bulk_ctx["bulk_run_id"], {})
        bulk_run.pop(session_id, None)


async def get_diff(project_path: str) -> str:
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None, lambda: subprocess.run("git diff HEAD", shell=True, cwd=project_path,
                                     capture_output=True, text=True)
    )
    return truncate(result.stdout or "(no diff)", 3500)


async def get_status(project_path: str) -> str:
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None, lambda: subprocess.run("git status --short && git log --oneline -5",
                                     shell=True, cwd=project_path, capture_output=True, text=True)
    )
    return result.stdout.strip() or "(not a git repo)"
