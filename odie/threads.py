"""Threads: every chat conversation (a day's segment: chat-YYYY-MM-DD[-n]) as a list the user can search, pin and rename,
read from the session store (read-only). The title is the user's first message in it unless they renamed it."""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import UTC, datetime

from odie import config
from odie.store.db import Store

ID_RE = re.compile(r"^chat-\d{4}-\d{2}-\d{2}(-\d+)?$")
TITLE_MAX = 70


def valid_id(sid: str) -> bool:
    return bool(ID_RE.match(sid or ""))


def segment_of(sid: str) -> int:
    """A thread id's number within its day: "chat-2026-11-17" -> 1; "chat-2026-11-17-4" -> 4."""
    parts = sid.split("-")  # "chat", year, month, day, and the number when there is one
    if len(parts) == 5:
        return int(parts[4])
    return 1


def is_imported(sid: str) -> bool:
    """Whether a thread was imported from a replay (odie.replay_threads numbers those from 101, far past any new chat
    of a day), so it is a thread on its own and never part of a day's chat or of the day's numbering:
    "chat-2026-10-11-101" -> True; "chat-2026-10-11-3" -> False; "chat-2026-10-11" -> False."""
    from odie.replay_threads import FIRST_SEGMENT
    return segment_of(sid) >= FIRST_SEGMENT


def session_ids_on(date: str) -> list[str]:
    """Every chat session of that date in the session store, by number, whoever it belongs to:
    ["chat-2026-11-17", "chat-2026-11-17-3"]; a day nobody chatted -> []."""
    s = config.settings
    path = s.sessions_db_path
    if not path.exists():
        return []
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        rows = db.execute("select id from sessions where app_name=? and user_id=? and (id=? or id like ?)",
                          (s.app_name, s.user_id, f"chat-{date}", f"chat-{date}-%")).fetchall()
    finally:
        db.close()
    ids = [r[0] for r in rows if valid_id(r[0])]
    return sorted(ids, key=segment_of)


def next_free_id(store: Store, date: str) -> str:
    """The id for a new thread on that date: numbered 2 or more, and above every number already in use that day, in the
    session store or claimed in `threads` (a personality's thread is claimed a moment before its session is made).
    The bare "chat-<date>" is never given out: it is everyday Odie's first chat of the day. Imported threads
    (is_imported) have their own numbers and don't count.
      nothing yet today                          -> "chat-<date>-2"
      Odie on chat-<date>, Mira on chat-<date>-2 -> "chat-<date>-3"
      only chat-<date> and an imported -101      -> "chat-<date>-2" """
    in_store = session_ids_on(date)
    claimed = [r["session_id"] for r in store.query("select session_id from threads where session_id=? or session_id like ?",
                                                    (f"chat-{date}", f"chat-{date}-%"))]
    numbers = [segment_of(sid) for sid in [*in_store, *claimed] if valid_id(sid) and not is_imported(sid)]
    highest = max(numbers, default=1)
    return f"chat-{date}-{highest + 1}"


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
    """A message as a title or a search snippet shows it: without what Odie appended, its image markers, or a form
    answer's fence (odie.blocks.answers), on one line."""
    from odie.app.runner import split_images, strip_trailer
    from odie.blocks.answers import without_form_answers
    return " ".join(without_form_answers(split_images(strip_trailer(text))[0]).split())


def list_threads(store: Store, q: str | None = None, personality: str = "") -> list[dict]:
    """The chat threads of one personality (everyday Odie's when none is named) that have at least one of the user's
    messages: pinned first, then the most recent. Nobody's list ever holds another's thread, and a search reads only
    the threads listed."""
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
    meta = _meta(store)
    for sid, ts, data in rows:
        if sid not in sessions or not valid_id(sid):
            continue
        owner = meta.get(sid, {}).get("personality") or ""
        if owner != personality:
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
    out = []
    for sid, t in info.items():
        if not t["first"]:
            continue
        m = meta.get(sid, {})
        title = m.get("title") or (t["first"][:TITLE_MAX] + ("…" if len(t["first"]) > TITLE_MAX else ""))
        date = sid[5:15]
        pinned_at = m.get("pinned_at")
        if needle and t["snippet"] is None and needle not in title.lower():
            continue
        out.append({"id": sid, "title": title, "renamed": bool(m.get("title")), "date": date, "messages": t["messages"],
                    "started": t["started"], "updated": sessions[sid], "pinned": bool(pinned_at), "pinned_at": pinned_at,
                    "snippet": t["snippet"]})
    out.sort(key=lambda x: (not x["pinned"], -(datetime.fromisoformat(x["pinned_at"]).timestamp() if x["pinned_at"] else 0), -x["updated"]))
    return out
