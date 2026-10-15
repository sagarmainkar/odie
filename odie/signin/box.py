"""Odie's sign-in box (spec "Sign in for me", Parts 3, 4 and 6): a login typed in Odie's own sheet, or saved in the
vault, is filled into the site by the engine; the AI never sees it. Through a code step the login waits in memory,
never on disk, for up to PENDING_FOR seconds. Odie signs in by itself at most once per site every AUTO_EVERY seconds."""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from odie.signin import sites, state, vault

PENDING_FOR = 600.0
AUTO_EVERY = 600.0
log = logging.getLogger("odie.signin")


@dataclass
class Pending:
    site: str
    username: str = field(repr=False)
    password: str = field(repr=False)  # never printed, not even in a traceback's repr
    remember: bool
    until: float = field(default_factory=lambda: time.monotonic() + PENDING_FOR)


class SignInBox:
    def __init__(self, store, browser_for: Callable[[], Any] | None = None):
        self.store = store
        self._browser_for = browser_for
        self._pending: dict[str, Pending] = {}  # tab -> a login waiting for its code
        self._tried: dict[str, tuple[str | None, float, bool]] = {}  # site -> (the turn's words, when, worked) of Odie's last try
        self._left: dict[str, tuple[str | None, float]] = {}  # site -> (the turn's words, when) it logged out

    def _browser(self, given=None):
        if given is not None:
            return given
        if self._browser_for is not None:
            return self._browser_for()
        from odie.browser import shared
        return shared()

    async def submit(self, tab: str, site: str, username: str, password: str, remember: bool, browser=None) -> dict:
        p = Pending(sites.site_of(site), username, password, remember)
        return self._after(tab, p, await self._browser(browser).sign_in(tab, p.site, username, password))

    async def code(self, tab: str, code: str, browser=None) -> dict:
        p = self._pending.get(tab)
        if p is None or p.until < time.monotonic():
            self._pending.pop(tab, None)
            return {"status": "expired", "site": p.site if p else ""}
        return self._after(tab, p, await self._browser(browser).enter_code(tab, p.site, code.strip()))

    async def by_itself(self, tab: str, url: str, browser) -> dict | None:
        """A sign-in page of a site with a saved login, in a chat turn: sign in without asking. None when there's no
        saved login, signed-in browsing is off, or Odie tried this site in the last AUTO_EVERY seconds."""
        site = sites.site_of(url)
        if not state.is_on(self.store) or site not in {x["site"] for x in vault.listing(self.store)}:
            return None
        from odie.agent import turn
        words, now = turn.USER_TEXT.get(), time.monotonic()
        last = self._tried.get(site)
        if last and now - last[1] < AUTO_EVERY and (not last[2] or last[0] == words):
            return None  # a failed try waits AUTO_EVERY; a successful one, the rest of its turn (no loop)
        left = self._left.get(site)
        if left and left[0] == words and now - left[1] < AUTO_EVERY:
            return None  # this very turn logged out of it
        self._tried[site] = (words, now, False)
        try:
            login = vault.get(self.store, site)
        except vault.VaultError:
            return {"status": "vault", "site": site}
        if login is None:
            return None
        out = self._after(tab, Pending(site, login[0], login[1], remember=False), await browser.sign_in(tab, site, *login))
        self._tried[site] = (words, time.monotonic(), out["status"] == "signed_in")
        return out

    def _after(self, tab: str, p: Pending, result: dict) -> dict:
        status = str(result.get("status") or "failed")
        out: dict = {"status": status, "site": p.site}
        if status == "code":
            self._pending[tab] = p
            return out
        self._pending.pop(tab, None)
        if status == "signed_in":
            now = datetime.now().astimezone()
            sites.record(self.store, p.site, now)
            self.store.audit("user", "signin_done", result_summary=p.site)
            try:
                if p.remember:
                    vault.save(self.store, p.site, p.username, p.password, now)
                else:
                    vault.used(self.store, p.site, now)
            except (vault.VaultError, ValueError) as e:
                out["warning"] = f"Signed in. {e}"  # the sign-in worked; only saving it didn't
        return out

    def signed_out(self, site: str) -> None:
        """The model just logged out of this site, as asked: no signing straight back in during that turn. The user's
        next request is a new turn, which may sign in again."""
        from odie.agent import turn
        self._left[sites.site_of(site)] = (turn.USER_TEXT.get(), time.monotonic())

    def forget(self) -> None:
        self._pending.clear()
        self._tried.clear()
        self._left.clear()


_boxes: dict[int, SignInBox] = {}


def for_store(store) -> SignInBox:
    """The one box for this store: the routes (the sheet) and the browser tools (by itself) share its pending codes."""
    if id(store) not in _boxes or _boxes[id(store)].store is not store:
        _boxes[id(store)] = SignInBox(store)
    return _boxes[id(store)]
