"""Who the assistant works for: the user's name (asked during setup, editable in Settings) and what this computer
says about where they are (timezone, locale, currency). The prompts start using the name in a later stage."""
from __future__ import annotations

import sys

from odie import config
from odie.store.db import Store

MAX_NAME = 40


def machine_kind(platform: str = sys.platform) -> str:
    """How Settings refers to the computer the assistant lives on."""
    return "Mac" if platform == "darwin" else "computer"


def get(store: Store) -> dict:
    s = config.settings
    p = store.get_setting("profile") or {}
    return {"user_name": p.get("user_name") or "", "timezone": s.timezone, "locale": s.locale, "country": s.country,
            "currency": s.currency, "machine": machine_kind()}


def set_user_name(store: Store, name: str) -> dict:
    clean = " ".join((name or "").split())[:MAX_NAME].strip()
    store.set_setting("profile", {**(store.get_setting("profile") or {}), "user_name": clean})
    return get(store)
