"""The pushes Odie starts on its own (18 Nov 2026, proactive design §8): at most DAILY a day, shared by everyday Odie
and every personality, because there is one phone. What the watch or a loop wants to push past that is held for the
digest instead (it is on Pulse either way). Pushes that don't count: the user's own reminders, the reports of jobs he
started, the results of his Watch for entries and "an app stopped working".

A personality's push is titled with its name ("Mira · Reply to Asha"), so the lock screen says whose it is; the body
is one line of news. Everyday Odie's keep the titles they always had."""
from __future__ import annotations

from datetime import datetime

DAILY = 3
KEY = "push.budget"  # {"day": "2026-11-18", "sent": 2}: today's count of pushes Odie started
HELD = "push.held"  # what was over the budget, for the digest: [{"at", "title", "body"}], newest last
KEEP_HELD = 20


def sent_today(store, now: datetime) -> int:
    """How many pushes Odie started today: the saved count when it is today's, else 0 (a new day starts at 0).
    {"day": "2026-11-18", "sent": 2} on 18 Nov -> 2; the same on 19 Nov -> 0; nothing saved -> 0."""
    saved = store.get_setting(KEY) or {}
    if saved.get("day") != now.date().isoformat():
        return 0
    return int(saved.get("sent") or 0)


def spend(store, now: datetime) -> bool:
    """Takes one push from today's budget. True when one was left (and it is now used); False when today's DAILY are
    gone. Third push of the day -> True; the fourth -> False; the first one the next morning -> True."""
    sent = sent_today(store, now)
    if sent >= DAILY:
        return False
    store.set_setting(KEY, {"day": now.date().isoformat(), "sent": sent + 1})
    return True


def hold(store, now: datetime, title: str, body: str, owner: str = "", ref: str = "") -> None:
    """Keeps a push that was over the budget for the digest (phase 5 reads push.held; until then the item is on
    Pulse only), with whose it is and its card's ref."""
    held = list(store.get_setting(HELD) or [])
    held.append({"at": now.isoformat(timespec="seconds"), "title": title, "body": body, "owner": owner, "ref": ref})
    store.set_setting(HELD, held[-KEEP_HELD:])


def title_for(store, owner: str, text: str) -> str:
    """A push's title for whose it is. Everyday Odie's as it always was; a personality's starts with its name, so the
    lock screen says who: ("", "Reply to Asha") -> "Reply to Asha"; (Mira's id, "Reply to Asha") -> "Mira · Reply to
    Asha"; a personality deleted meanwhile -> the text alone."""
    if not owner:
        return text
    from odie import personalities
    found = personalities.get(store, owner)
    if found is None:
        return text
    return f"{found.name} · {text}"


def one_line(text: str, most: int = 160) -> str:
    """A push body: the first line, at most `most` characters. "Dropped to ₹4,200\\nlowest this week" -> "Dropped to
    ₹4,200"."""
    lines = (text or "").strip().splitlines()
    if not lines:
        return ""
    return lines[0][:most]


def started_by_odie(store, now: datetime, owner: str, title: str, body: str, send, ref: str = "") -> bool:
    """Sends one push Odie decided on (a needs-you item, a loop's card) when today's budget allows, else holds it for
    the digest. True when it was sent. `send(title, body)` does the sending."""
    whole_title = title_for(store, owner, title)
    line = one_line(body)
    if not spend(store, now):
        hold(store, now, whole_title, line, owner, ref)
        return False
    send(whole_title, line)
    return True
