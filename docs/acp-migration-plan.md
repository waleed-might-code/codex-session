# ACP Migration Plan

## Goal

Move the Discord bot from a CLI event-stream integration to an agent protocol boundary that is stable enough for long-lived sessions, worker swarms, and Discord-native progress reporting. The target is ACP as the primary runtime transport, with the current CLI path kept only as a fallback during rollout.

## Current Seams

The public branch is still centered on `layers/claude_exec.py`, with Discord ingress in `bot.py` and slash-command flows in `commands/claude_cmd.py`. Session state already exists in `storage/sessions.py`, which is the right place to keep Discord-facing session identity even after the agent transport changes.

Recent local runtime work also exposed the main fragility points of the current `codex exec --json` style approach:

- event parsing is being used as an agent protocol
- process exit codes do not always line up with streamed status events
- session/thread routing can drift when backend session ids go stale
- parent-channel and worker-thread responsibilities are easy to blur
- progress spam and duplicated bot processes create noisy Discord UX

ACP should replace the runtime boundary, not the whole bot. Discord routing, project storage, SSH helpers, Cloudflare helpers, and GitHub flows still belong in this repository.

## Target Architecture

### 1. Runtime abstraction

Add an `AgentRuntime` interface and move `ask`, `continue`, `cancel`, `resume`, `spawn`, and event streaming behind it. The bot should depend on normalized runtime events such as:

- `session_started`
- `turn_started`
- `progress`
- `tool_started`
- `tool_finished`
- `file_changed`
- `artifact_ready`
- `final_message`
- `error`
- `cancelled`

Implement two adapters:

- `CliJsonRuntime` for the current Codex CLI path during migration
- `AcpRuntime` as the target implementation

### 2. Director and worker sessions

General channels should stay director-only. Real work should move into dedicated worker threads, and swarm workers should each get their own thread. The session registry should keep:

- Discord parent channel id
- Discord thread id
- project path
- runtime session id
- worker/manager role
- parent session id
- last event timestamp

### 3. Discord event model

Discord output should be driven by structured runtime events, not raw shell command text. That means one progress message model across single-session, resumed, and spawned-worker flows, with attachment support for screenshots, logs, and videos.

### 4. Worker orchestration

Spawning up to 10 workers should be runtime-native. The manager should be able to reuse, message, wait on, or cancel workers without scraping CLI output or guessing whether a worker is still alive.

## Errors To Avoid

These are the concrete failure modes the ACP migration should eliminate or explicitly guard against:

1. Treating CLI JSONL as the protocol. The current model couples Discord UX to subprocess stdout parsing.
2. Hiding failures behind generic fallbacks. A runtime error should never collapse to `unknown error` when structured error data exists.
3. Relative path drift. Runtime working roots must be absolute and stable across resume, spawn, and attachment flows.
4. Stale backend ids. Session recovery must clear or replace unusable backend ids without leaking work into the wrong thread.
5. Parent-thread leakage. General channels should summarize and delegate; worker threads should do the work.
6. Duplicate process handling. The bot should detect or reject concurrent duplicate consumers before Discord events are double-processed.
7. Hardcoded intent routing. Thread/session/project moves should come from structured state and runtime capabilities, not string triggers alone.
8. Unbounded progress spam. Progress updates need coalescing and a stable event-to-message policy.
9. Test blindness. Discord-level integration tests must cover session creation, thread moves, worker spawn, cancellation, resume, artifact posting, and failure reporting.

## Issue Breakdown

The implementation should be tracked as separate work items:

- `#17` umbrella tracker: adopt ACP as the primary agent runtime transport
- `#15` introduce the runtime interface and ACP adapter
- `#16` migrate session and worker registries to runtime-agnostic state
- `#20` convert Discord updates to structured event rendering
- `#19` move worker swarm control onto runtime-native operations
- `#18` add adversarial Discord integration tests and rollout safeguards

## Rollout

1. Land the runtime abstraction without changing user-facing behavior.
2. Add ACP behind a feature flag and keep the CLI runtime as fallback.
3. Migrate single-session flows first.
4. Migrate worker spawn/reuse/wait/cancel flows next.
5. Remove direct CLI event assumptions from Discord rendering.
6. Only retire the fallback runtime after Discord integration tests pass against real sessions.
