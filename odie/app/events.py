"""In-process event bus: Odie-originated messages and task changes fan out to every open /api/events stream."""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any


class EventBus:
    def __init__(self) -> None:
        self._subs: set[asyncio.Queue] = set()

    async def publish(self, event: dict[str, Any]) -> None:
        self.emit(event)

    def emit(self, event: dict[str, Any]) -> None:
        """publish() for plain code (a push hook): the event goes to every open stream at once, nothing is awaited."""
        for q in list(self._subs):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass

    def queue(self) -> asyncio.Queue:
        """A subscriber queue; call release() when done. Safe to wait_for() on with timeouts."""
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._subs.add(q)
        return q

    def release(self, q: asyncio.Queue) -> None:
        self._subs.discard(q)

    async def subscribe(self) -> AsyncIterator[dict[str, Any]]:
        q = self.queue()
        try:
            while True:
                yield await q.get()
        finally:
            self.release(q)
