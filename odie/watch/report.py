"""What a check leaves (spec part 3): the Today card, and the pushes with their rules: only items the model marks,
at most 3 a check, never one ref twice, none on the first check after a source appears, none from 22:00 to 07:00 (held
for the brief). A check that ends without a report gets a card written by code."""
from __future__ import annotations

from datetime import datetime

from odie.watch.fetch import Event, Mail

CARD, FLAGGED, HELD = "watch.card", "watch.flagged", "watch.held"
PILES = ("alerts", "bills", "events", "personal", "orders")  # where an item belongs (the parked Desk design's buckets)
WHY_MAX = 120
LABEL_MAX = 40
DRAFT_MAX = 4000
MAX_PUSH = 3
# A source is said to have stopped working on its 3rd failed check in a row (one or two misses are often a blip),
# and said to work again only when it comes back after that.
SAY_FAILING_AT = 3


def quiet(now: datetime) -> bool:
    """Night hours, when pushes are held for the brief. Example: 22:00 or 06:59 -> True; 07:00 or 21:59 -> False."""
    return now.hour >= 22 or now.hour < 7


def sender_name(frm: str) -> str:
    """The person's name in a From line, else the address as it is.
      "Priya Nair <priya@acme.example>" -> "Priya Nair";  '"CDSL" <noreply@cdsl.example>' -> "CDSL";  "a@b.c" -> "a@b.c" """
    name = frm.split("<")[0].strip().strip('"').strip()
    return name or frm.strip()


def badge_of(source_id: str, statuses: dict) -> dict:
    """Where an item came from, for the little mark on its row: {"kind": "gmail" | "icloud" | "app", "app": name}.
    "mail:mac" -> icloud, "Apple Mail"; "mail:gmail-calendar" with app "Gmail and Calendar" -> gmail; a Zapier
    Outlook source -> app, "Zapier"."""
    app = str((statuses.get(source_id) or {}).get("app") or "")
    if source_id.endswith(":mac"):
        return {"kind": "icloud", "app": app or ("Apple Mail" if source_id.startswith("mail") else "Calendar")}
    words = f"{source_id} {app}".lower()
    kind = "gmail" if "gmail" in words or "google" in words else "app"
    return {"kind": kind, "app": app or source_id.split(":", 1)[-1]}


def badges_of(source_ids: list[str], statuses: dict) -> list[dict]:
    """One badge per source, in order, none repeated."""
    out, seen = [], set()
    for sid in source_ids:
        b = badge_of(sid, statuses)
        if b["kind"] in seen and b["kind"] != "app":
            continue
        seen.add(b["kind"])
        out.append(b)
    return out


def _label(value) -> str:
    """A button's words from the model's suggestion or escape: {"label": "Reply with your fee"} -> that, trimmed to
    fit; no label, or not an object -> "". The model writes only the words, never what the tap sends."""
    if not isinstance(value, dict):
        return ""
    return str(value.get("label") or "").strip()[:LABEL_MAX]


def _amount(value) -> dict | None:
    """An amount as {"value": number, "currency": text}: {"value": 4280, "currency": "INR"} -> the same; "lots" ->
    None."""
    if not isinstance(value, dict):
        return None
    number = value.get("value")
    if isinstance(number, bool) or not isinstance(number, (int, float)):
        return None
    return {"value": number, "currency": str(value.get("currency") or "")[:8]}


def _draft(value) -> dict | None:
    """A drafted reply as {"to", "subject", "body"} with a body; anything else -> None. It stays in Odie: chat sends
    it only after the user's tap."""
    if not isinstance(value, dict):
        return None
    body = str(value.get("body") or "").strip()
    if not body:
        return None
    return {"to": str(value.get("to") or "")[:200], "subject": str(value.get("subject") or "")[:200],
            "body": body[:DRAFT_MAX]}


def _day(value) -> str | None:
    """A due date the card can show: "2026-10-24" or "2026-10-24T18:00" -> as given; "next week" -> None."""
    text = str(value or "").strip()
    try:
        datetime.fromisoformat(text)
    except ValueError:
        return None
    return text


def labelled(n: dict) -> dict:
    """The labels of one item the model reported, each kept only when it is usable; a bad one is left out, never the
    item. {"pile": "alerts", "suggestion": {"label": "Reply", "run": "…"}, "due": "2026-10-24"} -> those three;
    {"pile": "urgent", "suggestion": {}, "due": "next week"} -> {}. A suggestion's or escape's tap always sends Odie's
    own request naming the item ("Show the draft for desk item mail:m1", "Close desk item mail:m1: Not interested"),
    whatever run the model wrote."""
    out: dict = {}
    ref = str(n.get("ref") or "")
    pile = str(n.get("pile") or "").strip().lower()
    if pile in PILES:
        out["pile"] = pile
    draft = _draft(n.get("draft"))
    suggestion = _label(n.get("suggestion"))
    if suggestion:  # what a tap sends is Odie's own words, naming the item: a mail can't write it
        run = f"Desk item {ref}: {suggestion}"
        if draft:
            run = f"Show the draft for desk item {ref}"
        out["suggestion"] = {"label": suggestion, "run": run}
    escape = _label(n.get("escape"))
    if escape:
        out["escape"] = {"label": escape, "run": f"Close desk item {ref}: {escape}"}
    due = _day(n.get("due"))
    if due:
        out["due"] = due
    amount = _amount(n.get("amount"))
    if amount:
        out["amount"] = amount
    if draft:
        out["draft"] = draft
    return out


def _mail_fields(ref: str, mails: list[Mail], statuses: dict | None = None) -> dict:
    """What Today's row needs from the mail behind an item (web: watchRow): the sender's name, the subject, the mail's
    time, its gist, its badges, and the app that holds its id (the tap opens the mail there, by that id). {} for an
    event, or a mail that isn't in this check's list (an older item keeps what it had).
      "mail:m9" with m9 from "Priya Nair <priya@…>", "Lease renewal", at 06:00, snippet "Sign by Friday please.", read
      from Gmail -> {"from": "Priya Nair", "subject": "Lease renewal", "when": "2026-10-08T06:00:00Z",
      "gist": "Sign by Friday please.", "badges": [...], "app": "Gmail and Calendar"}
      "event:e1" -> {}"""
    mail = next((m for m in mails if f"mail:{m.id}" == ref), None)
    if mail is None:
        return {}
    holds_the_id = badge_of(mail.source, statuses or {})["app"]
    return {"from": sender_name(mail.frm), "subject": mail.subject[:120], "when": mail.at, "gist": (mail.snippet or "")[:160],
            "badges": badges_of(mail.sources or [mail.source], statuses or {}), "app": holds_the_id}


CARD_EVENTS = 20  # Today's two weeks: Up next shows a big card and up to 14 small ones


def _events(events: list[Event], statuses: dict | None = None) -> list[dict]:
    return [{**e.brief(), "badges": badges_of(e.sources or [e.source], statuses or {})} for e in events if e.change != "cancelled"][:CARD_EVENTS]


def apply(store, now: datetime, needs_you: list[dict], line: str, mails: list[Mail], events: list[Event],
          statuses: dict, first: bool) -> list[dict]:
    from odie.watch import threads
    known = {f"mail:{m.id}" for m in mails} | {f"event:{e.id}" for e in events}
    known |= threads.open_refs(store)  # a thread the watch follows can come back (a reply now overdue)
    card = store.get_setting(CARD) or {}
    closed = threads.closed_refs(store)  # the user ticked it on Today, or the watch closed it: its card goes too
    items = [i for i in card.get("needs_you", []) if not i.get("done") and i.get("ref") not in closed]
    have = {i["ref"] for i in items}
    fresh = []
    for n in needs_you or []:
        ref = str(n.get("ref") or "")
        if ref not in known or ref in have:
            continue
        it = {"ref": ref, "title": str(n.get("title") or "")[:120], "why": str(n.get("why") or "")[:WHY_MAX],
              "at": now.isoformat(timespec="seconds"), "done": False, **_mail_fields(ref, mails, statuses),
              **labelled(n)}
        if ref.startswith("event:"):
            event = next((e for e in events if f"event:{e.id}" == ref), None)
            if event is not None:
                it["badges"] = badges_of(event.sources or [event.source], statuses)
        items.append(it)
        have.add(ref)
        if n.get("push"):
            fresh.append(it)
    store.set_setting(CARD, {"checked_at": now.isoformat(timespec="seconds"), "line": str(line or "")[:200], "needs_you": items[-30:],
                             "events": _events(events, statuses), "sources": statuses, "off": "", "done": card.get("done", [])})
    flagged = list(store.get_setting(FLAGGED) or [])
    push = [i for i in fresh if i["ref"] not in flagged]
    if first or not push:
        return []
    if quiet(now):
        store.set_setting(HELD, [*(store.get_setting(HELD) or []), *push][-20:])
        return []
    push = push[:MAX_PUSH]
    store.set_setting(FLAGGED, [*(i["ref"] for i in push), *flagged][:500])
    return push


def fallback(store, now: datetime, mails: list[Mail], events: list[Event], statuses: dict, reason: str) -> None:
    upcoming = [e for e in events if e.change != "cancelled"]
    bits = [f"{len(mails)} new email{'s' if len(mails) != 1 else ''}"]
    if upcoming:
        bits.append(f"next: {upcoming[0].title} at {upcoming[0].start[11:16]}")
    card = store.get_setting(CARD) or {}
    store.set_setting(CARD, {"checked_at": now.isoformat(timespec="seconds"), "line": ", ".join(bits),
                             "needs_you": [i for i in card.get("needs_you", []) if not i.get("done")],
                             "events": _events(events, statuses), "sources": statuses, "off": f"couldn't check properly: {reason}"[:200],
                             "done": card.get("done", [])})


KEEP_DONE = 10


def keep_done(store, now: datetime, message: str, told: bool) -> None:
    """Note on the card what the watch did for a Watch for entry, told in the chat or not, so a quiet one is still
    there to look up. The card keeps the last KEEP_DONE."""
    card = store.get_setting(CARD) or {}
    done = [*card.get("done", []), {"at": now.isoformat(timespec="seconds"), "message": message[:500], "told": told}]
    store.set_setting(CARD, {**card, "done": done[-KEEP_DONE:]})


def _failures_before(prev: dict, sid: str) -> int:
    """How many checks in a row this source had failed, as the last check saved it (Fetcher.commit)."""
    saved = prev.get(sid) or {}
    return int(saved.get("fails", 0))


def failing_now(store, statuses: dict) -> list[str]:
    """The apps to say "stopped working" for: the ones whose failure in this check is their SAY_FAILING_AT-th in a
    row. Read against the last check's saved state, so before Fetcher.commit().
    Example: Gmail failed the last 2 checks and fails this one too (its 3rd in a row) -> ["Gmail"];
    its 4th failure in a row -> [] (already said); its 1st or 2nd -> [] (often a blip)."""
    prev = (store.get_setting("watch.state") or {}).get("sources") or {}
    apps = set()
    for sid, st in statuses.items():
        if st.get("ok"):
            continue
        failures_in_a_row = _failures_before(prev, sid) + 1  # counting this check's
        if failures_in_a_row == SAY_FAILING_AT:
            apps.add(st.get("app", sid))
    return sorted(apps)


def recovered_now(store, statuses: dict) -> list[str]:
    """The apps to say "works again" for: the ones that answer in this check after failing at least SAY_FAILING_AT
    checks in a row, that is after failing_now said so.
    Example: Gmail had failed 4 checks in a row and answers now -> ["Gmail"]; it had failed only 2 (nothing was said)
    and answers now -> []."""
    prev = (store.get_setting("watch.state") or {}).get("sources") or {}
    apps = set()
    for sid, st in statuses.items():
        if not st.get("ok"):
            continue
        if _failures_before(prev, sid) >= SAY_FAILING_AT:
            apps.add(st.get("app", sid))
    return sorted(apps)


def drop_item(store, ref: str) -> None:
    """Takes an item off the card (its thread closed, or the user dismissed it); nothing when it isn't there."""
    card = store.get_setting(CARD)
    if not card:
        return
    items = card.get("needs_you", [])
    kept = [i for i in items if i.get("ref") != ref]
    if len(kept) != len(items):
        card["needs_you"] = kept
        store.set_setting(CARD, card)
