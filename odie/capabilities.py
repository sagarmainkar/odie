"""What this install can do beyond the core (web, memory, tasks, the shell): the notes vault (an MCP server named
"vault" that loaded) and whatever the add-ons bring (mail, calendar, the Google sign-in, the SMS money ledger). The
prompt only carries rules for what's here."""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def detect(servers: Iterable[Any] = (), store: Any = None) -> frozenset[str]:
    """servers: the loaded MCP servers (the runner's plugins["servers"]); mcp.json lists the vault on every install,
    so only one that answered counts. store: for Odie's own notes index (vault and vault_index when a folder is set)."""
    caps: set[str] = set()
    if any(e.name == "vault" and e.status == "ok" for e in servers):
        caps.add("vault")
    if store is not None:
        from odie.vault import settings
        if settings.configured(store):
            caps |= {"vault", "vault_index"}
        from odie.photos import settings as photos
        if photos.is_on(store):
            caps.add("photos")  # the user's Photos library is read into the index: pictures by who, where, when
    from odie.browser import find
    if find.browser_binary():
        caps.add("browser")  # a Chromium-family browser on this computer: Odie can browse with its own profile
        from odie.signin import state
        if store is not None and state.is_on(store):
            caps.add("signin")  # signed-in browsing, turned on by the user with the risks accepted (odie.signin)
    from odie import addons
    return frozenset(caps) | addons.capabilities()
