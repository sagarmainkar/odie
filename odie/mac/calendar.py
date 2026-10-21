"""The Mac's calendars (iCloud and any account Calendar shows) through Calendar's AppleScript: events in a window,
and adding one."""
from __future__ import annotations

import json
from datetime import datetime

from odie.mac import scripts

APP = "Calendar"


def _iso(d: datetime) -> str:
    return d.strftime("%Y-%m-%dT%H:%M:%S")


async def events(start: datetime, end: datetime, run=scripts.run) -> list[dict]:
    """Events starting between `start` and `end` (local time), every calendar: id (the event's uid), title, start,
    end (ISO with offset), where, attendees (emails), calendar (its name), all_day."""
    text = await run("calendar_events", _iso(start), _iso(end), app=APP)
    got = json.loads(text) if text else []
    return [r for r in got if isinstance(r, dict)] if isinstance(got, list) else []


async def calendars(run=scripts.run) -> list[dict]:
    """The calendars events may go into: [{name, writable}], the system ones (Birthdays, holidays, Siri Suggestions,
    Scheduled Reminders) left out."""
    text = await run("calendar_list", app=APP)
    got = json.loads(text) if text else []
    return [r for r in got if isinstance(r, dict)] if isinstance(got, list) else []


SETTING = "mac.default_calendar"


def chosen(store=None) -> str:
    """The calendar the user picked in Settings → Mac apps for events Odie adds, or "" (the script then takes the first
    writable calendar that isn't a system one)."""
    if store is None:
        from odie import config
        from odie.store.db import Store
        store = Store(config.settings.data_dir / "assistant.db")
        store.init_schema()
    return str(store.get_setting(SETTING) or "")


async def add(title: str, start: datetime, end: datetime, calendar: str = "", where: str = "", notes: str = "",
              run=scripts.run) -> dict:
    """Makes an event and returns {id, calendar}. `calendar` names one of the Mac's calendars; "" takes the first
    writable one that isn't a system calendar. A name that isn't there fails with the names that are (the script's
    own words)."""
    if not title.strip():
        raise scripts.MacError("An event needs a title.")
    if end <= start:
        raise scripts.MacError("The event's end must come after its start.")
    text = await run("calendar_add", title.strip(), _iso(start), _iso(end), calendar.strip(), where.strip(), notes.strip(), app=APP)
    got = json.loads(text)
    if not isinstance(got, dict) or not got.get("id"):
        raise scripts.MacError("Calendar made no event.")
    return got
