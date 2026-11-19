"""The digests (proactive design §8, his decision of 19 Nov in §17): "while you were away".

  evening  at 19:30, with the evening review: what needs him, what got done today, what Odie did, the cards that are
           digest lines instead (a kind he quieted or rarely acts on), what was held back from his phone, and what the
           review changed (each with Undo). Its words are the review's own (one call, no extra), checked by code, or
           code's when there was no call. A push ONLY when something needs him (needs_him), within the shared 3 a day
           (odie.watch.pushes); 22:00-07:00 it is held for the morning brief, as the other pushes are. Otherwise he
           sees it on opening the app (Pulse), until he says Got it.
  away     on opening Pulse after AWAY or more since his last visit, when something happened meanwhile: code's words
           alone, no model call.

Everything here is per owner (everyday Odie, each personality)."""
from __future__ import annotations

import re
from datetime import datetime, time, timedelta

from odie.loops import cards, ledger, quiet
from odie.loops.secret import secret_in

EVENING = "digest.evening"  # per owner (odie.watch.owner.key): {"day", "at", "text", "needs", "done", "held", "said", "dismissed"}
SEEN = "digest.seen"  # per owner: when he last opened Pulse
AWAY = timedelta(hours=3)
TEXT_MOST = 400
NAMES_SHOWN = 3
ADDRESS = re.compile(r"https?://|www\.|\b[\w.-]+\.(com|net|org|io|in|co|app|dev|xyz|ru)\b/", re.I)


def _key(pid: str, name: str) -> str:
    from odie.watch.owner import key
    return key(name, pid)


def start_of_day(now: datetime) -> datetime:
    return datetime.combine(now.date(), time(0, 0), now.tzinfo)


def names(titles: list[str]) -> str:
    """A few titles in one phrase: ["A", "B"] -> "A, B"; five -> "A, B, C and 2 more"; [] -> ""."""
    shown = ", ".join(titles[:NAMES_SHOWN])
    if len(titles) > NAMES_SHOWN:
        shown += f" and {len(titles) - NAMES_SHOWN} more"
    return shown


def held_today(store, pid: str, now: datetime, take: bool = False) -> list[str]:
    """The pushes held back today for this owner over the day's budget (odie.watch.pushes.HELD), as titles; with take,
    they are taken out of the held list (the evening digest says them)."""
    from odie.watch import pushes
    held = list(store.get_setting(pushes.HELD) or [])
    start = start_of_day(now)
    mine = []
    rest = []
    for item in held:
        at = item.get("at") or ""
        is_mine = (item.get("owner") or "") == pid and at and datetime.fromisoformat(at) >= start
        if is_mine:
            mine.append(str(item.get("title") or ""))
        else:
            rest.append(item)
    if take and mine:
        store.set_setting(pushes.HELD, rest)
    return [t for t in mine if t]


def facts(store, pid: str, now: datetime, since: datetime | None = None) -> dict:
    """What a digest is made of, for this owner, since the start of today (or `since`): his cards (and those new since),
    the loops Odie closed (with why), how many he closed himself, the digest lines, the pushes held back."""
    if since is None:
        since = start_of_day(now)
    ready = cards.ready_loops(store, pid, now)
    new = [lp for lp in ready if (lp.get("shown_at") or "") and datetime.fromisoformat(lp["shown_at"]) >= since]
    odie_closed = ledger.closed_since(store, pid, since)
    mine, values = ledger._whose(pid)
    early = (since - timedelta(days=1)).isoformat(timespec="seconds")  # a day early: offsets differ; checked below
    his = store.query(f"select closed_at from loops where closed_by in (?, ?) and closed_at >= ? and {mine}",
                      (*ledger.BY_HIM, early, *values))
    by_him = [r for r in his if r["closed_at"] and datetime.fromisoformat(r["closed_at"]) >= since]
    return {"needs": [lp["title"] for lp in ready], "new": [lp["title"] for lp in new],
            "odie_closed": [{"title": lp["title"], "why": lp["closed_why"] or ""} for lp in odie_closed],
            "you_closed": len(by_him),
            "quiet": [{"id": lp["id"], "title": lp["title"]} for lp in quiet.digest_lines(store, pid, now)],
            "held": held_today(store, pid, now)}


def facts_text(f: dict) -> str:
    """The day's facts as the evening review reads them (fenced there), one line each."""
    lines = [f"Needs the user: {len(f['needs'])}" + (f" ({names(f['needs'])})" if f["needs"] else "")]
    if f["odie_closed"]:
        lines.append("Odie closed today: " + "; ".join(f"{c['title']}: {c['why']}" for c in f["odie_closed"][:6]))
    if f["you_closed"]:
        lines.append(f"The user finished today: {f['you_closed']}")
    if f["quiet"]:
        lines.append("In the digest instead of cards: " + names([q["title"] for q in f["quiet"]]))
    if f["held"]:
        lines.append("Held back from the phone today: " + names(f["held"]))
    return "\n".join(lines)


def code_text(f: dict, away: bool = False) -> str:
    """The digest in code's words (no call): "2 need you: Reply to Asha, Gas bill. Odie closed 1: Order: lamp. You
    finished 3." Away: only what is new since he left ("1 new for you: …"). Nothing -> ""."""
    parts = []
    needs = f["needs"]
    if away:
        needs = f["new"]
    if needs:
        word = "need you"
        if len(needs) == 1:
            word = "needs you"
        if away:
            word = "new for you"
        parts.append(f"{len(needs)} {word}: {names(needs)}.")
    if f["odie_closed"]:
        parts.append(f"Odie closed {len(f['odie_closed'])}: {names([c['title'] for c in f['odie_closed']])}.")
    if f["you_closed"] and not away:
        parts.append(f"You finished {f['you_closed']}.")
    if f["quiet"] and not away:
        parts.append(f"In the digest: {names([q['title'] for q in f['quiet']])}.")
    return " ".join(parts)


def checked_text(text) -> str | None:
    """The review's digest words as they may be shown and pushed: one paragraph of at most TEXT_MOST characters, with
    no web address and nothing secret-shaped; else None (code's words are used).
      "Two things need you: the reply to Asha and the gas bill." -> kept;  "Open http://x.example now" -> None;
      "Your PIN is 4321" -> None;  "" -> None"""
    if not isinstance(text, str):
        return None
    one = " ".join(text.split())
    if not one or ADDRESS.search(one) or secret_in(one):
        return None
    if len(one) > TEXT_MOST:
        one = one[:TEXT_MOST].rsplit(" ", 1)[0] + "…"
    return one


def seen_at(store, pid: str) -> datetime | None:
    saved = store.get_setting(_key(pid, SEEN))
    if not saved:
        return None
    return datetime.fromisoformat(saved)


def pulse_seen_at(store, pid: str) -> str:
    """When this owner's Pulse was last opened (the watch card's seen_at), or ""."""
    from odie.watch import report
    card = store.get_setting(_key(pid, report.CARD)) or {}
    return str(card.get("seen_at") or "")


def needs_him(store, pid: str, now: datetime) -> bool:
    """Whether the evening digest pushes: a card he hasn't seen yet (shown after he last opened Pulse), or a card due
    by the end of tomorrow. A card new since lunch, Pulse last opened at 09:00 -> True; a card he saw at noon, due next
    week -> False; a card due tomorrow 10:00 -> True; no cards (or only digest lines) -> False."""
    seen = pulse_seen_at(store, pid)
    end_of_tomorrow = start_of_day(now) + timedelta(days=2)
    for loop in cards.ready_loops(store, pid, now):
        if (loop.get("shown_at") or "") > seen:
            return True
        due = loop.get("due_at")
        if due and datetime.fromisoformat(due) < end_of_tomorrow:
            return True
    return False


def night(now: datetime) -> bool:
    """No push from 22:00 to 07:00: 23:00 -> True; 19:30 -> False."""
    return now.hour >= 22 or now.hour < 7


def make_evening(store, pid: str, now: datetime, text: str | None) -> dict:
    """Saves today's evening digest: the review's checked words, else code's. The pushes held back today are taken
    into it (said here, not again)."""
    f = facts(store, pid, now)
    held_today(store, pid, now, take=True)
    words = checked_text(text)
    if words is None:
        words = code_text(f)
    digest = {"day": now.date().isoformat(), "at": now.isoformat(timespec="seconds"), "text": words,
              "needs": f["needs"], "done": f["odie_closed"], "held": f["held"], "said": "", "dismissed": False}
    store.set_setting(_key(pid, EVENING), digest)
    return digest


def evening(store, pid: str) -> dict | None:
    return store.get_setting(_key(pid, EVENING)) or None


def tell(store, pid: str, now: datetime, digest: dict, push) -> str:
    """The evening digest's push, only when something needs him: "quiet" (nothing needs him, or no words, or no
    push), "held" (night: kept for the morning brief), "pushed", or "over budget" (held for tomorrow's digest)."""
    from odie.watch import pushes, report
    from odie.watch.owner import key
    said = "quiet"
    if push is not None and digest["text"] and needs_him(store, pid, now):
        if night(now):
            held_key = key(report.HELD, pid)
            held = [*(store.get_setting(held_key) or []), {"ref": "digest", "title": "Evening digest",
                                                          "why": digest["text"]}]
            store.set_setting(held_key, held[-20:])
            said = "held"
        elif pushes.started_by_odie(store, now, pid, "Evening digest", digest["text"], push,
                                    ref=f"digest:{digest['day']}"):
            said = "pushed"
        else:
            said = "over budget"
    store.set_setting(_key(pid, EVENING), {**digest, "said": said})
    return said


def for_pulse(store, pid: str, now: datetime, changes: list[dict] | None = None) -> dict | None:
    """What Pulse shows on opening: today's evening digest until he says Got it; else, after AWAY or more since his
    last visit, what happened meanwhile (code's words) when anything did; else None. The digest lines (with Done) are
    read now, so a Done since is gone."""
    lines = [{"id": lp["id"], "title": lp["title"]} for lp in quiet.digest_lines(store, pid, now)]
    today = evening(store, pid)
    if today and today["day"] == now.date().isoformat() and not today.get("dismissed"):
        return {"kind": "evening", "title": "This evening", "text": today["text"], "at": today["at"],
                "quiet": lines, "held": today.get("held") or [], "changes": changes or []}
    last = seen_at(store, pid)
    if last is None or now - last < AWAY:
        return None
    f = facts(store, pid, now, since=last)
    text = code_text(f, away=True)
    if not text:
        return None
    return {"kind": "away", "title": "While you were away", "text": text, "at": now.isoformat(timespec="seconds"),
            "quiet": lines, "held": [], "changes": []}


def seen(store, pid: str, now: datetime, dismiss: bool = False) -> None:
    """He opened Pulse (the away digest starts counting from now); with dismiss, his Got it on today's evening one."""
    store.set_setting(_key(pid, SEEN), now.isoformat(timespec="seconds"))
    today = evening(store, pid)
    if dismiss and today:
        store.set_setting(_key(pid, EVENING), {**today, "dismissed": True})
