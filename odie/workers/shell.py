"""A Worker's run_shell (security reviews, 18-19 Nov 2026): the chat's shell rules on top (odie.workers.worker's guard),
and underneath every command:
  - the default-deny sandbox (odie.workers.sandbox): reads the system, the toolchains, its own folder and the folders
    the owner named for the job; writes only its own folder; no network at all (web reads go through the Worker's web
    tools, never its shell);
  - its own process group, and when the command returns, every process still running in the job's sandbox is killed,
    found by the sandbox itself (sandbox.processes_in), so a child that left the group (setsid), dropped its
    environment and left the folder still goes;
  - the same sweep when the job is stopped or failed, its budget runs out, Odie shuts down or its personality is
    deleted (kill_job).
Output is capped at OUTPUT_CAP and a command at TIMEOUT_S; a command runs in the job's folder, or inside a folder the
owner named for the job."""
from __future__ import annotations

import asyncio
import os
import signal
from pathlib import Path

from google.adk.tools import FunctionTool

from odie.workers import sandbox

OUTPUT_CAP = 8000
TIMEOUT_S = 300  # one command; the job as a whole has its 45 minutes
SWEEP_ROUNDS = 10
_GROUPS: dict[str, set[int]] = {}  # job id -> the process groups its commands are running now
_FOLDERS: dict[str, Path] = {}  # job id -> its folder, for the sweep


def _kill_group(pgid: int) -> None:
    """Stops a process group, every process in it; one that is gone already, or that macOS won't signal, is fine."""
    try:
        os.killpg(pgid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def records_of(folder: Path) -> Path:
    """Odie's own record folder for a job, beside its folder and outside every sandbox (jobs/.<name>.odie): the
    sweep's "beside" place and where a test's output log is written."""
    return folder.parent / f".{folder.name}.odie"


def sweep(folder: Path) -> int:
    """Kills every process running in this job's sandbox, again until none is left (a process may fork while it
    dies). Returns how many were killed."""
    killed = 0
    beside = records_of(folder)
    for _ in range(SWEEP_ROUNDS):
        found = sandbox.processes_in(folder, beside)
        if not found:
            break
        for pid in found:
            try:
                os.kill(pid, signal.SIGKILL)
                killed += 1
            except (ProcessLookupError, PermissionError):
                pass
    return killed


def kill_job(job_id: str, folder: Path | None = None) -> int:
    """Stops everything this job's commands started: its running process groups, then the sweep of its sandbox.
    Returns how many process groups were running."""
    groups = _GROUPS.pop(job_id, set())
    for pgid in groups:
        _kill_group(pgid)
    ran_commands = job_id in _FOLDERS
    if folder is None:
        folder = _FOLDERS.get(job_id)
    if folder is not None and sandbox.available() and (ran_commands or folder_ran_commands(folder)):
        sweep(folder)
    _FOLDERS.pop(job_id, None)
    return len(groups)


def folder_ran_commands(folder: Path) -> bool:
    """Whether any command ever ran in this job's folder (each one leaves its .home there): a job that never ran one
    has nothing to sweep. After a restart the memory of it is gone, so the folder tells."""
    return (folder / ".home").exists()


def cwd_for(folder: Path, read_dirs: list[str], cwd: str | None) -> Path | None:
    """Where a command runs: its folder when none is named; a named one when it is the folder or inside it, or inside a
    folder the owner named for the job; else None (refused). None -> folder; "src" -> folder/src; "~/Downloads" (not
    named) -> None; "/etc" -> None."""
    if not cwd:
        return folder
    where = Path(cwd).expanduser()
    if not where.is_absolute():
        where = folder / where
    where = where.resolve()
    for allowed in (folder, *(Path(d) for d in read_dirs)):
        root = allowed.resolve()
        if where == root or root in where.parents:
            return where
    return None


def make_worker_shell(store, job) -> FunctionTool:
    read_dirs = list(getattr(job, "read_dirs", None) or [])

    async def run_shell(command: str, cwd: str | None = None) -> str:
        """Run a shell command (zsh) in your own folder. Commands run in a sandbox: they read the system, the toolchains, your folder and any folder the user named for this job, and write only inside your folder. No network from the shell. Output is capped at 8 KB and 5 minutes; anything a command starts in the background stops when it returns."""
        if not sandbox.available():
            return "Not run: this computer has no sandbox for Workers, so a Worker runs no commands here."
        where = cwd_for(job.folder, read_dirs, cwd)
        if where is None or not where.is_dir():
            return f"Not run: {cwd} is neither your folder nor a folder the user named for this job."
        argv = sandbox.command(["/bin/zsh", "-c", command], job.folder, read_dirs=read_dirs)
        _FOLDERS[job.id] = job.folder
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
            _kill_group(proc.pid)
            _GROUPS.get(job.id, set()).discard(proc.pid)
            sweep(job.folder)  # whatever it left running, in its group or not, stops with it (cancel included)
        text = b"".join(chunks).decode(errors="replace")
        if timed_out:
            text += f"\n[stopped after {TIMEOUT_S} seconds]"
        if proc.returncode and not (truncated or timed_out):
            text = f"(exit {proc.returncode})\n{text}"
        if len(text) > OUTPUT_CAP:
            text = text[: OUTPUT_CAP - 1] + "…"
        return text

    return FunctionTool(run_shell)
