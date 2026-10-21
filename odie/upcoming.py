"""Up next: everything coming up in the next two weeks, from the user's dated tasks and whatever the add-ons bring (a
calendar, the SMS ledger, confirmation mails), merged into one list for Today."""
from __future__ import annotations

import logging
import re
import time
from datetime import date, datetime, timedelta

from odie.store.db import Store

log = logging.getLogger("odie.upcoming")
DAYS = 14

# Kind of event, by keywords in its title (first match wins; order matters).
KINDS: list[tuple[str, str]] = [
    ("birthday", r"birthday|\bb'?day\b|\bbd\b|\bbdy\b|janmadin|vadhdivas"),
    ("celebration", r"anniversary|wedding|engagement|reception|sangeet|mehendi"),
    ("medical", r"\bdr\.?\s|\bdr\b|doctor|clinic|hospital|dentist|dental|physio|\blab\b|blood test|scan\b|check-?up|cardio|derma|ortho|"
                r"\bent\b|eye test|vaccin|pathology|diagnostic"),
    ("travel", r"flight|airport|\btrain\b|irctc|\bpnr\b|boarding|hotel|check-?in|\btrip\b|travel|\bbus\b|\b[A-Z0-9]{2}\s?\d{3,4}\b"),
    ("insurance", r"insurance|mediclaim|\blic\b|premium|policy"),
    ("card", r"credit card|card bill|card due|\bcard\b.*\b(due|bill|statement)"),
    ("bill", r"\bbill\b|postpaid|electricity|broadband|\bemi\b|\brent\b|\bdue\b|recharge|maintenance"),
    ("delivery", r"deliver|shipped|out for delivery|parcel|courier|order\b"),
    ("call", r"\bcall\b|zoom|meet\.google|google meet|teams|webex|video"),
    ("meeting", r"meeting|\bsync\b|stand-?up|review|interview|\b1:1\b|one on one|demo|client|workshop|offsite|presentation"),
    ("meal", r"lunch|dinner|breakfast|coffee|brunch|drinks|restaurant|table for|cafe"),
    ("fitness", r"\bgym\b|yoga|\brun\b|running|workout|swim|cricket|football|badminton|tennis|pilates|trek"),
    ("school", r"school|\bptm\b|\bexam\b|\bclass\b|tuition|parents?'? meet"),
    ("show", r"concert|movie|\bshow\b|\bmatch\b|ticket|bookmyshow|festival|play\b|standup comedy|gig"),
]
_KIND_RE = [(k, re.compile(p, re.I)) for k, p in KINDS]
_PRIORITY = {"calendar": 0, "mail": 1, "sms": 2, "task": 3}
_PREFIX = {"calendar": "cal", "mail": "mail", "sms": "sms", "task": "task"}


def kind_for(title: str) -> str:
    for k, rx in _KIND_RE:
        if rx.search(title or ""):
            return k
    return "general"


def _when(d: str, t: str | None, today: date) -> str:
    day = date.fromisoformat(d)
    label = "today" if day == today else "tomorrow" if day == today + timedelta(days=1) else day.strftime("%A %-d %b")
    return f"{label} at {t}" if t else label


def ask_for(kind: str, title: str, when: str) -> str:
    return {
        "medical": f"Help me prepare for {title} {when}",
        "meeting": f"Help me prepare for {title} {when}",
        "call": f"Help me prepare for {title} {when}",
        "birthday": f"Ideas for {title}",
        "celebration": f"Ideas for {title}",
        "travel": f"What do I need for {title} {when}?",
        "card": f"Help me pay {title}",
        "bill": f"Help me pay {title}",
        "insurance": f"What's due for {title}?",
        "delivery": f"Where is {title}?",
    }.get(kind, f"Tell me about {title} {when}")


def _item(source: str, iid: str, title: str, d: str, today: date, t: str | None = None, end: str | None = None,
          place: str | None = None, people: list[str] | None = None, amount: float | None = None, kind: str | None = None) -> dict:
    k = kind or kind_for(title)
    return {"id": f"{_PREFIX.get(source, source)}:{iid}", "source": source, "kind": k, "title": title, "date": d, "time": t, "end": end,
            "place": place, "people": people, "amount": amount, "ask": ask_for(k, title, _when(d, t, today))}


# ── tasks ──
def from_tasks(store: Store, now: datetime, days: int = DAYS) -> list[dict]:
    """The user's dated tasks; the ledger's own copies (its dues) come from the ledger directly."""
    end = (now + timedelta(days=days)).isoformat()
    out = []
    for r in store.query("select id, title, due_at from tasks where status in ('open','waiting') and due_at is not null "
                         "and due_at >= ? and due_at <= ? and coalesce(source_kind,'') != 'ledger' order by due_at",
                         (now.date().isoformat(), end)):
        due = r["due_at"]
        t = due[11:16] if len(due) >= 16 and due[11:16] != "00:00" else None
        out.append(_item("task", str(r["id"]), r["title"], due[:10], now.date(), t))
    return out


# ── merge ──
def _words(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", s.lower()) if len(w) > 1}


def _same(a: dict, b: dict) -> bool:
    """The same real thing in two sources: a shared code (flight number, PNR), or real word overlap. A shared start
    time only counts with at least one shared word (a 09:00 task and a 09:00 standup are different things)."""
    if a["date"] != b["date"]:
        return False
    wa, wb = _words(a["title"]), _words(b["title"])
    shared = wa & wb
    if any(re.search(r"\d", w) and len(w) >= 3 for w in shared):
        return True
    if a.get("time") and a.get("time") == b.get("time") and shared:
        return True
    return len(shared) >= 2 and len(shared) / min(len(wa), len(wb)) >= 0.5


def merge(items: list[dict]) -> list[dict]:
    """One entry per real thing (a flight in the calendar and in a mail shows once), soonest first."""
    out: list[dict] = []
    for it in sorted(items, key=lambda i: _PRIORITY.get(i["source"], len(_PRIORITY))):  # an add-on's own source sorts last
        hit = next((o for o in out if it["source"] not in o["sources"] and _same(o, it)), None)  # two calendar events never merge
        if hit:
            hit["sources"].append(it["source"])
            for k in ("time", "end", "place", "amount", "people"):
                if hit.get(k) is None and it.get(k) is not None:
                    hit[k] = it[k]
        else:
            out.append({**it, "sources": [it["source"]]})
    return sorted(out, key=lambda i: (i["date"], i["time"] or "00:00"))


# ── all of it ──
async def build(store: Store, now: datetime, days: int = DAYS) -> dict:
    """The user's dated tasks, plus what each add-on brings (a calendar, the SMS ledger's dues and orders, mail)."""
    sources, items = {}, from_tasks(store, now, days)
    from odie import addons
    for more, have in await addons.acall("upcoming", store, now, days):
        items += more
        sources.update(have)
    if not sources.get("calendar"):  # no add-on calendar: the watch's last check brings the events
        card = store.get_setting("watch.card") or {}
        for e in card.get("events", []):
            start = str(e.get("start") or "")
            if len(start) >= 10:
                it = _item("calendar", f"watch:{e.get('id')}", str(e.get("title") or ""), start[:10], now.date(),
                           start[11:16] if len(start) >= 16 else None, str(e.get("end") or "")[11:16] or None, e.get("where") or None)
                it["badges"] = list(e.get("badges") or [])  # where the event came from (Gmail, iCloud), for its row
                items.append(it)
        if card.get("events"):
            sources["calendar"] = True
    return {"items": merge(items), "sources": sources}
