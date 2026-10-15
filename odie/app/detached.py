"""Run a chat turn in its own task so it survives the phone going away.

A turn used to run inside the HTTP stream: when iOS suspended the backgrounded PWA, the connection dropped,
the stream was cancelled and the turn died half way (question saved, answer lost). Now the turn runs to the
end on its own; the stream only watches it. If nobody is watching when it finishes, on_orphaned_done gets the
final text so Odie can push it.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from typing import Any

log = logging.getLogger(__name__)

_running: set[asyncio.Task] = set()  # strong refs: the event loop keeps only weak ones


def detached(events: AsyncIterator[dict[str, Any]], on_orphaned_done: Callable[[str], Any]) -> AsyncIterator[dict[str, Any]]:
    queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
    watching = {"on": True}

    async def run() -> None:
        final: str | None = None
        try:
            async for e in events:
                if e.get("type") == "done":
                    final = e.get("text") or ""
                queue.put_nowait(e)
        except Exception:  # noqa: BLE001
            log.exception("detached turn failed")
        finally:
            queue.put_nowait(None)
            if not watching["on"] and final:
                try:
                    on_orphaned_done(final)
                except Exception:  # noqa: BLE001
                    log.warning("orphaned-turn callback failed", exc_info=True)

    task = asyncio.create_task(run())
    _running.add(task)
    task.add_done_callback(_running.discard)

    async def watch() -> AsyncIterator[dict[str, Any]]:
        try:
            while (e := await queue.get()) is not None:
                yield e
        finally:
            watching["on"] = False  # after the end marker this changes nothing; before it, the phone left

    return watch()
