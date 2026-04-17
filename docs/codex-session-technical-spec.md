# Codex Session Technical Spec

## Objective

Turn the current Discord bot into a Codex-native session manager that runs continuously on a single Ubuntu VPS and is friendly to small-server users who want SSH, GitHub, and Cloudflare control without AWS-style orchestration.

## Current State

- `layers/codex_exec.py` now backs the runtime and persists Codex thread IDs per Discord session.
- the runtime can now recover from a dead Codex backend thread by clearing the stale backend session, rebuilding context from stored transcript history, and starting a fresh backend thread
- `storage/sessions.py` now persists transcript messages instead of keeping history in memory only
- Codex now has first-class local tools for project/session/history control and Discord send/schedule actions through `tools/pexo_context.py` and `tools/pexo_discord.py`
- `layers/claude_exec.py` is now a compatibility wrapper so older imports keep working during the `/codex` rollout.
- Session persistence already exists in `storage/sessions.py`.
- Server, deploy, GitHub, and Cloudflare primitives already exist in `layers/ssh_layer.py`, `storage/servers.py`, `layers/cloudflare_layer.py`, and `tools/pexo_github.py`.
- The bot now supports native Discord message scheduling and thread creation helpers through a persistent job table plus a background dispatch loop.

## Target Architecture

### 1. Codex execution backend

Create `layers/codex_exec.py` and move all agent execution behind a backend interface. The new layer should:

- launch Codex via `codex exec` or `codex resume`
- persist Codex session IDs alongside Discord channel IDs
- stream partial progress, shell commands, and file-change summaries back to Discord
- support multiple concurrent sessions with cancellation and resume

### 2. Session supervisor

Add a long-lived session manager that keeps Codex runs isolated per Discord channel or thread. The root project flow now reuses one main session per project, while thread/bulk jobs still use separate thread sessions. Each session should track:

- Discord channel/thread
- project path
- Codex session ID
- active task state
- last tool call / file change summary

### 3. Remote server operations

Reuse the existing SSH and port allocation layers, but expose them to Codex as first-class tools. Codex should be able to:

- inspect active services and allocated ports
- pick a free port
- deploy or restart an app on the VPS
- create or update a Cloudflare Tunnel for that app

### 4. GitHub operations

Replace narrow repo-only wrappers with a broader GitHub path centered on `gh` plus the native Codex GitHub app where available. Required flows:

- create repos, branches, commits, and PRs
- inspect PRs and review comments
- report changed files and tool activity back into Discord

## Discord UX Requirements

- `/codex ask`, `/codex continue`, `/codex stop`, `/codex sessions`, `/codex status`
- `/discord send`, `/discord schedule`, `/discord jobs`, `/discord cancel`
- `/session history` and Codex-initiated transcript inspection through `pexo_context`
- threaded session mode for parallel jobs
- clear progress events: command started, file edited, deploy started, tunnel attached, PR opened
- summary messages that stay readable in Discord, not raw log spam

## Deployment Model

Target a single Ubuntu host first. Use systemd for:

- `codex-session.service` for the Discord bot
- optional per-project app services
- optional per-project `cloudflared` services

Avoid Lambda, queues, and managed workflow dependencies in phase 1.

## Security Changes

- stop tracking `.env`, `.storage_key`, and populated `data/*.csv`
- rotate the existing GitHub and Cloudflare tokens before any public push
- prefer least-privilege GitHub and Cloudflare credentials
- store remote server auth via encrypted local storage or environment injection only

## Delivery Phases

1. Done: publish sanitized repo, README, installer, and this spec.
2. Done: introduce the `codex_exec.py` backend and Codex session persistence.
3. Done: migrate core Discord commands from `/claude` to `/codex` while keeping a legacy alias.
4. Done: add session transcript persistence, backend-thread recovery, project/session context tools, and native Discord scheduling helpers.
5. Next: richer Discord event reporting for tool calls, diffs, deploys, and PRs.
6. Next: broader app integrations and stronger multi-session supervision for long parallel runs.
