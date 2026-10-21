"""The Reminders app through its AppleScript: what is due by a time, and adding one."""
from __future__ import annotations

import json
from datetime import datetime

from odie.mac import scripts

APP = "Reminders"


async def due(before: datetime, run=scripts.run) -> list[dict]:
    """Open reminders due before `before` (local time), every list: id, title, due (ISO with offset), list."""
    text = await run("reminders_due", before.strftime("%Y-%m-%dT%H:%M:%S"), app=APP)
    got = json.loads(text) if text else []
    return [r for r in got if isinstance(r, dict)] if isinstance(got, list) else []


async def add(title: str, due_at: datetime, list_name: str = "", run=scripts.run) -> dict:
    """Makes a reminder in the named list ("" = the default list) and returns {id, list}."""
    if not title.strip():
        raise scripts.MacError("A reminder needs a title.")
    text = await run("reminder_add", title.strip(), due_at.strftime("%Y-%m-%dT%H:%M:%S"), list_name.strip(), app=APP)
    got = json.loads(text)
    if not isinstance(got, dict) or not got.get("id"):
        raise scripts.MacError("Reminders made no reminder.")
    return got
