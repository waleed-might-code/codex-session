"""
Markdown-based skills loader.
Drop a .md file in skills/ and it becomes a runnable prompt template.
Usage in Discord: start message with !<skill_name> [args]
  e.g. !frontend create a landing page
       !review
       !upgrade focus on the API
"""
import os
from pathlib import Path

SKILLS_DIR = Path(__file__).parent


def list_skills() -> list[str]:
    return [p.stem for p in SKILLS_DIR.glob("*.md")]


def load_skill(name: str) -> str | None:
    p = SKILLS_DIR / f"{name}.md"
    if not p.exists():
        return None
    content = p.read_text(errors="replace")
    return _resolve_includes(content)


def _resolve_includes(content: str) -> str:
    """Replace {{include: filename}} with the content of skills/filename.md"""
    import re
    def replacer(m):
        fname = m.group(1).strip()
        if not fname.endswith(".md"):
            fname += ".md"
        inc = SKILLS_DIR / fname
        if inc.exists():
            return inc.read_text(errors="replace").strip()
        return m.group(0)  # leave unchanged if file not found
    return re.sub(r"\{\{include:\s*([^}]+)\}\}", replacer, content)


def resolve_prompt(message: str) -> str:
    """
    If message starts with !<skill_name>, replace with the skill's prompt template.
    Remaining text after the skill name is appended as context.
    Returns the original message unchanged if no skill matches.
    """
    if not message.startswith("!"):
        return message
    parts = message[1:].split(None, 1)
    skill_name = parts[0].lower()
    extra = parts[1] if len(parts) > 1 else ""
    template = load_skill(skill_name)
    if template is None:
        return message
    return template.strip() + (f"\n\nAdditional context: {extra}" if extra else "")
