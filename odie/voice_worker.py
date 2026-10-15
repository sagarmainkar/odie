"""Odie's own voice worker: voice_server/ (Kokoro and Maya1 on Apple Silicon, via MLX), started by Odie as a child
process on its own port (ODIE_VOICE_PORT, 8771), restarted if it dies, and stopped with Odie.

- **It dies with its Odie.** It holds one end of a pipe whose other end only its Odie has. When that Odie is gone,
  however it went (a kill -9, a second Ctrl-C), the pipe closes and the worker exits. So a worker left on the port
  belongs to a running Odie, and can be shared.
- **Never someone else's.** Any other service answering on the port is never used.
- **Never in the way.** Without its environment (`uv sync` in voice_server), or if it can't start, local voice is
  simply off and Odie starts as usual."""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import subprocess
import time
from pathlib import Path

import httpx

VOICE_DIR = Path(__file__).resolve().parent.parent / "voice_server"
TITLE = "odie-voice"  # what voice_server/server.py calls itself
log = logging.getLogger("odie.voice")
current: VoiceWorker | None = None  # the running server's worker (set by the app at startup)


def voice_port() -> int:
    return int(os.environ.get("ODIE_VOICE_PORT", "8771"))


class VoiceWorker:
    """A local service Odie starts and keeps: the voice worker, and (odie/embed_worker.py) the embedding service."""
    title = TITLE          # what the service calls itself (its FastAPI title): only that is ever used on the port
    what = "local voice"   # how it's named in log lines and problems
    port_setting = "ODIE_VOICE_PORT"  # the environment setting that moves it to another port

    def __init__(self, folder: Path = VOICE_DIR, port: int | None = None, cmd: list[str] | None = None, log: Path | None = None):
        self.folder = folder
        self.port = port or voice_port()
        self._custom = cmd is not None  # tests bring their own
        self.cmd = cmd or [str(folder / ".venv" / "bin" / "uvicorn"), "server:app", "--host", "127.0.0.1", "--port", str(self.port)]
        self.log_path = log
        self.proc: subprocess.Popen | None = None
        self.problem = ""
        self.spawned = 0
        self._parent_w: int | None = None  # our end of the pipe the worker watches
        self._lock = asyncio.Lock()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def installed(self) -> bool:
        return self._custom or (self.folder / ".venv" / "bin" / "uvicorn").exists()

    async def _who(self) -> str | None:
        """The name of whatever answers on the port; None only if nothing does."""
        try:
            async with httpx.AsyncClient(timeout=2) as c:
                r = await c.get(f"{self.url}/openapi.json")
        except (httpx.ConnectError, httpx.ConnectTimeout):
            return None
        except httpx.HTTPError:
            return "something that doesn't answer properly"
        try:
            return str((r.json().get("info") or {}).get("title") or "something else")
        except (ValueError, AttributeError):
            return "something else"

    def environment(self) -> dict[str, str]:
        """What the service needs besides Odie's own environment (a subclass says; the voice worker needs nothing)."""
        return {}

    async def healthy(self) -> bool:
        if await self._who() != self.title:
            return False
        try:
            async with httpx.AsyncClient(timeout=2) as c:
                return (await c.get(f"{self.url}/health")).status_code == 200
        except httpx.HTTPError:
            return False

    def _off(self, why: str) -> None:
        if why != self.problem:  # said once, not on every request
            log.warning("%s is off: %s", self.what, why)
        self.problem = why

    async def start(self) -> None:
        async with self._lock:
            await self._start()

    async def _start(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            return  # ours is running (perhaps still starting)
        who = await self._who()
        if who == self.title:
            return  # an Odie worker is already there (another running Odie's): share it
        if who is not None:
            return self._off(f"port {self.port} is taken by {who}; set {self.port_setting} to a free port")
        if not self.installed:
            return self._off(f"{self.what} isn't set up: run `uv sync` in {self.folder}")
        r = w = None
        try:
            r, w = os.pipe()
            out = open(self.log_path, "ab") if self.log_path else subprocess.DEVNULL  # noqa: SIM115 (the child keeps it)
            self.proc = subprocess.Popen(self.cmd, cwd=None if self._custom else self.folder, stdout=out, stderr=subprocess.STDOUT,
                                         start_new_session=True, pass_fds=(r,), env={**os.environ, **self.environment(), "ODIE_PARENT_FD": str(r)})
        except OSError as e:
            if w is not None:
                os.close(w)
            self.proc = None
            return self._off(f"{self.what} couldn't start ({e.strerror or e})")
        finally:
            if r is not None:
                os.close(r)  # the worker has its copy
        if self._parent_w is not None:
            os.close(self._parent_w)  # the last worker's pipe: that one is gone
        self._parent_w = w
        self.spawned += 1
        self.problem = ""

    async def ready(self, timeout: float = 30) -> bool:
        """Waits (up to `timeout` seconds) for the worker to answer."""
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if await self.healthy():
                return True
            if self.proc is not None and self.proc.poll() is not None:
                return False  # it died starting
            await asyncio.sleep(0.2)
        return False

    async def ensure(self, timeout: float = 30) -> bool:
        """The worker is up, started again if it died; False (with `problem` saying why) if local voice can't run."""
        if await self.healthy():
            return True
        async with self._lock:  # two requests at once start one worker
            if not await self.healthy():
                await self._start()
        if self.proc is None and self.problem:
            return False
        return await self.ready(timeout)

    async def stop(self) -> None:
        """Stops the worker this Odie started (another Odie's is left alone)."""
        proc, self.proc = self.proc, None
        if self._parent_w is not None:
            os.close(self._parent_w)  # the worker sees the pipe close and exits on its own too
            self._parent_w = None
        if proc is None or proc.poll() is not None:
            return
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(proc.pid, sig)
            except (ProcessLookupError, PermissionError):
                return
            for _ in range(50):
                if proc.poll() is not None:
                    return
                await asyncio.sleep(0.1)
