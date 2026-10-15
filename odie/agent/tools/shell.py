"""run_shell: commands on this computer, each behind the user's tap unless they allowed shell for 30 min (shell_grant).
Runs as the logged-in user, cwd must be under their home, 60 s, 8 KB of output read incrementally (a runaway command is
killed, process group and all, the moment the cap is hit)."""
from __future__ import annotations

import asyncio
import os
import signal
from pathlib import Path

from google.adk.tools import FunctionTool, ToolContext

OUTPUT_CAP = 8000
TIMEOUT_S = 60
_HOME = str(Path.home())
SHELL_PATH = ":".join([f"{_HOME}/.lmstudio/bin", f"{_HOME}/.local/bin", f"{_HOME}/.cargo/bin", "/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin", "/usr/sbin", "/sbin"])


def make_shell_tool(home: Path | None = None, store=None) -> FunctionTool:
    home = (home or Path.home()).resolve()

    async def run_shell(command: str, cwd: str | None = None, tool_context: ToolContext = None) -> str:
        """Run a shell command on this computer (zsh). The user sees the exact command and directory and approves it first. Use for files, git, scripts, system questions. cwd defaults to their home and must stay under it. Output is capped at 8 KB and 60 seconds."""
        where = Path(cwd).expanduser().resolve() if cwd else home
        if home != where and home not in where.parents:
            return f"Not run: cwd {where} is outside {home}."
        if not where.is_dir():
            return f"Not run: {where} is not a directory."
        try:
            proc = await asyncio.create_subprocess_shell(
                command, cwd=str(where), stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT, executable="/bin/zsh", start_new_session=True,
                env={**os.environ, "PATH": SHELL_PATH})
        except OSError as e:
            return f"Could not run it: {e}"

        def kill_group() -> None:
            try:
                os.killpg(proc.pid, signal.SIGKILL)  # pipelines and background children too
            except ProcessLookupError:
                pass

        chunks: list[bytes] = []
        size = 0
        truncated = timed_out = False
        loop = asyncio.get_running_loop()
        deadline = loop.time() + TIMEOUT_S
        assert proc.stdout is not None
        try:
            while True:
                left = deadline - loop.time()
                if left <= 0:
                    timed_out = True
                    break
                chunk = await asyncio.wait_for(proc.stdout.read(4096), left)
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
                if size > OUTPUT_CAP:
                    truncated = True
                    break
        except asyncio.TimeoutError:
            timed_out = True
        if truncated or timed_out:
            kill_group()
        try:
            await asyncio.wait_for(proc.wait(), 5)
        except asyncio.TimeoutError:
            kill_group()
        text = b"".join(chunks).decode(errors="replace")
        if timed_out:
            text += f"\n[stopped after {TIMEOUT_S} seconds]"
        if proc.returncode and not (truncated or timed_out):
            text = f"(exit {proc.returncode})\n{text}"
        return text if len(text) <= OUTPUT_CAP else text[: OUTPUT_CAP - 1] + "…"

    # tool_context is declared above only so ADK hands it to the check (which conversation is asking); the model
    # never sees it. Without a store (tests, eval) every command asks.
    if store is None:
        return FunctionTool(run_shell, require_confirmation=True)
    from odie.agent.shell_grant import make_check
    return FunctionTool(run_shell, require_confirmation=make_check(store))
