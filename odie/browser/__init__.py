"""Odie's own browser: the Chrome, Edge, Chromium or Brave already on the computer, driven over the DevTools protocol
in a profile of its own (never the user's), reaching only public web addresses."""
from __future__ import annotations

_shared = None


def shared():
    """The app's one browser (its profile in <data>/browser), made on first use."""
    global _shared
    if _shared is None:
        from odie import config
        from odie.browser.engine import Browser
        _shared = Browser(config.settings.data_dir / "browser")
    return _shared


async def close_shared() -> None:
    global _shared
    if _shared is not None:
        await _shared.close()
        _shared = None
