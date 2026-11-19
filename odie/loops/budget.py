"""The day's budget of proactive model calls (proactive design §6): CALLS_DAILY, shared by everyday Odie and every
personality. Stage 4's calls are spent from it and stop when it is gone (the loops wait for tomorrow; nothing is
lost); the watch's own turns are counted too, so the day's number is honest, but never stopped by it (the watch
works as it always has)."""
from __future__ import annotations

from datetime import datetime

CALLS_DAILY = 150
KEY = "loops.calls"  # {"day": "2026-11-18", "used": 12}


def used_today(store, now: datetime) -> int:
    """Today's count: the saved one when it is today's, else 0. {"day": "2026-11-18", "used": 12} on 18 Nov -> 12; on
    19 Nov -> 0."""
    saved = store.get_setting(KEY) or {}
    if saved.get("day") != now.date().isoformat():
        return 0
    return int(saved.get("used") or 0)


def left(store, now: datetime) -> int:
    return max(0, CALLS_DAILY - used_today(store, now))


def count(store, now: datetime) -> None:
    """Counts one proactive model call, whatever is left (the watch's turn)."""
    store.set_setting(KEY, {"day": now.date().isoformat(), "used": used_today(store, now) + 1})


def spend(store, now: datetime) -> bool:
    """Takes one call from today's budget: True when one was left (now used); False when today's are gone. 149 used
    -> True (150 now); 150 used -> False; the next day -> True."""
    if left(store, now) <= 0:
        return False
    count(store, now)
    return True
