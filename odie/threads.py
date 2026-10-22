"""Threads: every chat conversation (a day's segment: chat-YYYY-MM-DD[-n]) as a list the user can search, pin and rename,
read from the session store (read-only). The title is the user's first message in it unless they renamed it."""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import UTC, datetime

from odie import config
from odie.store.db import Store

ID_RE = re.compile(r"^(chat-\d{4}-\d{2}-\d{2}(-\d+)?|chat-desk)$")
DESK = "chat-desk"  # the watch's own conversation: its morning round, urgent items and news (never the user's chat)
DESK_TITLE = "Desk"
TITLE_MAX = 70


def valid_id(sid: str) -> bool:
    return bool(ID_RE.match(sid or ""))


def _meta(store: Store) -> dict[str, dict]:
    return {r["session_id"]: dict(r) for r in store.query("select * from threads")}


def set_pinned(store: Store, sid: str, pinned: bool) -> None:
    at = datetime.now(UTC).isoformat(timespec="seconds") if pinned else None
    store.execute("insert into threads(session_id, pinned_at) values (?,?) on conflict(session_id) do update set pinned_at=excluded.pinned_at",
                  (sid, at))


def rename(store: Store, sid: str, title: str) -> None:
    t = " ".join((title or "").split())[:TITLE_MAX] or None
    store.execute("insert into threads(session_id, title) values (?,?) on conflict(session_id) do update set title=excluded.title", (sid, t))


def _text(event_data: str) -> tuple[str, str]:
    try:
        d = json.loads(event_data)
    except ValueError:
        return "", ""
    parts = ((d.get("content") or {}).get("parts")) or []
    return d.get("author") or "", "".join(p.get("text") or "" for p in parts if isinstance(p, dict))


def _clean(text: str) -> str:
    from odie.app.runner import split_images, strip_trailer
    return " ".join(split_images(strip_trailer(text))[0].split())


def list_threads(store: Store, q: str | None = None) -> list[dict]:
    """Chat threads that have at least one of the user's messages: pinned first, then the most recent."""
    from odie.app.runner import CHECK_PREFIX
    s = config.settings
    path = s.sessions_db_path
    if not path.exists():
        return []
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        sessions = {r[0]: r[1] for r in db.execute("select id, update_time from sessions where app_name=? and user_id=? and id like 'chat-%'",
                                                   (s.app_name, s.user_id))}
        rows = db.execute("select session_id, timestamp, event_data from events where app_name=? and user_id=? and session_id like 'chat-%' "
                          "order by timestamp", (s.app_name, s.user_id)).fetchall()
    finally:
        db.close()
    info: dict[str, dict] = {}
    needle = (q or "").strip().lower()
    for sid, ts, data in rows:
        if sid not in sessions or not valid_id(sid):
            continue
        author, text = _text(data)
        if not text or text.startswith(CHECK_PREFIX):
            continue
        t = info.setdefault(sid, {"first": None, "messages": 0, "snippet": None, "started": ts})
        if author == "user":
            clean = _clean(text)
            if not clean:
                continue
            t["first"] = t["first"] or clean
            t["messages"] += 1
        elif text.startswith("("):
            continue  # dividers like (New chat.) and (Continuing from earlier today.), whichever agent wrote them
        else:
            t["messages"] += 1
            clean = _clean(text)
        if needle and t["snippet"] is None and needle in clean.lower():
            i = clean.lower().index(needle)
            t["snippet"] = ("…" if i > 40 else "") + clean[max(0, i - 40): i + 80]
    meta = _meta(store)
    out = []
    for sid, t in info.items():
        if sid == DESK:  # only Odie writes there at first; it is always listed, pinned, under its own name
            t["first"] = t["first"] or DESK_TITLE
        if not t["first"]:
            continue
        m = meta.get(sid, {})
        title = m.get("title") or (t["first"][:TITLE_MAX] + ("…" if len(t["first"]) > TITLE_MAX else ""))
        date = sid[5:15]
        pinned_at = m.get("pinned_at")
        if sid == DESK:
            title = DESK_TITLE
            date = datetime.fromtimestamp(sessions[sid]).strftime("%Y-%m-%d")
            pinned_at = pinned_at or "9999-12-31T00:00:00"  # pinned above every pin the user made
        if needle and t["snippet"] is None and needle not in title.lower():
            continue
        out.append({"id": sid, "title": title, "renamed": bool(m.get("title")), "date": date, "messages": t["messages"],
                    "started": t["started"], "updated": sessions[sid], "pinned": bool(pinned_at), "pinned_at": pinned_at,
                    "snippet": t["snippet"]})
    out.sort(key=lambda x: (not x["pinned"], -(datetime.fromisoformat(x["pinned_at"]).timestamp() if x["pinned_at"] else 0), -x["updated"]))
    return out
