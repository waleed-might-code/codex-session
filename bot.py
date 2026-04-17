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
import storage.projects as proj_store
import storage.sessions as sess_store
import layers.claude_exec as claude_exec
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

        elif command == "claude":
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
        await dh.followup(token, f"❌ Internal error: `{str(e)[:200]}`")


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
    """Create ALL threads upfront, then run Claude in them 3 at a time.
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

    nav_lines = [f"✅ **{len(thread_map)}/{total} threads created.** Claude is starting work...\n"]
    for i, spec in enumerate(specs):
        if thread_map.get(i):
            nav_lines.append(f"<#{thread_map[i]}>")
    await dh.send_message(channel_id, "\n".join(nav_lines))

    # ── Phase 2: Run Claude in each destination ───────────────────────────────
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
        print(f"[bulk] starting Claude for #{spec['index']} {spec['name']}")

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

async def handle_message(data: dict):
    channel_id = data.get("channel_id", "")
    content = (data.get("content") or "").strip()
    author = data.get("author", {})
    user_id = author.get("id", "")

    # Ignore bots
    if author.get("bot"):
        return

    # Quick "continue" shorthand for plain messages
    if content.lower() in ("continue", "c", "go", "keep going"):
        sess = sess_store.get_active_for_channel(channel_id)
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
                    )
                    await dh.send_message_chunks(channel_id, result)
                except claude_exec.TurnLimitReached as e:
                    if e.partial_result:
                        await dh.send_message_chunks(channel_id, e.partial_result)
                    await dh.send_message(channel_id, "⚠️ Step limit reached again. Say `continue` or use `/claude auto`.")
                except Exception as e:
                    await dh.send_message(channel_id, f"❌ Error: {str(e)[:200]}")
                return
        # Fall through to normal handling if no session

    # Interruption: "stop" or "cancel" cancels the running Claude task + auto-continue + bulk
    if content.lower() in ("stop", "cancel", "s"):
        sess = sess_store.get_active_for_channel(channel_id)
        if sess:
            claude_exec.cancel_session(sess["id"])
            try:
                from commands.claude_cmd import _auto_continue, _bulk_cancel
                _auto_continue.pop(sess["id"], None)
                _bulk_cancel[channel_id] = True
            except ImportError:
                pass
            await dh.send_message(channel_id, "⛔ Stopping after current step (auto-continue/bulk also cancelled)...")
        return

    # Only respond if a project is active for this channel
    proj = proj_store.get_by_channel(channel_id)
    if not proj:
        # Check if this is a thread with an active session (from /claude thread or /claude bulk)
        thread_sess = sess_store.get_active_for_channel(channel_id)
        if thread_sess and thread_sess.get("project_name"):
            proj = proj_store.get(thread_sess["project_name"])
        if not proj:
            all_projects = proj_store.list_all()
            if all_projects and content:
                names = ", ".join(f"`{p['name']}`" for p in all_projects)
                await dh.send_message(channel_id,
                    f"No active project in this channel.\nAvailable: {names}\nUse `/project use <name>` to select one."
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

    # ── Casual message detection — don't run Claude agent on greetings/chitchat ──
    if content and not image_data and not text_file_content and len(content) < 60:
        _casual = {
            "hello", "hi", "hey", "sup", "yo", "hiya", "howdy",
            "how are you", "how r u", "how are u", "what's up", "whats up",
            "good morning", "good evening", "good afternoon", "good night",
            "thanks", "thank you", "ty", "thx", "ok", "okay", "cool", "nice",
            "great", "awesome", "perfect", "sounds good", "got it", "noted",
            "lol", "haha", "😂", "👍", "🙏",
        }
        _stripped = content.lower().strip().rstrip("!?.").strip()
        if _stripped in _casual or (_stripped.startswith(("hi ", "hey ", "hello ")) and len(_stripped) < 30):
            await dh.send_message(channel_id,
                f"👋 Hey! I'm ready to work on **{proj['name']}**. What would you like me to build or fix?"
            )
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

    await dh.send_typing(channel_id)

    sess = sess_store.get_active_for_channel(channel_id)
    if not sess:
        sess = sess_store.create(proj["name"], channel_id, user_id)
    # Auto-close stale sessions older than 30 minutes to prevent history bleed
    else:
        import time as _time
        updated = sess.get("updated_at") or sess.get("created_at") or ""
        try:
            import datetime
            age = (datetime.datetime.utcnow() - datetime.datetime.fromisoformat(updated.replace("Z",""))).total_seconds()
            if age > 1800:  # 30 min
                sess_store.close(sess["id"])
                sess = sess_store.create(proj["name"], channel_id, user_id)
                print(f"[session] auto-closed stale session, new: {sess['id']}")
        except Exception:
            pass

    progress_queue = asyncio.Queue()
    def on_progress(msg: str):
        print(f"[claude] {msg}")
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

    typing_task = asyncio.create_task(send_typing_loop())
    try:
        result = await claude_exec.run(
            session_id=sess["id"],
            prompt=prompt,
            project_path=proj["path"],
            progress_cb=on_progress,
            image_data=image_data,
            image_media_type=image_media_type,
            channel_id=channel_id,
        )
    except claude_exec.TurnLimitReached as e:
        typing_task.cancel()
        if e.partial_result:
            await dh.send_message_chunks(channel_id, e.partial_result)
        await dh.send_message(channel_id,
            "⚠️ **Step limit reached (20 steps).**\n"
            "Say `continue` to keep going, or use `/claude limit` to increase the limit."
        )
        return
    except Exception as e:
        import traceback
        print(f"[!] handle_message error: {e}\n{traceback.format_exc()}")
        typing_task.cancel()
        await dh.send_message(channel_id, f"❌ Error: `{str(e)[:200]}`")
        return
    finally:
        typing_task.cancel()

    await dh.send_message_chunks(channel_id, result)


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


async def main():
    print("[*] Starting ProjectExo...")
    while True:
        try:
            await gateway_loop()
        except Exception as e:
            print(f"[!] Gateway error: {e} — reconnecting in 5s")
            await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(main())
