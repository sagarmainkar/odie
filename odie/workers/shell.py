"""A Worker's run_shell (security review, 18 Nov 2026): the chat's shell rules on top (odie.workers.worker's guard),
and underneath every command:
  - the sandbox (odie.workers.sandbox): reads anything but the secret places, writes only in the job's folder, no
    network when the job is tainted;
  - its own process group, killed when the command returns: a background child (`nohup … &`) never outlives it;
  - every group the job has running is known (_GROUPS), so stopping or failing the job, its budget running out, a
    shutdown or its personality's deletion kills them all (kill_job).
Output is capped at OUTPUT_CAP and a command at TIMEOUT_S; the cwd is the job's folder unless it names another under
the user's home (where it may read, not write)."""
from __future__ import annotations

import asyncio
import os
import signal
from pathlib import Path

from google.adk.tools import FunctionTool

from odie.workers import sandbox

OUTPUT_CAP = 8000
TIMEOUT_S = 300  # one command; the job as a whole has its 45 minutes
_GROUPS: dict[str, set[int]] = {}  # job id -> the process groups its commands are running now


def _kill_group(pgid: int) -> None:
    """Stops a process group, every process in it; one that is gone already, or that macOS won't signal, is fine."""
    try:
        os.killpg(pgid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def kill_job(job_id: str) -> int:
    """Stops everything this job's commands are running now. Returns how many process groups were stopped."""
    groups = _GROUPS.pop(job_id, set())
    for pgid in groups:
        _kill_group(pgid)
    return len(groups)


def cwd_for(folder: Path, cwd: str | None) -> Path | None:
    """Where a command runs: its folder when none is named; a named one when it is the folder, inside it, or under the
    user's home; else None (refused). None -> folder; "~/Downloads" -> it; "/etc" -> None."""
    if not cwd:
        return folder
    where = Path(cwd).expanduser().resolve()
    home = Path.home().resolve()
    job = folder.resolve()
    if where == job or job in where.parents or where == home or home in where.parents:
        return where
    return None


def make_worker_shell(store, job) -> FunctionTool:
    async def run_shell(command: str, cwd: str | None = None) -> str:
        """Run a shell command (zsh) in your own folder, or in a folder under the user's home that you name as cwd. Commands run in a sandbox: you can read the user's ordinary files and write only inside your folder. Output is capped at 8 KB and 5 minutes; anything a command starts in the background stops when it returns."""
        if not sandbox.available():
            return "Not run: this computer has no sandbox for Workers, so a Worker runs no commands here."
        where = cwd_for(job.folder, cwd)
        if where is None or not where.is_dir():
            return f"Not run: {cwd} is not a folder under the user's home."
        argv = sandbox.command(["/bin/zsh", "-c", command], job.folder, offline=bool(job.taint))
        try:
            proc = await asyncio.create_subprocess_exec(*argv, cwd=str(where), env=sandbox.env(job.folder),
                                                        stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
                                                        stderr=asyncio.subprocess.STDOUT, start_new_session=True)
        except OSError as e:
            return f"Could not run it: {e}"
        _GROUPS.setdefault(job.id, set()).add(proc.pid)
        chunks: list[bytes] = []
        size = 0
        timed_out = truncated = False
        try:
            async def read() -> None:
                nonlocal size, truncated
                assert proc.stdout is not None
                while True:
                    chunk = await proc.stdout.read(4096)
                    if not chunk:
                        return
                    chunks.append(chunk)
                    size += len(chunk)
                    if size > OUTPUT_CAP:
                        truncated = True
                        return
            try:
                await asyncio.wait_for(read(), TIMEOUT_S)
            except TimeoutError:
                timed_out = True
            if truncated or timed_out:
                _kill_group(proc.pid)
            await proc.wait()
        finally:
            _kill_group(proc.pid)  # whatever it left running in the background stops with it (cancel included)
            _GROUPS.get(job.id, set()).discard(proc.pid)
        text = b"".join(chunks).decode(errors="replace")
        if timed_out:
            text += f"\n[stopped after {TIMEOUT_S} seconds]"
        if proc.returncode and not (truncated or timed_out):
            text = f"(exit {proc.returncode})\n{text}"
        if len(text) > OUTPUT_CAP:
            text = text[: OUTPUT_CAP - 1] + "…"
        return text

    return FunctionTool(run_shell)
