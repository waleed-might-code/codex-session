# Codex Session

Codex Session is a Discord-first coding workspace for people running a plain Ubuntu VPS from Contabo, Linode, Hetzner, or similar providers. The goal is simple: keep long-running Codex coding sessions alive on your server, prompt them from Discord, and let the bot manage GitHub, SSH deploys, ports, and Cloudflare tunnels without forcing you into AWS-heavy infrastructure.

This repository currently ships the working ProjectExo bot codebase plus a concrete migration plan to replace the Anthropic-specific execution layer with a Codex-native backend. The current runtime is still Claude-centered; the Codex migration work is specified in [docs/codex-session-technical-spec.md](docs/codex-session-technical-spec.md).

## What You Get

- Discord slash commands for project, file, session, preview, deploy, test, server, GitHub, and Cloudflare workflows
- SSH-based service deployment and port tracking for a single VPS
- Cloudflare Tunnel and Pages helpers for exposing apps safely
- Local GitHub credential storage and repo automation hooks
- A Codex migration plan aimed at always-on multi-session server workflows

## Quick Start

Once this repo is on GitHub, the intended one-line bootstrap will be:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/waleed-might-code/codex-session/main/scripts/install.sh)
```

Manual setup works too:

```bash
git clone https://github.com/waleed-might-code/codex-session.git
cd codex-session
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
cp .env.example .env
python register_commands.py
python bot.py
```

## Configuration

Fill `.env` with your Discord bot token, guild ID, and backend credentials before starting the service. Keep `.env`, `.storage_key`, and `data/*.csv` private. The install script creates `/opt/codex-session`, a virtualenv, and a systemd unit so the bot can stay alive across reboots.

## Status

- `main`: sanitized baseline of the working bot
- Feature PRs: README/install polish and the Codex migration technical spec

If you want the actual Codex backend implementation, start with the spec in `docs/` and replace `layers/claude_exec.py` with a `codex_exec.py` session runner instead of extending the existing Anthropic-specific layer further.
