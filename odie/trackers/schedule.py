"""When a tracker checks: an interval ("15m", "every 2 hours", "1d") or set times ("09:00", "mon 09:00",
"weekdays 7:30", "daily 08:00, 20:00"), in the user's timezone."""
from __future__ import annotations

import re
from datetime import datetime, timedelta

MIN_MINUTES, MAX_MINUTES = 5, 7 * 1440  # 5: the background tick
_DAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
_UNIT = {"m": 1, "min": 1, "mins": 1, "minute": 1, "minutes": 1, "h": 60, "hr": 60, "hrs": 60, "hour": 60, "hours": 60,
         "d": 1440, "day": 1440, "days": 1440}


def parse_every(text: str) -> dict | None:
    """The tracker's schedule from what the user said, or None when it can't be read.
    Example: "every 2 hours" -> {"minutes": 120}; "1m" -> None (under 5 minutes); "weekdays 7:30" ->
    {"times": ["07:30"], "days": [0, 1, 2, 3, 4]}; "daily 08:00, 20:00" -> {"times": ["08:00", "20:00"], "days": None}."""
    t = " ".join((text or "").lower().replace("every", " ").split())
    m = re.fullmatch(r"(\d+)\s*([a-z]+)", t)
    if m and m.group(2) in _UNIT:
        mins = int(m.group(1)) * _UNIT[m.group(2)]
        if mins < MIN_MINUTES or mins > MAX_MINUTES:
            return None
        return {"minutes": mins}
    times = re.findall(r"\b(\d{1,2}):(\d{2})\b", t)
    if not times or any(int(h) > 23 or int(mm) > 59 for h, mm in times):
        return None
    words = re.sub(r"\d{1,2}:\d{2}", " ", t).replace(",", " ").split()
    days: set[int] = set()
    for w in words:
        if w in ("daily", "day", "at"):
            continue
        if w == "weekdays":
            days |= {0, 1, 2, 3, 4}
        elif w == "weekends":
            days |= {5, 6}
        elif w[:3] in _DAYS:
            days.add(_DAYS[w[:3]])
        else:
            return None
    times_of_day = sorted({f"{int(h):02d}:{mm}" for h, mm in times})
    on_days = sorted(days)
    if not on_days:
        on_days = None  # no day named: every day
    return {"times": times_of_day, "days": on_days}


def next_due(spec: dict, after: datetime) -> datetime:
    """The first check strictly after `after` (an aware local time)."""
    if "minutes" in spec:
        return after + timedelta(minutes=spec["minutes"])
    days = spec.get("days")
    for add in range(0, 8):
        day = (after + timedelta(days=add)).date()
        if days is not None and day.weekday() not in days:
            continue
        for hm in spec["times"]:
            h, m = map(int, hm.split(":"))
            at = datetime(day.year, day.month, day.day, h, m, tzinfo=after.tzinfo)
            if at > after:
                return at
    return after + timedelta(days=1)  # unreachable for a valid spec
