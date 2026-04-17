"""
Legacy compatibility wrapper.

The runtime backend has moved to `layers.codex_exec`. Keep this module so older
imports continue to work while the command surface migrates from `/claude` to
`/codex`.
"""

from layers.codex_exec import *  # noqa: F401,F403
