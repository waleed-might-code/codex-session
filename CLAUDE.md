# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

ProjectExo is a Discord bot that serves as an AI-powered full-stack development workspace. Users interact via Discord slash commands; the bot delegates to Claude (Anthropic API) as an agent that can read/write files and run shell commands inside registered local projects. It also manages SSH deployment servers and Cloudflare tunnels/pages.

The bot connects to Discord using a raw WebSocket Gateway (no discord.py library) and handles slash command interactions directly via HTTP.

## Running the Bot

```bash
# Install dependencies
pip install -r requirements.txt

# Install Playwright browsers (required for preview/screenshot commands)
playwright install chromium

# Copy and fill in environment variables
cp .env.example .env

# Register slash commands with Discord (run once per guild, or after command schema changes)
python register_commands.py

# Start the bot
python bot.py
```

## Environment Configuration (`.env`)

Key variables:
- `DISCORD_BOT_TOKEN` — required; also used to derive the application ID
- `DISCORD_GUILD_ID` — guild to register slash commands against
- `ANTHROPIC_API_KEY` — used by `layers/claude_exec.py`
- `CLAUDE_MODEL` — defaults to `claude-sonnet-4-6`
- `DEFAULT_HOST` / `DEFAULT_HOST_USER` / `DEFAULT_HOST_PASSWORD` — seeds the default SSH server on startup
- `STORAGE_DIR` — directory for CSV data files (default: `data/`)
- `ENCRYPTION_KEY` — Fernet key for credential encryption; auto-generated to `.storage_key` if blank
- `ALLOWED_PROJECT_ROOTS` — comma-separated path prefixes that projects may live under
- `COMMAND_TIMEOUT` — shell command timeout in seconds (default: 120)

## Architecture

### Entry Point: `bot.py`
Connects to `wss://gateway.discord.gg` directly (no library). On `INTERACTION_CREATE` (type 2 = slash command), dispatches to `route()`, which defers the interaction immediately, then calls the appropriate command handler. All handlers are `async` and run as `asyncio` tasks.

### Command Handlers (`commands/`)
Each file exports a `handle(sub, sub_opts, token, ...)` coroutine. Subcommand name and its options are extracted by `dh.subcommand()` / `dh.opts()` from `utils/discord_helpers.py`. Commands send results back via `dh.followup()` or `dh.followup_chunks()`.

| File | Commands |
|---|---|
| `project.py` | `/project` — register and activate local projects per channel |
| `files.py` | `/files`, `/file` — browse and read project files |
| `claude_cmd.py` | `/claude` — run Claude agent, continue sessions, diff, status |
| `session_cmd.py` | `/session` — list/resume/close Claude sessions |
| `preview_cmd.py` | `/preview` — Playwright browser screenshots and dev server |
| `server_cmd.py` | `/server` — SSH server registry, bootstrap, logs |
| `cloudflare_cmd.py` | `/cloudflare` — Cloudflare tunnel/pages management |
| `deploy_cmd.py` | `/deploy` — SSH backend deploy + Cloudflare Pages frontend |

### Layers (`layers/`)
Business logic separated from Discord plumbing:

- **`claude_exec.py`** — Anthropic API agent loop. Maintains per-session message history. Tools: `bash`, `read_file`, `write_file`, `list_directory`, `search_files`. Claude runs in a thread (`run_in_executor`) to avoid blocking the event loop. Max 20 turns per invocation.
- **`ssh_layer.py`** — Paramiko-based SSH: run commands, SFTP upload, find free ports, deploy systemd services, bootstrap a `deploy` user with RSA key.
- **`browser_layer.py`** — Playwright async: start a local dev server, take desktop/mobile screenshots.
- **`cloudflare_layer.py`** — Cloudflare API: manage tunnels, hostnames, deploy to Cloudflare Pages.

### Storage (`storage/`)
- **`base.py`** — Thread-safe CSV storage via pandas. Each table = one CSV under `STORAGE_DIR/`. Writes are atomic (temp file + `shutil.move`). Per-file threading locks.
- **`projects.py`** — Project registry; channel→project mapping.
- **`sessions.py`** — Claude session history (JSON-serialized message arrays stored in CSV).
- **`servers.py`** — SSH server registry with encrypted credentials; service port assignments.
- **`cloudflare.py`** — Cloudflare token, tunnel, and Pages records.

### Utils (`utils/`)
- **`crypto.py`** — Fernet encryption/decryption for credentials stored in CSVs. Key auto-generated to `.storage_key` on first run.
- **`security.py`** — Path traversal prevention (`safe_relative`, `validate_project_path`), dangerous shell pattern detection, output truncation, Discord message chunking.
- **`discord_helpers.py`** — All Discord HTTP calls (defer, followup, send image, create thread). `opts()` flattens interaction options; `subcommand()` extracts sub name + options.

### Skills (`skills/`)
- **`make_live.py`** — Orchestrates the `/make-live` command: Claude code review → Playwright screenshot → SSH backend deploy → Cloudflare tunnel → Cloudflare Pages frontend deploy → summary.

## Key Patterns

- **Channel = workspace context**: active project and Claude session are scoped to `channel_id`.
- **Credential encryption**: all SSH passwords and private keys are encrypted with Fernet before storing in CSVs. The key lives in `.storage_key` (chmod 600).
- **Long output**: Discord messages cap at 2000 chars. Use `dh.followup_chunks()` for large output and `dh.send_image_to_channel()` for screenshots.
- **Slash command registration**: after adding/changing any command in `register_commands.py`, re-run `python register_commands.py` to push to Discord (guild commands propagate instantly).
- **No reconnect on session resume**: the Gateway loop breaks on op 7/9 and `main()` reconnects automatically.
