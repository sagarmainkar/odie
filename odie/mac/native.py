"""The Mac apps as watch sources: the fetcher calls a native tool by name with the same arguments it would give a
connector, and gets the same Result shape (JSON text, or an error in words), so the parsers need no other path."""
from __future__ import annotations

import json
from datetime import datetime

from odie.mac import calendar, mail, permissions, scripts
from odie.watch.calls import Result

MAIL_TOOL = "mac_mail_new"
EVENTS_TOOL = "mac_calendar_events"
APP_OF = {MAIL_TOOL: "mail", EVENTS_TOOL: "calendar"}


def _time(text) -> datetime:
    t = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    return t.replace(tzinfo=None) if t.tzinfo is None else t.astimezone().replace(tzinfo=None)  # the Mac's local time


async def call(tool: str, args: dict) -> Result:
    """mac_mail_new {since, limit} -> the inbox since then as JSON; mac_calendar_events {start, end} -> the events.
    An app not allowed -> an error Result, and the denial remembered so Settings shows it."""
    app_id = APP_OF.get(tool)
    if app_id is None:
        return Result(f"no such Mac source: {tool}", True)
    try:
        if tool == MAIL_TOOL:
            rows = await mail.new_mail(_time(args["since"]), int(args.get("limit") or mail.MAX))
        else:
            rows = await calendar.events(_time(args["start"]), _time(args["end"]))
    except scripts.MacPermission as e:
        permissions.remember(app_id, permissions.DENIED)
        return Result(f"Odie isn't allowed to read {e} any more: allow it in Settings → Mac apps", True)
    except (scripts.MacError, ValueError, KeyError) as e:
        return Result(str(e)[:300] or type(e).__name__, True)
    return Result(json.dumps(rows), False)
