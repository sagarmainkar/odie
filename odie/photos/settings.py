"""Whether Odie reads the user's Photos library, and whether screenshots count. Off until setup or Settings turns it
on; kept in the store's settings as "photos". Hidden photos and the bin are never read (odie.photos.library)."""
from __future__ import annotations

KEY = "photos"
_KEEP = object()


def get(store) -> dict:
    v = store.get_setting(KEY) or {}
    return {"on": bool(v.get("on")), "screenshots": bool(v.get("screenshots"))}


def put(store, on=_KEEP, screenshots=_KEEP) -> dict:
    """Save what's given; leave a field out to keep it.
      put(store, on=True)            -> {"on": True, "screenshots": False}
      then put(store, screenshots=True) -> {"on": True, "screenshots": True}"""
    v = get(store)
    if on is not _KEEP:
        v["on"] = bool(on)
    if screenshots is not _KEEP:
        v["screenshots"] = bool(screenshots)
    store.set_setting(KEY, v)
    return v


def is_on(store) -> bool:
    return get(store)["on"]
