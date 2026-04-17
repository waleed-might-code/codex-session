# Codex Session

Codex Session is a Discord-first coding workspace for people running a plain Ubuntu VPS from Contabo, Linode, Hetzner, or similar providers. The goal is simple: keep long-running Codex coding sessions alive on your server, prompt them from Discord, and let the bot manage GitHub, SSH deploys, ports, and Cloudflare tunnels without forcing you into AWS-heavy infrastructure.

This repository now runs on the local Codex CLI backend through [layers/codex_exec.py](layers/codex_exec.py). The older `/claude` command name is kept as a legacy alias, but `/codex` is the primary surface going forward. The broader rollout and remaining follow-up work are documented in [docs/codex-session-technical-spec.md](docs/codex-session-technical-spec.md).

## What You Get

- Discord slash commands for project, file, session, preview, deploy, test, server, GitHub, and Cloudflare workflows
- Codex-backed persistent sessions with resume support through the local Codex CLI
- SSH-based service deployment and port tracking for a single VPS
- Cloudflare Tunnel and Pages helpers for exposing apps safely
- Local GitHub credential storage and repo automation hooks
- A concrete migration/spec document for the remaining `/codex` rollout work

## Quick Start

Once this repo is on GitHub, the intended one-line bootstrap will be:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/waleed-might-code/codex-session/main/scripts/install.sh)
```

Prerequisites before starting the bot:

- `codex` must already be installed on the server
- the service user must already be authenticated with Codex, typically via `codex login`

Manual setup works too:

```bash
git clone https://github.com/waleed-might-code/codex-session.git
cd codex-session
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
cp .env.example .env
codex login
python register_commands.py
python bot.py
```

## Configuration

Fill `.env` with your Discord bot token, guild ID, and backend credentials before starting the service. Keep `.env`, `.storage_key`, and `data/*.csv` private. The install script creates `/opt/codex-session`, a virtualenv, and a systemd unit so the bot can stay alive across reboots. If you run the service under a dedicated user, make sure that same user has a working Codex login or a writable `CODEX_HOME`.

## Status

- `main`: sanitized Codex-backed bot runtime
- `/codex`: primary command surface
- `/claude`: legacy alias retained for compatibility

The next implementation steps are richer Discord event formatting, stronger multi-session supervision, and rolling the remaining docs/tests fully onto `/codex`.
