"""A minimal DevTools protocol client over one websocket: commands by id (with sessions for tabs) and events to
listeners. Only the standard library and `websockets` (already installed with uvicorn)."""
from __future__ import annotations

import asyncio
import inspect
import itertools
import json
import logging
from collections.abc import Callable
from typing import Any

import websockets

log = logging.getLogger("odie.browser")


class CDPError(RuntimeError):
    pass


class CDP:
    def __init__(self, ws) -> None:
        self.ws = ws
        self._ids = itertools.count(1)
        self._pending: dict[int, asyncio.Future] = {}
        self._listeners: list[Callable[[str, dict, str | None], Any]] = []
        self._tasks: set[asyncio.Task] = set()
        self._reader = asyncio.create_task(self._read())

    @classmethod
    async def connect(cls, url: str) -> CDP:
        return cls(await websockets.connect(url, max_size=64 * 1024 * 1024, ping_interval=None, close_timeout=1))

    def on(self, fn: Callable[[str, dict, str | None], Any]) -> None:
        self._listeners.append(fn)

    async def send(self, method: str, params: dict | None = None, session: str | None = None, timeout: float = 30) -> dict:
        i = next(self._ids)
        fut = asyncio.get_running_loop().create_future()
        self._pending[i] = fut
        msg: dict[str, Any] = {"id": i, "method": method, "params": params or {}}
        if session:
            msg["sessionId"] = session
        try:
            await self.ws.send(json.dumps(msg))
            return await asyncio.wait_for(fut, timeout)
        finally:
            self._pending.pop(i, None)

    async def _read(self) -> None:
        try:
            async for raw in self.ws:
                msg = json.loads(raw)
                if "id" in msg:
                    fut = self._pending.get(msg["id"])
                    if fut and not fut.done():
                        if "error" in msg:
                            fut.set_exception(CDPError(msg["error"].get("message", "error")))
                        else:
                            fut.set_result(msg.get("result", {}))
                    continue
                for fn in self._listeners:
                    try:
                        out = fn(msg.get("method", ""), msg.get("params", {}), msg.get("sessionId"))
                    except Exception:  # noqa: BLE001 (a listener's bug must not stop the connection)
                        log.warning("browser event handler failed", exc_info=True)
                        continue
                    if inspect.isawaitable(out):
                        t = asyncio.ensure_future(out)
                        self._tasks.add(t)
                        t.add_done_callback(self._tasks.discard)
        except websockets.ConnectionClosed:
            pass
        finally:
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(ConnectionError("the browser closed"))

    @property
    def closed(self) -> bool:
        return self._reader.done()

    async def close(self) -> None:
        try:
            await self.ws.close()
        except Exception:  # noqa: BLE001
            pass
        self._reader.cancel()
        for t in list(self._tasks):
            t.cancel()
