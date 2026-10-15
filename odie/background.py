"""The background agent's loop (spec 2026-10-07, part 1): every tick runs the parts that are due, in order and one at a
time, apart from chat. In 9a the parts are the trackers; the watch (9b) and parked tasks (9c) add theirs. A tick that
finds the last one still running does nothing; a part that fails or overruns its time limit is recorded and the next
one runs; the brief runs under the same lock through exclusive(); stop() cancels whatever is running."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

log = logging.getLogger("odie.background")


@dataclass
class Part:
    name: str
    run: Callable[[], Awaitable[Any]]
    due: Callable[[datetime], bool] = field(default=lambda now: True)
    limit: float = 300.0
    last_run: str | None = None
    last_ok: str | None = None
    error: str = ""


class Background:
    def __init__(self, parts: list[Part] | None = None, now: Callable[[], datetime] | None = None):
        self.parts: list[Part] = list(parts or [])
        self._now = now or (lambda: datetime.now().astimezone())
        self._lock = asyncio.Lock()
        self._current: asyncio.Task | None = None
        self._stopped = False
        self.last_tick: str | None = None

    def add(self, part: Part) -> None:
        self.parts.append(part)

    async def _run(self, part: Part) -> None:
        part.last_run = self._now().isoformat(timespec="seconds")
        try:
            await asyncio.wait_for(part.run(), part.limit)
        except TimeoutError:
            part.error = f"took longer than {part.limit:g} seconds, so it was stopped"
            log.warning("background %s: %s", part.name, part.error)
        except asyncio.CancelledError:
            part.error = "stopped (Odie is shutting down)"
            raise
        except Exception as e:  # noqa: BLE001 (a part's failure never stops the loop)
            part.error = f"{type(e).__name__}: {e}"[:300]
            log.warning("background %s failed", part.name, exc_info=True)
        else:
            part.error = ""
            part.last_ok = self._now().isoformat(timespec="seconds")

    async def _guarded(self, work: Callable[[], Awaitable[Any]]) -> Any:
        self._current = asyncio.current_task()
        try:
            return await work()
        finally:
            self._current = None

    async def tick(self) -> list[str]:
        if self._stopped or self._lock.locked():
            return []
        async with self._lock:
            if self._stopped:
                return []
            now = self._now()
            self.last_tick = now.isoformat(timespec="seconds")
            ran: list[str] = []

            async def work():
                for part in list(self.parts):
                    try:
                        due = part.due(now)
                    except Exception:  # noqa: BLE001
                        log.warning("background %s: due check failed", part.name, exc_info=True)
                        due = False
                    if due:
                        ran.append(part.name)
                        await self._run(part)
            try:
                await self._guarded(work)
            except asyncio.CancelledError:
                pass  # stop(): the tick ends here
            return ran

    async def exclusive(self, part: Part) -> bool:
        if self._stopped:
            return False
        async with self._lock:
            if self._stopped:
                return False
            try:
                await self._guarded(lambda: self._run(part))
            except asyncio.CancelledError:
                return False
            return True

    async def stop(self) -> None:
        self._stopped = True
        task = self._current
        if task is not None and not task.done():
            task.cancel()
            try:
                await asyncio.wait_for(asyncio.shield(task), 2)
            except (asyncio.CancelledError, TimeoutError, Exception):  # noqa: BLE001
                pass

    def status(self) -> dict:
        return {"running": self._lock.locked(), "last_tick": self.last_tick,
                "parts": {p.name: {"last_run": p.last_run, "last_ok": p.last_ok, "error": p.error} for p in self.parts}}
