"""
ProjectExo — Discord Bot
Gateway WebSocket mode. Routes slash commands to modular handlers.
"""
import asyncio
import json
import os
import sys

import websockets
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

# ── Path setup ────────────────────────────────────────────────────────────────
ROOT = os.path.dirname(__file__)
sys.path.insert(0, ROOT)

# ── Discord helpers ───────────────────────────────────────────────────────────
import utils.discord_helpers as dh
import utils.session_threads as session_threads
import storage.projects as proj_store
import storage.sessions as sess_store
import storage.discord_jobs as discord_jobs_store
import storage.discord_ops as discord_ops_store
import storage.agent_ops as agent_ops_store
import layers.codex_exec as claude_exec
import tools.pexo_discord as pexo_discord_tool
import tools.pexo_agents as pexo_agents_tool
dh.init(os.getenv("DISCORD_BOT_TOKEN"))

# ── Storage bootstrap ─────────────────────────────────────────────────────────
import storage.servers as srv_store
_host = os.getenv("DEFAULT_HOST", "")
_user = os.getenv("DEFAULT_HOST_USER", "root")
_pass = os.getenv("DEFAULT_HOST_PASSWORD", "")
if _host and _pass:
    srv_store.seed_default(_host, _user, _pass)

# ── Cloudflare bootstrap ───────────────────────────────────────────────────────
import storage.cloudflare as cf_store
_cf_token = os.getenv("CLOUDFLARE_TOKEN", os.getenv("cloudflare_token", ""))
if _cf_token and not cf_store.get_token():
    import asyncio as _asyncio
    import layers.cloudflare_layer as _cf_layer
    async def _seed_cf():
        account_id = await _cf_layer.get_account_id(_cf_token)
        cf_store.save_token(_cf_token, account_id or "")
        print(f"[✓] Cloudflare auto-connected (account: {account_id})")
    _asyncio.new_event_loop().run_until_complete(_seed_cf())

# ── GitHub bootstrap ──────────────────────────────────────────────────────────
import storage.github as _gh_store
_gh_token = os.getenv("GITHUB_TOKEN", "")
_gh_user  = os.getenv("GITHUB_USERNAME", "")
if _gh_token and _gh_user and not _gh_store.get_token():
    _gh_store.save(_gh_token, _gh_user)
    print(f"[✓] GitHub auto-connected ({_gh_user})")

# ── Command handlers ──────────────────────────────────────────────────────────
import commands.project as project_cmd
import commands.files as files_cmd
import commands.claude_cmd as claude_cmd
import commands.session_cmd as session_cmd
import commands.preview_cmd as preview_cmd
import commands.server_cmd as server_cmd
import commands.cloudflare_cmd as cloudflare_cmd
import commands.github_cmd as github_cmd
import commands.discord_cmd as discord_cmd
import commands.deploy_cmd as deploy_cmd
import commands.test_cmd as test_cmd
import skills.make_live as make_live_skill

BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
GATEWAY_URL = "wss://gateway.discord.gg/?v=10&encoding=json"

# Intents: GUILDS(1) + GUILD_MESSAGES(512) + MESSAGE_CONTENT(32768)
# MESSAGE_CONTENT is a privileged intent — must be enabled in Discord Dev Portal:
# discord.com/developers/applications → Bot → Privileged Gateway Intents → Message Content Intent ON
_msg_content_enabled = os.getenv("MESSAGE_CONTENT_INTENT", "false").lower() == "true"
INTENTS = (1 | 512 | 32768) if _msg_content_enabled else 0


# ── Interaction router ────────────────────────────────────────────────────────

async def route(data: dict):
    interaction_id = data["id"]
    token = data["token"]
    channel_id = data.get("channel_id", "")
    user = data.get("member", {}).get("user") or data.get("user", {})
    user_id = user.get("id", "")
    command = data["data"]["name"]
    options = data["data"].get("options", [])

    # Defer immediately — all commands take time
    await dh.defer(interaction_id, token)

    sub, sub_opts = dh.subcommand(options)

    # Helpers scoped to this interaction's token
    async def fu(t, content):
        await dh.followup(t, content)
    async def fu_chunks(t, text, code_lang=""):
        await dh.followup_chunks(t, text, code_lang)

    try:
        if command == "ping":
            await dh.followup(token, "🏓 Pong! ProjectExo is online.")

        elif command == "project":
            await project_cmd.handle(sub, sub_opts, token, channel_id, user_id)

        elif command == "files":
            await files_cmd.handle_files(sub, sub_opts, token, channel_id)

        elif command == "file":
            await files_cmd.handle_file(sub, sub_opts, token, channel_id)

        elif command in ("claude", "codex"):
            await claude_cmd.handle(sub, sub_opts, token, channel_id, user_id, fu, fu_chunks)

        elif command == "session":
            await session_cmd.handle(sub, sub_opts, token, channel_id)

        elif command == "preview":
            await preview_cmd.handle(sub, sub_opts, token, channel_id)

        elif command == "server":
            await server_cmd.handle(sub, sub_opts, token)

        elif command == "cloudflare":
            await cloudflare_cmd.handle(sub, sub_opts, token, channel_id)

        elif command == "github":
            await github_cmd.handle(sub, sub_opts, token)

        elif command == "discord":
            await discord_cmd.handle(sub, sub_opts, token, channel_id, user_id)

        elif command == "deploy":
            await deploy_cmd.handle(sub, sub_opts, token, channel_id)

        elif command == "test":
            await test_cmd.handle(sub, sub_opts, token, channel_id, user_id)

        elif command == "make-live":
            notes = dh.opts(options).get("notes", "")
            await make_live_skill.run(token, channel_id, user_id, notes)

        else:
            await dh.followup(token, f"❌ Unknown command: `/{command}`")

    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        print(f"[!] Handler error for /{command}: {e}\n{tb}")
        message = str(e)[:200]
        friendly_prefixes = (
            "Codex CLI is not authenticated",
            "Codex CLI could not reach",
            "Active project path does not exist",
            "Dev server crashed on startup",
            "Failed to install Python requirements",
        )
        if any(message.startswith(prefix) for prefix in friendly_prefixes):
            await dh.followup(token, f"❌ {message}")
        else:
            await dh.followup(token, f"❌ Internal error: `{message}`")


# ── Auto-bulk: parse numbered app specs from text ────────────────────────────

import re as _re

def _parse_numbered_specs(text: str) -> list[dict] | None:
    """Detect numbered specs and split into individual items.
    Handles: '1. Name', '1) Name', '**1.** Name', '1 - Name', '#1 Name'
    Returns None if fewer than 2 specs found.

    Deduplicates by index — if the same index appears twice (e.g. sub-lists inside
    a spec body), only the FIRST occurrence is kept so we don't get phantom specs.
    """
    # Try multiple patterns, use whichever matches the most
    patterns = [
        _re.compile(r'^\*{0,2}(\d{1,3})\.\*{0,2}\s+(.+)', _re.MULTILINE),   # 1. / **1.** / *1.*
        _re.compile(r'^(\d{1,3})\)\s+(.+)', _re.MULTILINE),                    # 1)
        _re.compile(r'^(\d{1,3})\s*[-–—]\s+(.+)', _re.MULTILINE),              # 1 - / 1 –
        _re.compile(r'^#{1,3}\s*(\d{1,3})[\.\):]?\s+(.+)', _re.MULTILINE),     # # 1 / ## 1.
        _re.compile(r'^App\s+(\d{1,3})[\.\):]?\s+(.+)', _re.MULTILINE | _re.IGNORECASE),  # App 1: / App 1.
    ]

    best_matches = []
    for pat in patterns:
        found = list(pat.finditer(text))
        if len(found) > len(best_matches):
            best_matches = found

    matches = best_matches
    print(f"[bulk-parse] tried {len(patterns)} patterns, best matched {len(matches)} specs")

    if len(matches) < 2:
        print(f"[bulk-parse] NOT bulk — text starts with: {text[:200]!r}")
        return None

    preamble = text[:matches[0].start()].strip()
    print(f"[bulk-parse] preamble: {len(preamble)} chars, {len(matches)} raw matches")

    # Deduplicate by index: only keep first occurrence of each index number.
    # This prevents sub-list items inside spec bodies from being treated as new specs.
    seen_indices: set[int] = set()
    deduped_matches = []
    for m in matches:
        idx = int(m.group(1))
        if idx not in seen_indices:
            seen_indices.add(idx)
            deduped_matches.append(m)
    matches = deduped_matches
    print(f"[bulk-parse] after dedup: {len(matches)} unique specs")

    if len(matches) < 2:
        print(f"[bulk-parse] NOT bulk after dedup")
        return None

    specs = []
    for i, m in enumerate(matches):
        idx = int(m.group(1))
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[m.start():end].strip()
        first_line = m.group(2).strip()
        # Strip markdown bold markers from name
        first_line_clean = _re.sub(r'\*+', '', first_line).strip()
        # Extract short name: split on common delimiters
        name = _re.split(r'\s*[-–—:]\s*', first_line_clean, maxsplit=1)[0][:60].strip()
        full_prompt = (preamble + "\n\n" + body).strip() if preamble else body
        specs.append({"index": idx, "name": name, "prompt": full_prompt})

    print(f"[bulk-parse] specs: {[s['name'] for s in specs[:5]]}{'...' if len(specs) > 5 else ''}")
    return specs if len(specs) >= 2 else None


async def _run_bulk_from_specs(channel_id: str, user_id: str, proj: dict, specs: list[dict]):
    """Create ALL threads upfront, then run Codex in them 3 at a time.
    If running from inside a thread (Discord doesn't support nested threads),
    runs all apps inline in the same channel with bold headers instead.
    """
    import uuid as _uuid
    from commands.claude_cmd import _bulk_cancel
    _bulk_cancel[channel_id] = False

    bulk_run_id = _uuid.uuid4().hex[:8]
    total = len(specs)

    # Detect if we're already inside a thread — can't nest threads
    parent_channel_id = await dh.resolve_thread_parent(channel_id)
    in_thread = (parent_channel_id != channel_id)

    await dh.send_message(channel_id,
        f"📋 **Detected {total} app specs** — "
        f"{'running all in this channel (thread mode)' if in_thread else 'creating threads now'}.\n"
        f"Say `stop` to cancel. Project: `{proj['name']}`"
    )

    # ── Phase 1: thread_map setup ─────────────────────────────────────────────
    # list_position → destination channel id for each app's messages
    thread_map = {}  # list_position → channel_id (thread or same channel)

    # Create standalone threads in the parent channel (no anchor messages posted there — parent stays clean)
    for i, spec in enumerate(specs):
        thread_name = f"[{proj['name']}] #{spec['index']} {spec['name']}"
        print(f"[bulk] creating standalone thread: {thread_name}")
        result = await dh.create_thread_standalone(parent_channel_id, thread_name)
        tid = result.get("thread_id", "")
        if tid:
            thread_map[i] = tid
            await dh.send_message(tid, f"⏳ **{spec['name']}** — queued, waiting to start...")
            print(f"[bulk] thread created: {thread_name} → {tid}")
        else:
            print(f"[bulk] FAILED standalone thread for {thread_name}: {result}")
        await asyncio.sleep(1.0)

    nav_lines = [f"✅ **{len(thread_map)}/{total} threads created.** Codex is starting work...\n"]
    for i, spec in enumerate(specs):
        if thread_map.get(i):
            nav_lines.append(f"<#{thread_map[i]}>")
    await dh.send_message(channel_id, "\n".join(nav_lines))

    # ── Phase 2: Run Codex in each destination ────────────────────────────────
    completed = 0
    failed = 0

    all_specs_summary = [{"index": s["index"], "name": s["name"]} for s in specs]

    _PORT_FIND_SCRIPT = (
        "python3 -c \""
        "import socket, random, sys; "
        "used = set(); "
        "[used.add(int(l.split()[3].rsplit(':',1)[-1])) for l in open('/proc/net/tcp').readlines()[1:] if len(l.split())>3]; "
        "ports = [p for p in range(5100, 6000) if p not in used]; "
        "print(random.choice(ports[:50])) if ports else sys.exit(1)"
        "\""
    )

    async def run_one(spec: dict, position: int):
        nonlocal completed, failed
        if _bulk_cancel.get(channel_id):
            return

        dest = thread_map.get(position)
        if not dest:
            failed += 1
            return

        tag = f"[#{spec['index']}]"
        port_hint = (
            "\n\nIMPORTANT — Port & infrastructure setup:"
            "\n1. Find a free port FIRST by running this bash command before writing any code:"
            f"\n   `{_PORT_FIND_SCRIPT}`"
            "\n   Use whatever port it prints. Do NOT hardcode 5000-5010 — they may already be in use."
            "\n2. Check existing Cloudflare tunnel routes before picking a subdomain:"
            "\n   `cloudflared tunnel info <tunnel-name>` or check /etc/cloudflared/ configs."
            "\n   Pick a subdomain that is NOT already routed. Never reuse an occupied route."
            "\n3. If a port is already bound to a running process, pick a different one."
        )
        prompt_with_port = spec["prompt"] + port_hint

        try:
            thread_sess = sess_store.create(proj["name"], dest, user_id, thread_id=dest)
        except Exception as e:
            print(f"{tag} ERROR creating session: {e}")
            failed += 1
            return

        await dh.send_message(dest,
            f"🤖 **Working on: {spec['name']}**\nSession: `{thread_sess['id']}`"
        )
        print(f"[bulk] starting Codex for #{spec['index']} {spec['name']}")

        claude_exec.register_bulk_session(
            bulk_run_id=bulk_run_id,
            session_id=thread_sess["id"],
            spec_name=spec["name"],
            spec_index=spec["index"],
            all_specs=all_specs_summary,
        )

        def make_progress_cb(d=dest, tg=tag):
            async def _send(msg):
                try:
                    await dh.send_message(d, msg)
                except Exception:
                    pass
            def cb(msg):
                print(f"{tg} {msg}")
                try:
                    asyncio.get_event_loop().call_soon_threadsafe(
                        lambda m=msg: asyncio.ensure_future(_send(m)))
                except Exception:
                    pass
            return cb

        progress = make_progress_cb()

        run_kwargs = dict(
            session_id=thread_sess["id"],
            project_path=proj["path"],
            progress_cb=progress,
            channel_id=dest,
            user_id=user_id,
            bulk_run_id=bulk_run_id,
        )

        try:
            result = await claude_exec.run(prompt=prompt_with_port, **run_kwargs)
            await dh.send_message_chunks(dest, result)
            await dh.send_message(dest, f"✅ **{spec['name']}** complete.")
            completed += 1
        except claude_exec.TurnLimitReached as e:
            if e.partial_result:
                await dh.send_message_chunks(dest, e.partial_result)
            summary = getattr(e, 'task_summary', {})
            remaining = summary.get('remaining', 'unknown') if summary else 'unknown'

            for round_num in range(2, 6):
                if _bulk_cancel.get(channel_id):
                    break
                await dh.send_message(dest, f"🔄 Auto-continuing round {round_num}... (remaining: {remaining})")
                try:
                    result = await claude_exec.run(
                        prompt="Continue where you left off. Complete the remaining tasks.",
                        **run_kwargs,
                    )
                    await dh.send_message_chunks(dest, result)
                    await dh.send_message(dest, f"✅ **{spec['name']}** complete.")
                    completed += 1
                    return
                except claude_exec.TurnLimitReached as e2:
                    if e2.partial_result:
                        await dh.send_message_chunks(dest, e2.partial_result)
                    summary2 = getattr(e2, 'task_summary', {})
                    remaining = summary2.get('remaining', 'unknown') if summary2 else 'unknown'
                    if remaining and ('nothing' in remaining.lower() or 'complete' in remaining.lower()):
                        await dh.send_message(dest, f"✅ **{spec['name']}** appears complete.")
                        completed += 1
                        return
                except Exception as inner_e:
                    await dh.send_message(dest, f"❌ Error in round {round_num}: {str(inner_e)[:200]}")
                    break

            await dh.send_message(dest, f"⚠️ **{spec['name']}** — auto-continue exhausted. Say `continue` to keep going.")
            completed += 1
        except Exception as e:
            print(f"{tag} ERROR: {e}")
            await dh.send_message(dest, f"❌ Error: {str(e)[:200]}")
            failed += 1

    # Stagger starts by 3s each to avoid slamming the API proxy
    async def staggered_run(spec, position, delay):
        if _bulk_cancel.get(channel_id):
            return
        if delay > 0:
            await asyncio.sleep(delay)
        await run_one(spec, position)

    tasks = [asyncio.create_task(staggered_run(s, i, i * 3)) for i, s in enumerate(specs)]
    await asyncio.gather(*tasks, return_exceptions=True)

    _bulk_cancel.pop(channel_id, None)
    await dh.send_message(channel_id,
        f"🏁 **Bulk run finished** — {completed}/{total} completed, {failed} failed."
    )


# ── Plain message handler ─────────────────────────────────────────────────────

_BOT_ID = None  # set on READY
_pending_project_create: dict[str, dict] = {}


def _project_slug(text: str) -> str:
    cleaned = _re.sub(r"[^a-zA-Z0-9._-]+", "-", (text or "").strip()).strip("-._").lower()
    return cleaned[:64]


def _normalize_project_query(text: str) -> str:
    return _re.sub(r"[^a-z0-9]+", "", (text or "").lower())


def _projects_dir() -> str:
    path = os.path.join(ROOT, "projects")
    os.makedirs(path, exist_ok=True)
    return path


def _project_names_text(projects: list[dict] | None = None) -> str:
    projects = projects if projects is not None else proj_store.list_all()
    if not projects:
        return "(none)"
    return ", ".join(f"`{p['name']}`" for p in projects)


def _find_project_by_text(text: str) -> dict | None:
    query = (text or "").strip().strip("`'\"")
    if not query:
        return None
    projects = proj_store.list_all()
    if not projects:
        return None

    lowered = query.lower()
    exact = next((p for p in projects if p["name"].lower() == lowered), None)
    if exact:
        return exact

    normalized = _normalize_project_query(query)
    canonical_matches = [p for p in projects if _normalize_project_query(p["name"]) == normalized]
    if len(canonical_matches) == 1:
        return canonical_matches[0]

    contains = [p for p in projects if lowered in p["name"].lower()]
    if len(contains) == 1:
        return contains[0]
    return None


def _extract_create_project_name(text: str) -> str:
    stripped = (text or "").strip()
    patterns = [
        r"^(?:please\s+)?(?:can you\s+)?(?:create|add|make|start)\s+(?:me\s+)?(?:a\s+)?project(?:\s+(?:called|named)\s+|\s+)(?P<name>[a-zA-Z0-9][\w ._-]{0,80})$",
        r"^(?:please\s+)?new\s+project(?:\s+(?:called|named)\s+|\s+)(?P<name>[a-zA-Z0-9][\w ._-]{0,80})$",
    ]
    for pattern in patterns:
        match = _re.match(pattern, stripped, _re.IGNORECASE)
        if match:
            return match.group("name").strip().strip("`'\"")
    return ""


def _extract_switch_project_name(text: str) -> str:
    stripped = (text or "").strip()
    patterns = [
        r"^(?:please\s+)?(?:can you\s+)?(?:switch|shift|move|use|open|select|go)\s+(?:me\s+)?(?:to\s+)?(?:project\s+)?(?P<name>[a-zA-Z0-9][\w ._-]{0,80})$",
        r"^(?:please\s+)?work on\s+(?:project\s+)?(?P<name>[a-zA-Z0-9][\w ._-]{0,80})$",
    ]
    for pattern in patterns:
        match = _re.match(pattern, stripped, _re.IGNORECASE)
        if match:
            return match.group("name").strip().strip("`'\"")
    return ""


def _current_project_for_channel(channel_id: str) -> dict | None:
    proj = proj_store.get_by_channel(channel_id)
    if proj:
        return proj
    sess = sess_store.get_active_for_channel(channel_id)
    if sess and sess.get("project_name"):
        return proj_store.get(sess["project_name"])
    return None


def _current_session_for_channel(channel_id: str) -> dict | None:
    sess = sess_store.get_active_for_channel(channel_id)
    if sess:
        return sess
    proj = _current_project_for_channel(channel_id)
    if proj:
        return sess_store.get_active_root_for_project(proj["name"])
    return None


async def _run_codex_in_channel(dest_channel_id: str, sess: dict, proj: dict, prompt: str, user_id: str,
                                image_data: bytes = None, image_media_type: str = "image/png") -> bool:
    progress_queue = asyncio.Queue()

    def on_progress(msg: str):
        print(f"[codex:{dest_channel_id}] {msg}")
        asyncio.get_event_loop().call_soon_threadsafe(progress_queue.put_nowait, msg)

    async def send_typing_loop():
        while True:
            await dh.send_typing(dest_channel_id)
            msgs = []
            while not progress_queue.empty():
                msgs.append(await progress_queue.get())
            if msgs:
                await dh.send_message(dest_channel_id, "\n".join(msgs[-5:]))
            await asyncio.sleep(8)

    typing_task = asyncio.create_task(send_typing_loop())
    try:
        result = await claude_exec.run(
            session_id=sess["id"],
            prompt=prompt,
            project_path=proj["path"],
            progress_cb=on_progress,
            image_data=image_data,
            image_media_type=image_media_type,
            channel_id=dest_channel_id,
            user_id=user_id,
        )
    except claude_exec.TurnLimitReached as e:
        typing_task.cancel()
        if e.partial_result:
            await dh.send_message_chunks(dest_channel_id, e.partial_result)
        await dh.send_message(
            dest_channel_id,
            "⚠️ **Step limit reached (20 steps).**\n"
            "Say `continue` to keep going, or use `/codex limit` to increase the limit."
        )
        return False
    except Exception as e:
        import traceback
        print(f"[!] run_codex_in_channel error: {e}\n{traceback.format_exc()}")
        typing_task.cancel()
        await dh.send_message(dest_channel_id, f"❌ Error: {str(e)[:200]}")
        return False
    finally:
        typing_task.cancel()

    await dh.send_message_chunks(dest_channel_id, result)
    return True


def _activate_project(name: str, channel_id: str, user_id: str) -> tuple[dict, dict]:
    proj = proj_store.get(name)
    if not proj:
        raise ValueError(f"Project `{name}` not found.")
    proj_store.set_active_channel(name, channel_id)
    sess = sess_store.get_active_for_channel(channel_id)
    if sess and sess.get("project_name") != name:
        claude_exec.close_session_shell(sess["id"])
        sess_store.close(sess["id"])
        sess = None
    if not sess or sess.get("project_name") != name:
        sess = sess_store.get_active_root_for_project(name)
        if sess:
            sess_store.attach_channel(sess["id"], channel_id)
        else:
            sess = sess_store.create(name, channel_id, user_id)
    return proj, sess


def _create_project_record(name: str) -> dict:
    slug = _project_slug(name)
    if not slug:
        raise ValueError("Project name must include letters or numbers.")
    path = os.path.join(_projects_dir(), slug)
    os.makedirs(path, exist_ok=True)
    return proj_store.add(slug, path, "")


async def _run_control_plane_turn(channel_id: str, user_id: str, prompt: str,
                                  image_data: bytes = None, image_media_type: str = "image/png"):
    progress_queue = asyncio.Queue()

    def on_progress(msg: str):
        print(f"[codex-control] {msg}")
        asyncio.get_event_loop().call_soon_threadsafe(progress_queue.put_nowait, msg)

    async def send_typing_loop():
        while True:
            await dh.send_typing(channel_id)
            msgs = []
            while not progress_queue.empty():
                msgs.append(await progress_queue.get())
            if msgs:
                await dh.send_message(channel_id, "\n".join(msgs[-5:]))
            await asyncio.sleep(8)

    control_prompt = (
        "No active project is currently bound to this Discord channel.\n"
        "You are in control mode. Help the user manage projects, sessions, Discord tasks, "
        "and infrastructure from conversation.\n"
        "Use $PEXO_PYTHON $PEXO_CONTEXT to inspect/create/switch projects and inspect/close sessions/history.\n"
        "Use $PEXO_PYTHON $PEXO_DISCORD for Discord-native actions.\n"
        "Use $PEXO_PYTHON $PEXO_AGENTS to spawn and manage delegated project agents once a project is active.\n"
        "Do not edit the bot repository itself unless the user explicitly asks you to work on this bot.\n"
        "If the user wants coding work on an app, create or switch to a project first, then tell them it is ready.\n\n"
        f"User message:\n{prompt}"
    )

    typing_task = asyncio.create_task(send_typing_loop())
    try:
        result, _ = await claude_exec.run_once(
            prompt=control_prompt,
            project_path=ROOT,
            progress_cb=on_progress,
            image_data=image_data,
            image_media_type=image_media_type,
            channel_id=channel_id,
            user_id=user_id,
            sandbox="workspace-write",
        )
        await dh.send_message_chunks(channel_id, result)
    except Exception as e:
        await dh.send_message(channel_id, f"❌ Error: {str(e)[:200]}")
    finally:
        typing_task.cancel()


def _looks_like_thread_intent(text: str) -> bool:
    lower = (text or "").lower().strip()
    if not lower:
        return False
    if "thread" in lower:
        return any(word in lower for word in ("create", "make", "start", "open", "move", "shift"))
    if "threa" in lower:
        return any(word in lower for word in ("create", "make", "start", "open", "move", "shift"))
    return False


async def _maybe_handle_control_message(channel_id: str, user_id: str, content: str) -> bool:
    text = (content or "").strip()
    if not text:
        return False

    lower = text.lower().strip()
    current_proj = _current_project_for_channel(channel_id)
    current_sess = _current_session_for_channel(channel_id)
    pending = _pending_project_create.get(channel_id)

    if pending:
        if lower in {"cancel", "never mind", "nevermind", "nvm"}:
            _pending_project_create.pop(channel_id, None)
            await dh.send_message(channel_id, "✅ Project creation cancelled.")
            return True
        try:
            created = _create_project_record(_extract_create_project_name(text) or text)
            proj, sess = _activate_project(created["name"], channel_id, user_id)
            _pending_project_create.pop(channel_id, None)
            await dh.send_message(
                channel_id,
                f"✅ Project **{proj['name']}** created and selected.\n"
                f"📁 `{proj['path']}`\n"
                f"🔑 Session: `{sess['id']}`\n"
                "You can start chatting with Codex here now."
            )
        except Exception as e:
            await dh.send_message(channel_id, f"❌ {str(e)[:200]}")
        return True

    if _looks_like_thread_intent(text):
        if current_sess and current_sess.get("thread_id") == channel_id:
            await dh.send_message(channel_id, f"🧵 This session is already running in <#{channel_id}>.")
            return True
        if current_proj:
            try:
                thread_sess, thread_id, created = await session_threads.ensure_parent_thread_session(
                    current_proj,
                    channel_id,
                    user_id,
                    thread_name=f"{current_proj['name']} session",
                )
                if created:
                    await dh.send_message(
                        channel_id,
                        f"🧵 Created the session thread: <#{thread_id}>. Continue there for the rest of this work."
                    )
                else:
                    await dh.send_message(
                        channel_id,
                        f"🧵 The active session thread is <#{thread_id}>. Continue there for the rest of this work."
                    )
            except Exception as e:
                await dh.send_message(channel_id, f"❌ {str(e)[:200]}")
            return True

        try:
            created = await dh.create_thread_standalone(
                channel_id,
                "codex session",
                initial_message=f"Continuing this Codex session from <#{channel_id}>.",
            )
            thread_id = created.get("thread_id", "")
            if not thread_id:
                raise RuntimeError("Failed to create the thread.")
            sess = sess_store.create("", thread_id, user_id, thread_id=thread_id)
            await dh.send_message(
                channel_id,
                f"🧵 Created <#{thread_id}> for this session. Continue there and I’ll work with you in that thread."
            )
            await dh.send_message(
                thread_id,
                f"🧵 **Thread ready.** Session: `{sess['id']}`\nTell me what you want to do here."
            )
        except Exception as e:
            await dh.send_message(channel_id, f"❌ {str(e)[:200]}")
        return True

    if any(phrase in lower for phrase in ("how many projects", "list projects", "show projects", "what projects")):
        projects = proj_store.list_all()
        if not projects:
            await dh.send_message(channel_id, "No projects yet. Say `create a project called my-app` to start one.")
            return True
        lines = [f"📁 {len(projects)} project(s):"]
        for proj in projects[:20]:
            marker = " ← active here" if current_proj and proj["name"] == current_proj["name"] else ""
            lines.append(f"• **{proj['name']}** — `{proj['path']}`{marker}")
        await dh.send_message(channel_id, "\n".join(lines))
        return True

    if "current project" in lower or "what project" in lower:
        if current_proj:
            message = (
                f"📁 Current project: **{current_proj['name']}**\n"
                f"📂 `{current_proj['path']}`"
            )
            if current_sess:
                message += f"\n🔑 Session: `{current_sess['id']}`"
            await dh.send_message(
                channel_id,
                message,
            )
        else:
            await dh.send_message(
                channel_id,
                f"No active project in this channel.\nAvailable: {_project_names_text()}\n"
                "Say `create a project called my-app` or `switch to test`."
            )
        return True

    create_name = _extract_create_project_name(text)
    wants_create = bool(create_name) or any(
        phrase in lower for phrase in ("create a project", "new project", "add project", "make a project", "start a project")
    )
    if wants_create:
        if not create_name:
            _pending_project_create[channel_id] = {"user_id": user_id}
            await dh.send_message(channel_id, "What should I call the new project?")
            return True
        try:
            created = _create_project_record(create_name)
            proj, sess = _activate_project(created["name"], channel_id, user_id)
            await dh.send_message(
                channel_id,
                f"✅ Project **{proj['name']}** created and selected.\n"
                f"📁 `{proj['path']}`\n"
                f"🔑 Session: `{sess['id']}`\n"
                "You can start chatting with Codex here now."
            )
        except Exception as e:
            await dh.send_message(channel_id, f"❌ {str(e)[:200]}")
        return True

    switch_name = _extract_switch_project_name(text)
    wants_switch = bool(switch_name) or any(phrase in lower for phrase in ("switch project", "shift project", "use project"))
    if wants_switch:
        target = _find_project_by_text(switch_name or text)
        if not target:
            await dh.send_message(
                channel_id,
                f"❌ I couldn't match that project.\nAvailable: {_project_names_text()}"
            )
            return True
        try:
            proj, sess = _activate_project(target["name"], channel_id, user_id)
            await dh.send_message(
                channel_id,
                f"✅ Switched to **{proj['name']}**.\n"
                f"📁 `{proj['path']}`\n"
                f"🔑 Session: `{sess['id']}`"
            )
        except Exception as e:
            await dh.send_message(channel_id, f"❌ {str(e)[:200]}")
        return True

    if any(phrase in lower for phrase in ("list sessions", "show sessions", "how many sessions")):
        sessions = sess_store.list_active()
        if not sessions:
            await dh.send_message(channel_id, "No active sessions.")
            return True
        lines = [f"🧠 {len(sessions)} active session(s):"]
        for sess in sessions[:20]:
            marker = " ← active here" if current_sess and sess["id"] == current_sess["id"] else ""
            lines.append(f"• `{sess['id']}` — **{sess['project_name'] or 'control'}**{marker}")
        await dh.send_message(channel_id, "\n".join(lines))
        return True

    if "current session" in lower or "what session" in lower:
        if not current_sess:
            await dh.send_message(channel_id, "No active session in this channel.")
        else:
            await dh.send_message(
                channel_id,
                f"🔑 Current session: `{current_sess['id']}`\n"
                f"📁 Project: **{current_sess['project_name'] or 'control'}**\n"
                f"💬 Messages: {current_sess['message_count']}"
            )
        return True

    if any(phrase in lower for phrase in ("close session", "end session", "stop session")):
        if not current_sess:
            await dh.send_message(channel_id, "No active session in this channel.")
            return True
        sess_store.close(current_sess["id"])
        proj_store.clear_active_channel(channel_id)
        await dh.send_message(
            channel_id,
            f"✅ Session `{current_sess['id']}` closed.\n"
            "This channel no longer has an active project."
        )
        return True

    if any(phrase in lower for phrase in ("new session", "restart session", "fresh session")):
        if not current_proj:
            await dh.send_message(channel_id, "No active project in this channel. Create or switch to a project first.")
            return True
        if current_sess:
            sess_store.close(current_sess["id"])
        sess = sess_store.create(current_proj["name"], channel_id, user_id)
        await dh.send_message(
            channel_id,
            f"✅ Started a fresh session for **{current_proj['name']}**.\n"
            f"🔑 Session: `{sess['id']}`"
        )
        return True

    if any(phrase in lower for phrase in ("show history", "session history", "chat history")):
        if not current_sess:
            await dh.send_message(channel_id, "No active session in this channel.")
            return True
        rows = sess_store.list_messages(session_id=current_sess["id"], limit=10)
        if not rows:
            await dh.send_message(channel_id, "No stored transcript messages for this session yet.")
            return True
        lines = [f"🗂 Recent history for `{current_sess['id']}`:"]
        for row in rows:
            lines.append(f"• **{row['role']}**: {row['content'][:160]}")
        await dh.send_message(channel_id, "\n".join(lines)[:1900])
        return True

    if not current_proj:
        casual = {
            "hello", "hi", "hey", "sup", "yo", "hiya", "howdy",
            "how are you", "how r u", "how are u", "what's up", "whats up",
            "good morning", "good evening", "good afternoon", "good night",
        }
        stripped = lower.rstrip("!?.").strip()
        in_session_thread = bool(current_sess and current_sess.get("thread_id") == channel_id)
        if in_session_thread:
            return False
        if stripped in casual or stripped.startswith(("hi ", "hey ", "hello ", "yo ")):
            await dh.send_message(
                channel_id,
                "👋 Yo. I'm here. I can create or switch projects, manage sessions and threads, "
                "or just help you figure out what to work on next. What do you want to do?"
            )
            return True

    return False

async def handle_message(data: dict):
    channel_id = data.get("channel_id", "")
    content = (data.get("content") or "").strip()
    author = data.get("author", {})
    user_id = author.get("id", "")

    # Ignore bots
    if author.get("bot"):
        return

    bound_proj = proj_store.get_by_channel(channel_id)
    bound_thread_sess = sess_store.get_active_for_channel(channel_id)
    active_thread_sess = session_threads.get_active_thread_session(bound_proj) if bound_proj else None

    # Quick "continue" shorthand for plain messages
    if content.lower() in ("continue", "c", "go", "keep going"):
        if bound_proj and active_thread_sess and active_thread_sess.get("thread_id") and active_thread_sess.get("thread_id") != channel_id:
            await dh.send_message(
                channel_id,
                f"🧵 This session is running in <#{active_thread_sess['thread_id']}>. Continue there for the rest of this work."
            )
            return
        sess = sess_store.get_active_for_channel(channel_id)
        if not sess:
            proj = proj_store.get_by_channel(channel_id)
            if proj:
                sess = sess_store.get_active_root_for_project(proj["name"])
                if sess:
                    sess_store.attach_channel(sess["id"], channel_id)
        if sess:
            proj = proj_store.get_by_channel(channel_id)
            if not proj:
                proj = proj_store.get(sess.get("project_name", "")) if sess.get("project_name") else None
            if proj:
                await dh.send_typing(channel_id)
                await dh.send_message(channel_id, f"🔄 Continuing session `{sess['id']}`...")
                try:
                    result = await claude_exec.run(
                        session_id=sess["id"],
                        prompt="Continue where you left off. Complete the remaining tasks.",
                        project_path=proj["path"],
                        channel_id=channel_id,
                        user_id=user_id,
                    )
                    await dh.send_message_chunks(channel_id, result)
                except claude_exec.TurnLimitReached as e:
                    if e.partial_result:
                        await dh.send_message_chunks(channel_id, e.partial_result)
                    await dh.send_message(channel_id, "⚠️ Step limit reached again. Say `continue` or use `/codex auto`.")
                except Exception as e:
                    await dh.send_message(channel_id, f"❌ Error: {str(e)[:200]}")
                return
        # Fall through to normal handling if no session

    # Interruption: "stop" or "cancel" cancels the running Codex task + auto-continue + bulk
    if content.lower() in ("stop", "cancel", "s"):
        sess = sess_store.get_active_for_channel(channel_id)
        if not sess and bound_proj and active_thread_sess and active_thread_sess.get("thread_id"):
            sess = active_thread_sess
        if not sess:
            proj = proj_store.get_by_channel(channel_id)
            if proj:
                sess = sess_store.get_active_root_for_project(proj["name"])
                if sess:
                    sess_store.attach_channel(sess["id"], channel_id)
        if sess:
            claude_exec.cancel_session(sess["id"])
            try:
                from commands.claude_cmd import _auto_continue, _bulk_cancel
                _auto_continue.pop(sess["id"], None)
                _bulk_cancel[channel_id] = True
            except ImportError:
                pass
            if sess.get("thread_id") and sess.get("thread_id") != channel_id:
                await dh.send_message(
                    channel_id,
                    f"⛔ Stopping the active session in <#{sess['thread_id']}> after the current step..."
                )
            else:
                await dh.send_message(channel_id, "⛔ Stopping after current step (auto-continue/bulk also cancelled)...")
        return

    if not data.get("attachments"):
        handled = await _maybe_handle_control_message(channel_id, user_id, content)
        if handled:
            return

    # Only respond if a project is active for this channel
    proj = bound_proj
    project_from_parent_binding = bool(proj)
    if not proj:
        # Check if this is a thread with an active session (from /codex thread or /codex bulk)
        thread_sess = sess_store.get_active_for_channel(channel_id)
        if thread_sess and thread_sess.get("project_name"):
            proj = proj_store.get(thread_sess["project_name"])
        if not proj:
            if content:
                await _run_control_plane_turn(channel_id, user_id, content)
            elif data.get("attachments"):
                await dh.send_message(
                    channel_id,
                    "No active project in this channel yet. Create or switch to a project before sending files or images for work."
                )
            return

    # Handle attachments: images and text files
    attachments = data.get("attachments", [])
    image_data, image_media_type = None, "image/png"
    text_file_content = None
    for att in attachments:
        ct = att.get("content_type", "") or ""
        fname = att.get("filename", "").lower()

        # Text file attachments → use as prompt
        if ct.startswith("text/") or fname.endswith((".txt", ".md", ".json", ".csv", ".py", ".js", ".html")):
            try:
                import httpx as _httpx
                async with _httpx.AsyncClient(timeout=30, follow_redirects=True) as c:
                    r = await c.get(att["url"])
                text_file_content = r.text
                print(f"[text-file] downloaded {len(text_file_content)} chars from {att['filename']}")
            except Exception as e:
                print(f"[text-file] download failed: {e}")
            continue

        # Image attachments
        if ct.startswith("image/") or fname.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp")):
            image_media_type = ct if ct.startswith("image/") else "image/png"
            try:
                import httpx as _httpx
                async with _httpx.AsyncClient(timeout=30, follow_redirects=True) as c:
                    r = await c.get(att["url"])
                image_data = r.content
                print(f"[image] downloaded {len(image_data)} bytes from {att['url']}")
            except Exception as e:
                print(f"[image] download failed: {e}")

    # Merge text file content with message text
    if text_file_content:
        content = (content + "\n\n" + text_file_content).strip() if content else text_file_content

    if not content and not image_data:
        return

    # ── Auto-bulk detection: numbered app specs → 1 thread per app ────────
    if content and not image_data:
        print(f"[bulk-detect] checking content ({len(content)} chars) for numbered specs...")
        specs = _parse_numbered_specs(content)
        if specs and len(specs) > 1:
            print(f"[bulk-detect] BULK MODE — {len(specs)} specs, creating threads")
            await _run_bulk_from_specs(channel_id, user_id, proj, specs)
            return
        else:
            print(f"[bulk-detect] not bulk, running as single prompt")

    # Resolve skill templates (e.g. !frontend, !review)
    from skills.loader import resolve_prompt, list_skills
    if content:
        prompt = resolve_prompt(content)
        if image_data:
            prompt = prompt + "\n\n[The user has attached an image — analyze it carefully and respond to their request about it.]"
    elif image_data:
        prompt = "The user sent an image. Analyze it in detail: describe what you see, identify any UI/design elements, code, diagrams, or content visible in the image, and suggest what to do with it."
    else:
        return

    # Notify user if a skill was activated
    if content and content.startswith("!"):
        skill_name = content[1:].split()[0].lower() if content[1:].split() else ""
        if skill_name in list_skills():
            await dh.send_message(channel_id, f"🎨 **Skill `{skill_name}` activated** — running with full design guides...")

    if project_from_parent_binding:
        existing_thread_sess = session_threads.get_active_thread_session(proj)
        if existing_thread_sess and existing_thread_sess.get("thread_id"):
            await dh.send_message(
                channel_id,
                f"🧵 This project's active session is in <#{existing_thread_sess['thread_id']}>. Continue there for the rest of this task."
            )
            return

        await dh.send_typing(channel_id)
        thread_sess, thread_id, _created = await session_threads.ensure_parent_thread_session(
            proj,
            channel_id,
            user_id,
            thread_name=f"{proj['name']} session",
        )
        await dh.send_message(
            channel_id,
            f"🧵 I opened <#{thread_id}> for this session and started the work there. Continue in that thread for the rest of this task."
        )
        await dh.send_message(
            thread_id,
            f"🤖 **Codex is working on it...**\nProject: `{proj['name']}`\nSession: `{thread_sess['id']}`"
        )
        await _run_codex_in_channel(
            thread_id,
            thread_sess,
            proj,
            prompt,
            user_id,
            image_data=image_data,
            image_media_type=image_media_type,
        )
        return

    sess = bound_thread_sess
    if sess and sess.get("project_name") != proj["name"]:
        sess = None
    if not sess:
        sess = sess_store.get_active_root_for_project(proj["name"])
        if sess:
            sess_store.attach_channel(sess["id"], channel_id)
        else:
            sess = sess_store.create(proj["name"], channel_id, user_id)
    await dh.send_typing(channel_id)
    await _run_codex_in_channel(
        channel_id,
        sess,
        proj,
        prompt,
        user_id,
        image_data=image_data,
        image_media_type=image_media_type,
    )


# ── Gateway loop ──────────────────────────────────────────────────────────────

async def gateway_loop():
    sequence = None

    async with websockets.connect(GATEWAY_URL) as ws:
        print("[*] Connected to Discord Gateway")

        async def heartbeat(interval_ms):
            while True:
                await asyncio.sleep(interval_ms / 1000)
                await ws.send(json.dumps({"op": 1, "d": sequence}))

        async for raw in ws:
            msg = json.loads(raw)
            op, d, t, s = msg["op"], msg.get("d"), msg.get("t"), msg.get("s")
            if s:
                sequence = s

            if op == 10:
                asyncio.create_task(heartbeat(d["heartbeat_interval"]))
                await ws.send(json.dumps({
                    "op": 2,
                    "d": {
                        "token": BOT_TOKEN,
                        "intents": INTENTS,
                        "properties": {"os": "linux", "browser": "projectexo", "device": "projectexo"},
                    },
                }))

            elif op == 7:
                print("[!] Reconnect requested")
                break

            elif op == 9:
                print("[!] Invalid session — reconnecting in 5s")
                await asyncio.sleep(5)
                break

            elif op == 0:
                if t == "READY":
                    u = d["user"]
                    global _BOT_ID
                    _BOT_ID = u["id"]
                    print(f"[✓] ProjectExo ready: {u['username']}#{u['discriminator']}")
                elif t == "INTERACTION_CREATE" and d.get("type") == 2:
                    asyncio.create_task(route(d))
                elif t == "MESSAGE_CREATE":
                    asyncio.create_task(handle_message(d))


async def discord_jobs_loop():
    while True:
        try:
            for job in discord_jobs_store.list_due(limit=10):
                target = job.get("thread_id") or job.get("channel_id")
                try:
                    result = await dh.send_message(target, job["content"])
                    discord_jobs_store.mark_sent(job["id"], result.get("id", ""))
                    print(f"[discord-jobs] sent job {job['id']} to {target}")
                except Exception as e:
                    discord_jobs_store.mark_failed(job["id"])
                    print(f"[discord-jobs] failed job {job['id']}: {e}")
        except Exception as e:
            print(f"[discord-jobs] loop error: {e}")
        await asyncio.sleep(15)


async def discord_ops_loop():
    while True:
        try:
            for op in discord_ops_store.list_pending(limit=10):
                op_id = op.get("id", "")
                try:
                    request = json.loads(op.get("request_json", "") or "{}")
                except Exception as e:
                    discord_ops_store.mark_failed(op_id, f"Invalid discord op payload: {e}")
                    print(f"[discord-ops] invalid payload {op_id}: {e}")
                    continue

                discord_ops_store.mark_processing(op_id)
                try:
                    result = await pexo_discord_tool.execute_request(request)
                    discord_ops_store.mark_done(op_id, result)
                    print(f"[discord-ops] completed {op_id}: {request.get('cmd', '')}")
                except SystemExit as e:
                    message = str(e) or "Discord operation failed."
                    discord_ops_store.mark_failed(op_id, message)
                    print(f"[discord-ops] failed {op_id}: {message}")
                except Exception as e:
                    discord_ops_store.mark_failed(op_id, str(e))
                    print(f"[discord-ops] failed {op_id}: {e}")
        except Exception as e:
            print(f"[discord-ops] loop error: {e}")
        await asyncio.sleep(0.25)


async def agent_ops_loop():
    while True:
        try:
            for op in agent_ops_store.list_pending(limit=10):
                op_id = op.get("id", "")
                try:
                    request = json.loads(op.get("request_json", "") or "{}")
                except Exception as e:
                    agent_ops_store.mark_failed(op_id, f"Invalid agent op payload: {e}")
                    print(f"[agent-ops] invalid payload {op_id}: {e}")
                    continue

                agent_ops_store.mark_processing(op_id)
                try:
                    result = pexo_agents_tool.execute_request(request)
                    agent_ops_store.mark_done(op_id, result)
                    print(f"[agent-ops] completed {op_id}: {request.get('cmd', '')}")
                except SystemExit as e:
                    message = str(e) or "Agent operation failed."
                    agent_ops_store.mark_failed(op_id, message)
                    print(f"[agent-ops] failed {op_id}: {message}")
                except Exception as e:
                    agent_ops_store.mark_failed(op_id, str(e))
                    print(f"[agent-ops] failed {op_id}: {e}")
        except Exception as e:
            print(f"[agent-ops] loop error: {e}")
        await asyncio.sleep(0.25)


async def main():
    print("[*] Starting ProjectExo...")
    asyncio.create_task(discord_jobs_loop())
    asyncio.create_task(discord_ops_loop())
    asyncio.create_task(agent_ops_loop())
    while True:
        try:
            await gateway_loop()
        except Exception as e:
            print(f"[!] Gateway error: {e} — reconnecting in 5s")
            await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(main())
