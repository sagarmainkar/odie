"""The Contacts app through its AppleScript: people whose name holds a query."""
from __future__ import annotations

import json

from odie.mac import scripts

APP = "Contacts"
MAX = 10


async def find(query: str, limit: int = MAX, run=scripts.run) -> list[dict]:
    """People whose name contains `query`, at most `limit`: name, emails, phones, birthday (YYYY-MM-DD or "")."""
    q = query.strip()
    if len(q) < 2:
        raise scripts.MacError("Give at least two characters of the name.")
    text = await run("contacts_find", q, str(max(1, min(limit, 50))), app=APP)
    got = json.loads(text) if text else []
    return [r for r in got if isinstance(r, dict)] if isinstance(got, list) else []
