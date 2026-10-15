"""The live view (spec Part 1): the user's turn in Odie's browser. The phone sees the tab's frames and drives it with
taps and its own keyboard; the model gets nothing of it (no frame is saved, no page is read, no input is logged), and
every browser tool on the tab waits while the user holds it. One device holds a tab; another can take over. A dropped
connection keeps the tab for GRACE seconds (the phone sleeping), and IDLE seconds without input hand it back."""
from __future__ import annotations

import asyncio
import contextlib
import logging
import math
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from odie.signin import sites

log = logging.getLogger("odie.signin")

GRACE = 120.0
IDLE = 15 * 60.0
KEYS = frozenset({"Backspace", "Enter", "Tab"})
TEXT_CAP = 2000  # one paste at most


def clean(msg: Any) -> dict | None:
    """The phone's input, checked: what reaches the browser, or None for anything else."""
    if not isinstance(msg, dict):
        return None

    def num(*keys) -> bool:
        return all(isinstance(msg.get(k), int | float) and not isinstance(msg.get(k), bool) and math.isfinite(msg[k])
                   and 0 <= msg[k] <= 20000 for k in keys)
    t = msg.get("t")
    if t == "tap" and num("x", "y"):
        return {"t": t, "x": msg["x"], "y": msg["y"]}
    if t == "drag" and num("x0", "y0", "x1", "y1"):
        return {"t": t, **{k: msg[k] for k in ("x0", "y0", "x1", "y1")}}
    if t == "text" and isinstance(msg.get("s"), str) and msg["s"]:
        return {"t": t, "s": msg["s"][:TEXT_CAP]}
    if t == "key" and msg.get("k") in KEYS:
        return {"t": t, "k": msg["k"]}
    if t in ("back", "reload"):
        return {"t": t}
    if t == "go" and isinstance(msg.get("url"), str) and msg["url"].strip():
        return {"t": t, "url": msg["url"].strip()[:2000]}
    return None


@dataclass
class View:
    tab: str
    holder: str
    socket: Any = None
    url: str = ""
    title: str = ""
    last: float = field(default_factory=time.monotonic)
    origins: set = field(default_factory=set)  # where the page went while the user drove (for Sign out)
    timer: asyncio.Task | None = None  # the drop grace, while no phone is connected
    watch: asyncio.Task | None = None  # the idle check


class LiveViews:
    def __init__(self, store, browser_for: Callable[[], Any] | None = None, grace: float = GRACE, idle: float = IDLE):
        self.store = store
        self._browser_for = browser_for
        self.grace, self.idle = grace, idle
        self._views: dict[str, View] = {}
        self._listening: set[int] = set()  # browsers whose UPI catches reach the live view

    def browser(self):
        if self._browser_for is not None:
            return self._browser_for()
        from odie.browser import shared
        return shared()

    def live(self, tab: str) -> bool:
        return tab in self._views

    async def _send(self, view: View, msg: dict) -> None:
        ws = view.socket
        if ws is None:
            return
        try:
            await ws.send_json(msg)
        except Exception:  # noqa: BLE001 (a phone that went away: the drop grace takes over)
            pass

    def _listen(self, b) -> None:
        if id(b) in self._listening or not hasattr(b, "on_upi"):
            return
        self._listening.add(id(b))
        loop = asyncio.get_running_loop()

        def caught(tab: str, url: str) -> None:  # the browser's event (on this loop), or any thread
            if (view := self._views.get(tab)) is not None:
                loop.call_soon_threadsafe(lambda: loop.create_task(self._send(view, {"t": "upi", "url": url})))
        b.on_upi(caught)

    async def serve(self, tab: str, ws) -> None:
        """One phone's live view of a tab, until Done or Cancel, a drop, the idle limit, or another device taking it."""
        hello = await ws.receive_json()
        if not isinstance(hello, dict) or hello.get("t") != "hello":
            await ws.send_json({"t": "bye", "why": "hello first"})
            return
        w = int(min(max(_n(hello.get("w"), 390), 320), 1024))
        h = int(min(max(_n(hello.get("h"), 844), 480), 2000))
        view = self._views.get(tab)
        if view is not None and view.socket is not None:
            await ws.send_json({"t": "busy"})
            answer = await ws.receive_json()
            if not isinstance(answer, dict) or answer.get("t") != "take" or self._views.get(tab) is not view:
                return
            old, view.socket = view.socket, None
            with contextlib.suppress(Exception):
                await old.send_json({"t": "bye", "why": "taken"})
                await old.close()
        b = self.browser()
        self._listen(b)
        if view is None:
            view = View(tab, secrets.token_hex(6))
            self._views[tab] = view
            b.hold(tab, view.holder)
        if view.timer:
            view.timer.cancel()
            view.timer = None
        view.socket, view.last = ws, time.monotonic()

        async def on_frame(jpeg: str, meta: dict) -> None:
            await self._send(view, {"t": "frame", "jpeg": jpeg, "w": meta.get("deviceWidth"), "h": meta.get("deviceHeight")})

        async def on_page(info: dict) -> None:
            view.url, view.title = info.get("url", view.url), info.get("title", view.title)
            if o := sites.origin_of(view.url):
                view.origins.add(o)
            await self._send(view, {"t": "page", "url": view.url, "title": view.title, "loading": bool(info.get("loading"))})
        try:
            await b.live_start(tab, w, h, on_frame, on_page)
        except Exception as e:  # noqa: BLE001
            log.warning("live view couldn't start", exc_info=True)
            await self._send(view, {"t": "bye", "why": f"The browser couldn't show the page ({type(e).__name__})."})
            await self.end(tab, None)
            return
        if view.watch is None:
            view.watch = asyncio.get_running_loop().create_task(self._watch(view))
        try:
            while True:
                msg = await ws.receive_json()
                if self._views.get(tab) is not view or view.socket is not ws:
                    return
                view.last = time.monotonic()
                if isinstance(msg, dict) and msg.get("t") == "ping":
                    await ws.send_json({"t": "pong"})
                    continue
                if (step := clean(msg)) is None:
                    continue  # nothing else reaches the browser
                try:
                    await b.live_input(tab, step)
                except Exception as e:  # noqa: BLE001 (a page that didn't take a tap shouldn't end the view)
                    await self._send(view, {"t": "error", "why": str(e)[:200] or type(e).__name__})
        except Exception:  # noqa: BLE001 (the phone went away)
            pass
        finally:
            if self._views.get(tab) is view and view.socket is ws:
                view.socket = None
                view.timer = asyncio.get_running_loop().create_task(self._later(view))

    async def _later(self, view: View) -> None:
        await asyncio.sleep(self.grace)
        if self._views.get(view.tab) is view and view.socket is None:
            await self.end(view.tab, None)

    async def _watch(self, view: View) -> None:
        while self._views.get(view.tab) is view:
            await asyncio.sleep(min(30.0, max(self.idle / 3, 0.05)))
            if self._views.get(view.tab) is view and time.monotonic() - view.last > self.idle:
                await self.end(view.tab, "idle")
                return

    async def end(self, tab: str, why: str | None) -> View | None:
        """Hand the tab back: the phone is told why, the screencast stops, the tab is desktop-shaped and free again."""
        view = self._views.pop(tab, None)
        if view is None:
            return None
        current = asyncio.current_task()
        for task in (view.timer, view.watch):
            if task is not None and task is not current:
                task.cancel()
        if view.socket is not None and why:
            await self._send(view, {"t": "bye", "why": why})
            with contextlib.suppress(Exception):
                await view.socket.close()
        view.socket = None
        b = self.browser()
        try:
            await b.live_stop(tab)
        except Exception:  # noqa: BLE001 (the browser went away: the tab is gone with it)
            log.warning("live view stop failed", exc_info=True)
        b.release(tab)
        return view

    async def finish(self, tab: str, done: bool) -> dict:
        """Done (record the site now open) or Cancel. LookupError if nothing is live on the tab."""
        view = await self.end(tab, "done" if done else "cancel")
        if view is None:
            raise LookupError(tab)
        site = sites.site_of(view.url)
        if done and site:
            sites.record(self.store, site, datetime.now().astimezone(), origins=view.origins)
            self.store.audit("user", "signin_done", result_summary=site)  # the site only: never what was typed
        return {"site": site}

    async def close(self, why: str = "closed") -> None:
        for tab in list(self._views):
            await self.end(tab, why)


def _n(v: Any, default: float) -> float:
    return float(v) if isinstance(v, int | float) and not isinstance(v, bool) and math.isfinite(v) else default
