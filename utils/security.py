"""
Security helpers: path validation, command sanitization, output truncation.
"""
import os
import re
import shlex

# Loaded from env at import time; fallback to sensible defaults
_ALLOWED_ROOTS = [r.strip() for r in os.getenv("ALLOWED_PROJECT_ROOTS", "/home,/Users,/root,/opt,/tmp").split(",")]
MAX_OUTPUT = int(os.getenv("MAX_OUTPUT_CHARS", "3800"))
CMD_TIMEOUT = int(os.getenv("COMMAND_TIMEOUT", "120"))

# Patterns that must never appear in shell args passed to remote exec
_DANGEROUS = re.compile(r"(;|\|{1,2}|&&|`|\$\(|>\s*/etc|>\s*/bin|rm\s+-rf\s+/)", re.IGNORECASE)


def validate_project_path(path: str) -> str:
    """Raise ValueError if path is outside allowed roots. Returns realpath."""
    real = os.path.realpath(os.path.expanduser(path))
    for root in _ALLOWED_ROOTS:
        if real.startswith(os.path.realpath(root)):
            return real
    raise ValueError(f"Path `{path}` is outside allowed project roots.")


def safe_relative(base: str, relpath: str) -> str:
    """Resolve relpath relative to base and ensure it doesn't escape base."""
    full = os.path.realpath(os.path.join(base, relpath))
    base_real = os.path.realpath(base)
    if not full.startswith(base_real):
        raise ValueError(f"Path traversal detected: `{relpath}`")
    return full


def sanitize_shell_arg(arg: str) -> str:
    """Raise if arg contains dangerous shell patterns."""
    if _DANGEROUS.search(arg):
        raise ValueError(f"Unsafe characters in argument: `{arg}`")
    return arg


def truncate(text: str, limit: int = None) -> str:
    limit = limit or MAX_OUTPUT
    if len(text) <= limit:
        return text
    half = limit // 2
    return text[:half] + f"\n\n… [truncated {len(text) - limit} chars] …\n\n" + text[-half:]


def chunk_message(text: str, size: int = 1900) -> list[str]:
    """Split long text into Discord-safe chunks."""
    lines, chunks, cur = text.splitlines(keepends=True), [], ""
    for line in lines:
        if len(cur) + len(line) > size:
            chunks.append(cur)
            cur = ""
        cur += line
    if cur:
        chunks.append(cur)
    return chunks or [""]
