"""Updating Odie from the app: is there a newer version on origin, and start `odie update` without leaving the phone.

The command (odie/cli.py: fetch, build, restart, roll back when unhealthy) stays the one way the live copy changes.
This module only asks git whether a newer release (or origin/<branch>) is there, and starts that command detached so it outlives
the server it restarts. The app watches /api/health for the version to change, then reloads itself.
"""
from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from odie.releases import follows_releases, newest_release, version_label

log = logging.getLogger(__name__)

CODE_DIR = Path(__file__).resolve().parent.parent  # the checkout this server runs from
CHECK_EVERY = 600  # seconds a check's answer is reused: the app asks hourly, and on every return to it

_version: str | None = None
_last_check: dict[str, Any] | None = None
_started: subprocess.Popen | None = None


def install():
    from odie.cli import install_from
    return install_from(os.environ)


def can_update() -> bool:
    """Whether `odie update` would change the code this server runs: it runs from the installed copy (~/.odie/app),
    and that copy is a git checkout. Example: launchd's Odie in ~/.odie/app -> True (the button shows);
    `uv run odie serve` from the work folder, or the demo copy -> False (no button)."""
    inst = install()
    return CODE_DIR == inst.app.resolve() and (inst.app / ".git").exists()


def version() -> str:
    """The version this server runs, read once: "0.1.0" on a release, "0.1.0+3 (ce33450)" three commits after it,
    "ce33450" before the first release; "unknown" where there's no git (a snapshot)."""
    global _version
    if _version is None:
        try:
            ran = subprocess.run(["git", "-C", str(CODE_DIR), "describe", "--tags", "--always"],
                                 capture_output=True, text=True, timeout=10, check=False)
            _version = version_label(ran.stdout) if ran.returncode == 0 else "unknown"
        except (OSError, subprocess.TimeoutExpired):
            _version = "unknown"
    return _version


async def _git(*args: str, timeout: float = 30) -> str:
    proc = await asyncio.create_subprocess_exec("git", "-C", str(CODE_DIR), *args,
                                                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout)
    except TimeoutError:
        proc.kill()
        raise RuntimeError(f"git {args[0]} took more than {timeout:.0f}s") from None
    if proc.returncode != 0:
        raise RuntimeError(err.decode().strip() or f"git {args[0]} failed")
    return out.decode().strip()


def is_fresh(last: dict[str, Any] | None, now: float, force: bool) -> bool:
    """Whether the last answer still serves. Example: checked 3 minutes ago, not forced -> True (no fetch);
    checked 11 minutes ago -> False; "Check now" (force) -> False, even a minute later; never checked -> False."""
    if last is None or force:
        return False
    return now - last["checked_at"] < CHECK_EVERY


async def check(force: bool = False) -> dict[str, Any]:
    """{"current", "latest", "behind", "checked_at"}: a fetch and a compare, reused for CHECK_EVERY seconds."""
    global _last_check
    if is_fresh(_last_check, time.time(), force):
        return _last_check  # type: ignore[return-value]
    branch = install().branch
    await _git("fetch", "-q", "--tags", "origin", timeout=60)
    current = await _git("rev-parse", "HEAD")
    if follows_releases(branch):
        newest = newest_release((await _git("tag", "-l", "v*")).split())
        latest = current  # no release yet: nothing to update to
        if newest:
            latest = await _git("rev-parse", f"{newest}^{{commit}}")
    else:
        latest = await _git("rev-parse", f"origin/{branch}")
    _last_check = {"current": current[:7], "latest": latest[:7], "behind": latest != current, "checked_at": time.time()}
    return _last_check


def running() -> bool:
    """Whether an update this server started is still going (the command exits when Odie is healthy again, or
    rolled back)."""
    return _started is not None and _started.poll() is None


def start() -> int:
    """Starts `odie update` with its output in logs/update.log and returns its pid. Its own session, so the restart
    it does to this server doesn't take it down too (launchd ends the service's process group)."""
    global _started
    inst = install()
    inst.logs.mkdir(parents=True, exist_ok=True)
    out = open(inst.update_log, "ab")  # noqa: SIM115  (the child owns it)
    _started = subprocess.Popen([sys.executable, "-P", "-m", "odie.cli", "update"], cwd=inst.app,
                                stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True)
    log.info("odie update started (pid %s) from %s", _started.pid, version())
    return _started.pid
