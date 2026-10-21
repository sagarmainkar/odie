"""Apple Mail through its own AppleScript: the inbox since a time, one message in full, an attachment saved. Mail
lists the inbox newest first and the walk stops at the first older message, so a big mailbox costs nothing extra."""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from odie.mac import scripts

APP = "Mail"
MAX = 25
BODY_CHARS = 6000
SAFE_NAME = re.compile(r"^[^/\\\x00]{1,200}$")


def _rows(text: str) -> list[dict]:
    got = json.loads(text) if text else []
    return [r for r in got if isinstance(r, dict)] if isinstance(got, list) else []


async def new_mail(since: datetime, limit: int = MAX, run=scripts.run) -> list[dict]:
    """Messages received since `since` (local time), newest first, at most `limit`: id ("mac:<n>"), from, subject,
    at (ISO with offset), snippet (the first 300 characters, for the first eight), attachments [{name, size}]."""
    text = await run("mail_new", since.strftime("%Y-%m-%dT%H:%M:%S"), str(max(1, min(limit, 100))), app=APP)
    return _rows(text)


async def read(mail_id: str, run=scripts.run) -> dict:
    """One message in full (the body trimmed to BODY_CHARS): id, from, subject, at, body, attachments."""
    if not mail_id.startswith("mac:") or not mail_id[4:].isdigit():
        raise scripts.MacError("That isn't one of Mail's message ids.")
    text = await run("mail_read", mail_id, str(BODY_CHARS), app=APP)
    got = json.loads(text)
    if not isinstance(got, dict):
        raise scripts.MacError("Mail gave no message.")
    return got


async def save_attachment(mail_id: str, name: str, into: Path, run=scripts.run) -> Path:
    """Saves the named attachment of a message into the folder `into` (made if needed) and returns the file's path.
    ("mac:12", "bill.pdf", ~/.odie/data/workspace/watch/mac_12) -> that folder / bill.pdf"""
    if not mail_id.startswith("mac:") or not mail_id[4:].isdigit():
        raise scripts.MacError("That isn't one of Mail's message ids.")
    if not SAFE_NAME.match(name) or name in (".", "..") or ".." in name:
        raise scripts.MacError("That isn't a file name.")
    into = into.resolve()
    into.mkdir(parents=True, exist_ok=True)
    text = await run("mail_save_attachment", mail_id, name, str(into), app=APP)
    got = json.loads(text)
    path = Path(str(got.get("path") or "")).resolve()
    if into not in path.parents:
        raise scripts.MacError("Mail saved the file somewhere else.")
    return path
