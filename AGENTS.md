# Repository Guidelines

## Project Structure & Module Organization
`bot.py` is the main Discord Gateway entry point and routes slash commands to `commands/`. Keep command-specific behavior in the matching module, such as `commands/project.py` or `commands/test_cmd.py`. Shared integrations live in `layers/` for Claude, browser, SSH, and Cloudflare workflows; persistent CSV-backed state lives in `storage/`; small helpers belong in `utils/`. Runtime data is stored under `data/`, and example local apps used by the bot sit in `projects/`.

## Build, Test, and Development Commands
Set up the environment with `pip install -r requirements.txt` and install browser binaries with `playwright install chromium`. Register slash commands after schema changes with `python register_commands.py`, then start the bot with `python bot.py`. Current tests are script-driven rather than `pytest`-based:

- `python test_bulk_flow.py` runs the mocked end-to-end bulk flow checks.
- `python test_bulk_cli.py parse-only` validates spec parsing without calling Claude.
- `python test_bulk_cli.py single` exercises one CLI-driven Claude run when the required env vars are configured.

## Coding Style & Naming Conventions
Follow the existing Python style: 4-space indentation, module docstrings, `snake_case` for functions and variables, and short async handlers shaped like `handle(sub, sub_opts, token, ...)`. Keep slash command definitions in `register_commands.py` aligned with the handler logic they trigger. Prefer small focused modules over large cross-cutting edits, and reuse helpers from `utils/` or `storage/` before adding new abstractions.

## Testing Guidelines
Name new tests as `test_*.py` in the repository root unless a clearer placement is needed. Favor mocked integration tests like `test_bulk_flow.py` for Discord, SSH, browser, or API-heavy code, and avoid live network calls in default test runs. For command changes, verify both the registration schema and the handler path you touched.

## Commit & Pull Request Guidelines
Git history is minimal (`Initial commit`), so use short imperative commit subjects such as `Add preview console capture`. In pull requests, include the affected slash commands or modules, required env var changes, and exact verification steps. Add screenshots or console snippets for browser, preview, or deployment-related changes.

## Security & Configuration Tips
Start from `.env.example`; do not commit `.env`, `.storage_key`, or populated CSV data. Respect `ALLOWED_PROJECT_ROOTS` and use helpers in `utils/security.py` for path and shell safety when adding file or command features.
