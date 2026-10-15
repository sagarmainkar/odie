"""The background indexer: a pass over the vault (keywords first, then meaning when an embedding model is set), again
every few minutes by modified time, and a note re-read straight away when Odie writes it; the Photos library read into
the same index every half hour when photos are on, or straight away when that setting changes. Never blocks a reply:
the file work runs in a thread, and embedding is awaited between batches."""
from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

from odie.photos import library
from odie.photos import settings as photos
from odie.vault import settings

log = logging.getLogger("odie.vault")
PHOTOS_EVERY = 1800  # seconds between reads of the Photos library (it changes slowly; a read is a few seconds)


class VaultWorker:
    def __init__(self, store, every: float = 300) -> None:
        self.store, self.every = store, every
        self._task: asyncio.Task | None = None
        self._wake: asyncio.Event | None = None
        self._touched: set[Path] = set()
        self._photos_at = 0.0       # when the library was last read (monotonic); 0: never
        self._photos_kick = False   # the photos setting changed: read the library on the next pass
        self._state = {"running": False, "done": 0, "total": 0, "phase": "idle", "error": ""}

    def progress(self) -> dict:
        return dict(self._state)

    def start(self) -> None:
        if self._task is None:
            self._wake = asyncio.Event()
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._task = None

    def kick(self, photos: bool = False) -> None:
        """Run a pass now (the settings changed, or the user asked). photos: read the library in it, whatever the clock says."""
        if photos:
            self._photos_kick = True
        if self._wake is not None:
            self._wake.set()

    def touch(self, path: Path) -> None:
        """Re-read this note soon: Odie just wrote it."""
        self._touched.add(Path(path))
        self.kick()

    def _count(self, phase: str):
        def update(done: int, total: int) -> None:
            self._state.update(phase=phase, done=done, total=total)
        return update

    def photos_due(self, now: float) -> bool:
        """Whether this pass reads the Photos library: when the setting just changed, or half an hour has gone by.
          never read yet                       -> True
          read 10 minutes ago, nothing changed -> False
          read 10 minutes ago, kick(photos=True) -> True"""
        if self._photos_kick:
            return True
        return now - self._photos_at >= PHOTOS_EVERY

    async def run_once(self) -> None:
        try:
            ix = settings.index_for(self.store)
        except Exception as e:  # noqa: BLE001
            log.warning("vault index unavailable", exc_info=True)
            self._state["error"] = f"{type(e).__name__}: {e}"[:300]
            return
        if ix is None:
            self._touched.clear()
            return
        self._state.update(running=True, error="", phase="keywords", done=0, total=0)
        problems: list[str] = []
        try:
            if ix.vault is not None:
                for p in list(self._touched):
                    self._touched.discard(p)
                    await asyncio.to_thread(ix.index_file, p)
                await asyncio.to_thread(ix.scan, self._count("keywords"))
            else:
                self._touched.clear()
            await self._photos_pass(ix, problems)
            embedder, reason = settings.embedder_and_reason(self.store)
            if embedder is not None:
                self._state.update(phase="meaning", done=0, total=0)
                await ix.embed_pending(embedder, progress=self._count("meaning"))
                if not ix.status()["embed_error"] and photos.is_on(self.store) and getattr(embedder, "sees_pictures", False):
                    self._state.update(phase="pictures", done=0, total=0)  # one vector per picture, after the notes
                    await ix.embed_pending_pictures(embedder, progress=self._count("pictures"))
                if ix.status()["embed_error"]:
                    problems.append(ix.status()["embed_error"])
            elif reason:
                problems.append(f"Meaning search is off: {reason}")
            elif ix.status()["model"]:
                await asyncio.to_thread(ix.forget_meaning)  # switched off: the status says keyword only
        except Exception as e:  # noqa: BLE001
            log.warning("vault pass failed", exc_info=True)
            problems.append(f"{type(e).__name__}: {e}"[:300])
        finally:
            self._state.update(running=False, phase="idle", error="; ".join(problems)[:300])

    async def _photos_pass(self, ix, problems: list[str]) -> None:
        """The Photos library into the index when photos are on and due; forgotten when they were switched off."""
        if not photos.is_on(self.store):
            st = ix.status()
            if st["photos"] or st["videos"]:
                await asyncio.to_thread(ix.forget_photos)
            return
        if not self.photos_due(time.monotonic()):
            return
        self._state.update(phase="photos", done=0, total=0)
        self._photos_kick = False
        self._photos_at = time.monotonic()  # a failed read waits the same half hour (or a kick) before trying again
        try:
            rows = await asyncio.to_thread(library.read_library, photos.get(self.store)["screenshots"], self._count("photos"))
            await asyncio.to_thread(ix.index_photos, rows, self._count("photos"))
        except library.LibraryError as e:
            log.warning("photos pass failed: %s", e)
            problems.append(f"Photos: {e}")

    async def _loop(self) -> None:
        while True:
            try:
                await self.run_once()
            except Exception:  # noqa: BLE001
                log.warning("vault pass failed", exc_info=True)  # one bad pass never stops the next
            try:
                await asyncio.wait_for(self._wake.wait(), self.every)
            except asyncio.TimeoutError:
                pass
            self._wake.clear()
