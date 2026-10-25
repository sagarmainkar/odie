"""Where the user is: a place name, remembered with its time, and a learned home. A device (the web app, the Mac app)
sends a fix when it opens; the server keeps the place, the coordinates and the last 30 days of fixes, and the model
gets only the place name and home in each message's context line (odie.agent.prompt.build_turn_context). Coordinates
never go to the model; they stay in the settings table for the place lookup and the home inference.

The setting (KEY): {"on": True|False|None, "place": str, "lat": float|None, "lon": float|None, "seen": iso, "home": str,
"home_set_by_user": bool, "fixes": [{"place", "lat", "lon", "at"}, ...]}. `on` is None until a device ever answered
the one ask, False after "Not now" or the Settings switch, True once a fix came in.
"""
from __future__ import annotations

import logging
import math
from collections import Counter
from datetime import datetime, timedelta

import httpx

log = logging.getLogger("odie.location")
KEY = "location"
NEAR_KM = 5  # a remembered fix this close is the same place: its name is reused, and nothing is asked of the network
NOMINATIM = "https://nominatim.openstreetmap.org/reverse"
USER_AGENT = "Odie (https://github.com/sagarmainkar/odie)"  # Nominatim's terms: say who is asking
LOOKUP_TIMEOUT = 6.0
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


def point_is_plausible(lat: float, lon: float) -> bool:
    """Whether a device's point can be a real one: latitude within [-90, 90], longitude within [-180, 180], and not
    exactly (0, 0), which is what a device with no fix at all sends. (18.52, 73.85) -> True; (0, 0) -> False;
    (91, 0) -> False; (1, 181) -> False."""
    in_range = -90 <= lat <= 90 and -180 <= lon <= 180
    null_island = lat == 0 and lon == 0
    return in_range and not null_island


def view(setting: dict) -> dict:
    """What leaves the server about the location: the switch, the place, when it was seen, home and whether the user
    stated it. Never the coordinates or the fixes."""
    return {"on": setting["on"], "place": setting["place"], "seen": setting["seen"], "home": setting["home"],
            "home_set_by_user": bool(setting["home_set_by_user"])}


def km_between(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """The distance between two points over the ground, in km (haversine). Example: (18.52, 73.85) to (18.55, 73.88)
    -> 4.6."""
    radius = 6371.0
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = math.sin(d_lat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(d_lon / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


def remembered_place(fixes: list[dict], lat: float, lon: float) -> str:
    """The name of a remembered fix within NEAR_KM of this point, the most recent one first, so the same place keeps
    one name however the geocoder words it ("Northvale" today is still "Northvale" tomorrow): a fix 4.6 km away named
    "Northvale, Westshire" -> that; nothing within 5 km -> ""."""
    for fix in reversed(fixes):
        place = str(fix.get("place") or "")
        if not place:
            continue
        try:
            close = km_between(float(fix["lat"]), float(fix["lon"]), lat, lon) <= NEAR_KM
        except (KeyError, TypeError, ValueError):
            continue
        if close:
            return place
    return ""


def place_from_address(address: dict) -> str:
    """Nominatim's address as a short place name: the city, town, village or county (the first of those it gives),
    then the state, joined by ", ". {"town": "Harbour Town", "state": "Eastmarch", "country": ...} -> "Harbour Town,
    Eastmarch"; {"state": "Eastmarch"} -> "Eastmarch"; {} -> ""."""
    locality = next((str(address[k]) for k in ("city", "town", "village", "county") if address.get(k)), "")
    state = str(address.get("state") or "")
    return ", ".join(part for part in (locality, state) if part)


async def place_for(store, lat: float, lon: float, transport=None) -> str:
    """The place name for a point. A remembered fix nearby answers first (remembered_place), with no network. Else
    Nominatim is asked once, over https, with Odie's user agent; a point is sent out only here, and only when nothing
    nearby is known. One request per call and at most one fix per device open keeps well under Nominatim's one request
    a second. "" when it can't be reached or read (an error status, a timeout, no JSON, no address): the fix is still
    stored, and the model line falls back to the last place name known."""
    known = remembered_place(get(store)["fixes"], lat, lon)
    if known:
        return known
    params = {"format": "jsonv2", "zoom": "10", "lat": f"{lat:.5f}", "lon": f"{lon:.5f}"}
    try:
        async with httpx.AsyncClient(transport=transport, timeout=LOOKUP_TIMEOUT, headers={"User-Agent": USER_AGENT}) as client:
            response = await client.get(NOMINATIM, params=params)
        if response.status_code != 200:
            log.info("the place lookup answered %s", response.status_code)
            return ""
        address = response.json().get("address") or {}
    except (httpx.HTTPError, ValueError, AttributeError):
        log.info("the place lookup failed", exc_info=True)
        return ""
    return place_from_address(address)
