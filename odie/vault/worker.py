"""The background indexer: a pass over the vault by keywords every few minutes by modified time, and a note re-read
straight away when Odie writes it; the Photos library read into the same index every half hour when photos are on, or
straight away when that setting changes. Meaning (embedding new passages and pictures, which loads the embedding model)
runs on its own schedule, the vault setting's embed_every: every 5 to 60 minutes, or never while it's off (the user
runs a heavy chat model and wants the embedding model left unloaded). Never blocks a reply: the file work runs in a
thread, and embedding is awaited between batches."""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from pathlib import Path

from odie.photos import library
from odie.photos import settings as photos
from odie.vault import settings

log = logging.getLogger("odie.vault")
PHOTOS_EVERY = 1800  # seconds between reads of the Photos library (it changes slowly; a read is a few seconds)
EARLY_GRACE = 1.0    # seconds: a wait that ends this close to the embedding time counts as on time (timers fire a hair early)


class VaultWorker:
    def __init__(self, store, every: float = 300) -> None:
        self.store, self.every = store, every
        self._task: asyncio.Task | None = None
        self._wake: asyncio.Event | None = None
        self._touched: set[Path] = set()
        self._photos_at = 0.0       # when the library was last read (monotonic); 0: never
        self._photos_kick = False   # the photos setting changed: read the library on the next pass
        self._embedded_at: float | None = None  # when the last embedding pass started (monotonic); None: not since start
        self._embedded_wall: str | None = None  # the same moment on the wall clock, for Settings
        self._embed_every_seen = 0  # the interval (minutes) the last pass embedded on; 0: off, or no embedder
        self._embed_kick = False    # a setting changed or the user asked: embed on the next pass, if it's on
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
        """Run a pass now (the settings changed, or the user asked). photos: read the library in it, whatever the clock
        says. Meaning is caught up in it too, unless background embedding is off."""
        if photos:
            self._photos_kick = True
        self._embed_kick = True
        self._wake_up()

    def touch(self, path: Path) -> None:
        """Re-read this note by keywords now: Odie just wrote it. Its meaning waits for the next scheduled embedding
        (and while that's off, until it's back on), so a memory write never loads the embedding model."""
        self._touched.add(Path(path))
        self._wake_up()

    def _wake_up(self) -> None:
        if self._wake is not None:
            self._wake.set()

    def last_embedded(self) -> str | None:
        """When the last embedding pass started, on the wall clock (ISO), or None when none has run since Odie started."""
        return self._embedded_wall

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

    def embed_due(self, now: float, every_minutes: int) -> bool:
        """Whether this pass embeds new passages and pictures (which loads the embedding model). At most once per chosen
        interval, never while it's off; a settings change or the user asking catches up at once:
          off (0)                                        -> False
          every 15 min, last embedded 6 min ago          -> False
          every 15 min, last embedded 16 min ago         -> True
          just switched on, or the interval just changed -> True
          never embedded since Odie started              -> True
          every 15 min, 6 min ago, kick() (a setting)    -> True"""
        if every_minutes == 0:
            return False
        if self._embedded_at is None:
            return True
        if every_minutes != self._embed_every_seen:
            return True
        if self._embed_kick:
            return True
        return now - self._embedded_at >= every_minutes * 60 - EARLY_GRACE

    def seconds_to_wait(self, now: float, every_minutes: int) -> float:
        """How long the loop sleeps after a pass: the keyword interval, or less when embedding falls due sooner, so
        "every 10 min" embeds every 10 minutes and doesn't drift to the next keyword pass at 15. every_minutes is what the
        last pass embedded on (0 when off or there's no embedder):
          keywords every 5 min, embedding off                          -> 300
          keywords every 5 min, every 60 min, embedded 10 min ago      -> 300
          keywords every 5 min, every 10 min, embedded 7 min ago       -> 180"""
        if every_minutes == 0 or self._embedded_at is None:
            return self.every
        left = self._embedded_at + every_minutes * 60 - now
        return max(0.0, min(self.every, left))

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
                # Off pauses embedding only: the vectors, the model setting and the passages waiting are all kept.
                every_minutes = settings.get(self.store)["embed_every"]
                if self.embed_due(time.monotonic(), every_minutes):
                    await self._meaning_pass(ix, embedder, problems)
                self._embed_every_seen = every_minutes
            else:
                self._embed_every_seen = 0  # nothing to embed with: the loop waits the plain keyword interval
                if reason:
                    problems.append(f"Meaning search is off: {reason}")
                elif ix.status()["model"]:
                    await asyncio.to_thread(ix.forget_meaning)  # no embedding model any more: the status says keyword only
        except Exception as e:  # noqa: BLE001
            log.warning("vault pass failed", exc_info=True)
            problems.append(f"{type(e).__name__}: {e}"[:300])
        finally:
            self._state.update(running=False, phase="idle", error="; ".join(problems)[:300])

    async def _meaning_pass(self, ix, embedder, problems: list[str]) -> None:
        """New note passages by meaning, then new pictures when photos are on and the model sees pictures."""
        self._embedded_at = time.monotonic()  # the start, so the next one is an interval after this one, not after it ends
        self._embedded_wall = datetime.now().astimezone().isoformat(timespec="seconds")
        self._embed_kick = False
        self._state.update(phase="meaning", done=0, total=0)
        await ix.embed_pending(embedder, progress=self._count("meaning"))
        sees_pictures = getattr(embedder, "sees_pictures", False)
        if not ix.status()["embed_error"] and photos.is_on(self.store) and sees_pictures:
            self._state.update(phase="pictures", done=0, total=0)  # one vector per picture, after the notes
            await ix.embed_pending_pictures(embedder, progress=self._count("pictures"))
        if ix.status()["embed_error"]:
            problems.append(ix.status()["embed_error"])

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
                wait = self.seconds_to_wait(time.monotonic(), self._embed_every_seen)
                await asyncio.wait_for(self._wake.wait(), wait)
            except asyncio.TimeoutError:
                pass
            self._wake.clear()
