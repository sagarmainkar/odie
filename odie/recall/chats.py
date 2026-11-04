"""Recall's source: the words of past chats, read out of ADK's session store (sessions.db), read-only.

No chats are left out, including signed-in ones (Sagar's decision, 4 Nov).

A chat session can live for days (a book chat like chat-2026-10-30-5 is still in use long after its id's date), so a
line's day comes from its own message time in the user's timezone, never from the session id."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from odie.app.runner import CHECK_PREFIX
from odie.threads import _clean, _text

EXCHANGE_CAP = 2000


@dataclass(frozen=True)
class ChatLine:
    session_id: str
    ts: float
    day: str  # ISO date of the message in the user's timezone
    author: str  # "you" or "odie"
    text: str


@dataclass(frozen=True)
class Exchange:
    session_id: str
    ts: float  # when the user's message was sent
    day: str
    text: str  # "you: ...\nOdie: ...", cut at the cap


def _line_from_event(session_id: str, ts: float, event_data: str, tz) -> ChatLine | None:
    """One stored event as a line of words, or None when it carries no words worth recalling.

    Left out: tool calls and results (no text), Odie's nudges to itself (start with CHECK_PREFIX), dividers such as
    "(New chat.)" (Odie text starting with "("), and messages that are empty once Odie's trailer is stripped.
    Examples: tool call -> None; "(New chat.)" from odie -> None; user "Hi\\n\\n[context: 9am]" -> "Hi"."""
    author, text = _text(event_data)
    if not text or text.startswith(CHECK_PREFIX):
        return None
    if author == "user":
        who = "you"
    else:
        if text.startswith("("):
            return None
        who = "odie"
    clean = _clean(text)
    if not clean:
        return None
    day = datetime.fromtimestamp(ts, tz).date().isoformat()
    return ChatLine(session_id, ts, day, who, clean)


def chat_lines(sessions_db: Path, app: str, user: str, since: float, until: float, tz) -> list[ChatLine]:
    """Every chat session's user and Odie words with since <= ts < until, oldest first."""
    if not sessions_db.exists():
        return []
    db = sqlite3.connect(f"file:{sessions_db}?mode=ro", uri=True)
    try:
        rows = db.execute(
            "select session_id, timestamp, event_data from events "
            "where app_name=? and user_id=? and session_id like 'chat-%' and timestamp >= ? and timestamp < ? "
            "order by timestamp",
            (app, user, since, until)).fetchall()
    finally:
        db.close()
    lines = []
    for session_id, ts, event_data in rows:
        line = _line_from_event(session_id, ts, event_data, tz)
        if line is not None:
            lines.append(line)
    return lines


def exchanges(lines: list[ChatLine], cap: int = EXCHANGE_CAP) -> list[Exchange]:
    """Group lines into exchanges: a user message plus the Odie replies that follow it in the same chat.

    Odie words before a chat's first user message in the window have no question to pair with and are dropped.
    Example: you, odie, odie, you, odie -> two exchanges, the first "you: ...\\nOdie: ...\\nOdie: ..."."""
    open_by_chat: dict[str, dict] = {}
    started: list[dict] = []
    for line in lines:
        if line.author == "you":
            current = {"session_id": line.session_id, "ts": line.ts, "day": line.day, "parts": ["you: " + line.text]}
            open_by_chat[line.session_id] = current
            started.append(current)
        else:
            current = open_by_chat.get(line.session_id)
            if current is not None:
                current["parts"].append("Odie: " + line.text)
    return [Exchange(e["session_id"], e["ts"], e["day"], "\n".join(e["parts"])[:cap]) for e in started]
