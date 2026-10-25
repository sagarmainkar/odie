"""Where the user is: a place name, remembered with its time, and a learned home. A device (the web app, the Mac app)
sends a fix when it opens; the server keeps the place, the coordinates and the last 30 days of fixes, and the model
gets only the place name and home in each message's context line (odie.agent.prompt.build_turn_context). Coordinates
never go to the model; they stay in the settings table for the place lookup and the home inference.

The setting (KEY): {"on": True|False|None, "place": str, "lat": float|None, "lon": float|None, "seen": iso, "home": str,
"home_set_by_user": bool, "fixes": [{"place", "lat", "lon", "at"}, ...]}. `on` is None until a device ever answered
the one ask, False after "Not now" or the Settings switch, True once a fix came in.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta

KEY = "location"
KEEP_FIXES = 200
KEEP_DAYS = 30
NIGHT_FIXES_NEEDED = 5
EMPTY: dict = {"on": None, "place": "", "lat": None, "lon": None, "seen": "", "home": "", "home_set_by_user": False, "fixes": []}


def get(store) -> dict:
    """The setting with every field present, whatever was saved: nothing saved -> EMPTY."""
    saved = store.get_setting(KEY) or {}
    return {**EMPTY, "fixes": [], **saved}


def _save(store, value: dict) -> dict:
    store.set_setting(KEY, value)
    return get(store)


def is_night(at: datetime) -> bool:
    """Whether a fix's own clock says night, 23:00 up to 06:00, in the fix's own offset (a fix taken abroad is judged by
    the time there): 23:00 -> True; 05:59 -> True; 06:00 -> False; 22:59 -> False."""
    return at.hour >= 23 or at.hour < 6


def _at(fix: dict) -> datetime | None:
    try:
        return datetime.fromisoformat(str(fix.get("at", "")))
    except ValueError:
        return None


def home_of(fixes: list[dict]) -> str:
    """The place seen most often on nights (is_night) among the fixes given: where the user sleeps. "" with fewer than
    NIGHT_FIXES_NEEDED night fixes (too little to say), or when two places tie for first (no clear winner).
    Example: 8 nights in "Northvale, Westshire" and 19 days in "Seaport, Eastmarch" -> "Northvale, Westshire";
    4 nights anywhere -> ""; 5 nights in Northvale and 5 in Harbour Town -> ""."""
    nights = Counter()
    for fix in fixes:
        at = _at(fix)
        place = str(fix.get("place") or "")
        if at is None or not place or not is_night(at):
            continue
        nights[place] += 1
    if sum(nights.values()) < NIGHT_FIXES_NEEDED:
        return ""
    ranked = nights.most_common(2)
    if len(ranked) == 2 and ranked[0][1] == ranked[1][1]:
        return ""
    return ranked[0][0]


def prune(fixes: list[dict], now: datetime) -> list[dict]:
    """The fixes worth keeping: those from the last KEEP_DAYS days, and of those the last KEEP_FIXES recorded (the list
    is in the order recorded, newest last). Example: 205 fixes from today and one from 31 days ago -> the 200 most
    recently recorded, the old one gone."""
    cutoff = now - timedelta(days=KEEP_DAYS)
    recent = []
    for fix in fixes:
        at = _at(fix)
        if at is not None and at >= cutoff:
            recent.append(fix)
    return recent[-KEEP_FIXES:]


def record(store, lat: float, lon: float, place: str, now: datetime) -> dict:
    """A device said where the user is: the place, the coordinates and the time are kept, the fix joins the list, and
    home is worked out again unless the user stated it. `on` becomes True: the ask is answered."""
    current = get(store)
    fixes = prune([*current["fixes"], {"place": place, "lat": lat, "lon": lon, "at": now.isoformat()}], now)
    home = current["home"] if current["home_set_by_user"] else home_of(fixes)
    return _save(store, {**current, "on": True, "place": place, "lat": lat, "lon": lon, "seen": now.isoformat(), "home": home,
                         "fixes": fixes})


def decline(store) -> dict:
    """"Not now", or the switch turned off: nothing is sent to the model, and what was known stays for the switch back on."""
    return _save(store, {**get(store), "on": False})


def set_on(store, on: bool) -> dict:
    if not on:
        return decline(store)
    return _save(store, {**get(store), "on": True})


def set_home(store, home: str) -> dict:
    """A home the user stated ("my home is Northvale"): it wins over inference until Forget."""
    return _save(store, {**get(store), "home": home.strip(), "home_set_by_user": bool(home.strip())})


def forget(store) -> dict:
    """Everything cleared: the place, the fixes, home, and the answer to the ask (`on` back to None)."""
    return _save(store, {**EMPTY, "fixes": []})
