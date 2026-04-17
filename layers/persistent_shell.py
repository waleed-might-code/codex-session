"""
Persistent bash session per agent session.
Tracks CWD across tool calls so `cd` works correctly between commands.
"""
import os
import subprocess


class PersistentShell:
    def __init__(self, cwd: str, session_id: str):
        self._cwd = os.path.realpath(cwd)
        self._cwd_file = f"/tmp/pexo_cwd_{session_id}"

    def run(self, command: str, timeout: int = 120, extra_env: dict = None) -> str:
        env = {**os.environ, **(extra_env or {})}
        # Wrap command to capture final working directory
        wrapped = f"{command}\npwd -P > {self._cwd_file} 2>/dev/null"
        try:
            result = subprocess.run(
                ["bash", "-c", wrapped],
                capture_output=True, text=True,
                timeout=timeout, env=env, cwd=self._cwd,
            )
            try:
                new_cwd = open(self._cwd_file).read().strip()
                if new_cwd and os.path.isdir(new_cwd):
                    self._cwd = new_cwd
            except Exception:
                pass
            out = result.stdout + result.stderr
            return out.strip() or "(no output)"
        except subprocess.TimeoutExpired:
            return f"[timeout after {timeout}s]"
        except Exception as e:
            return f"[error: {e}]"

    def cleanup(self):
        try:
            os.unlink(self._cwd_file)
        except Exception:
            pass
