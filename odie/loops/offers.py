"""His own commitments said in chat, offered for tracking (proactive design §17, phase 4): "I need to call the bank
Friday" -> a "Track this?" card on his Pulse, [Track] [No]. Nothing is tracked without his tap: an offer is not a loop
(it lives in the settings table, one list per owner), and Track, his tap in the app, makes the loop.

Track makes a loop of his own ("you", a card) with its due time and a reminder at that time, as stage 2 makes for a
new loop (odie.loops.consolidate.make_reminder). No forgets the offer. An offer nobody answers fades after KEEP_DAYS,
or once its time has passed."""
from __future__ import annotations

import threading
from datetime import datetime, timedelta

from odie.loops import ledger

KEY = "loops.offers"  # per owner (odie.watch.owner.key): {"next": 4, "items": [{id, what, due, said, chat, at, state}]}
KEEP_DAYS = 7
KEPT_MOST = 30  # answered and faded offers kept, newest last, so the list never grows
REF = "offer:"
OPEN, TRACKED, DECLINED = "open", "tracked", "declined"
WRITING = threading.Lock()  # every read-change-write of the offers list holds it, so two taps never lose one


def _key(pid: str) -> str:
    from odie.watch.owner import key
    return key(KEY, pid)


def _saved(store, pid: str) -> dict:
    saved = store.get_setting(_key(pid)) or {}
    return {"next": int(saved.get("next") or 1), "items": list(saved.get("items") or [])}


def add(store, pid: str, now: datetime, what: str, due: str | None, said: str, chat: str) -> int:
    """A new offer on this owner's Pulse. Returns its number."""
    with WRITING:
        saved = _saved(store, pid)
        offer_id = saved["next"]
        saved["items"].append({"id": offer_id, "what": what, "due": due, "said": said, "chat": chat,
                               "at": now.isoformat(timespec="seconds"), "state": OPEN})
        saved["items"] = saved["items"][-KEPT_MOST:]
        saved["next"] = offer_id + 1
        store.set_setting(_key(pid), saved)
    return offer_id


def faded(offer: dict, now: datetime) -> bool:
    """Whether an unanswered offer has faded: made more than KEEP_DAYS ago, or its time has passed. Made yesterday
    for Friday, asked on Thursday -> False; made 8 days ago -> True; for 18:00 today, asked at 19:00 -> True; no
    time, made today -> False."""
    made = datetime.fromisoformat(offer["at"])
    if now - made > timedelta(days=KEEP_DAYS):
        return True
    due = offer.get("due")
    return bool(due) and datetime.fromisoformat(due) < now


def open_offers(store, pid: str, now: datetime) -> list[dict]:
    """This owner's offers still waiting for his answer, oldest first."""
    return [o for o in _saved(store, pid)["items"] if o["state"] == OPEN and not faded(o, now)]


def get(store, pid: str, offer_id: int) -> dict | None:
    """One of this owner's offers by its number, in any state; None when it isn't this owner's."""
    for offer in _saved(store, pid)["items"]:
        if offer["id"] == int(offer_id):
            return offer
    return None


def _mark(store, pid: str, offer_id: int, state: str) -> None:
    saved = _saved(store, pid)
    for offer in saved["items"]:
        if offer["id"] == int(offer_id):
            offer["state"] = state
    store.set_setting(_key(pid), saved)


def card(offer: dict) -> dict:
    """An offer as a Pulse card, in the shape every card has (odie.watch.needs): "Track this? Call the bank", what he
    said as its why, its day as the badge, [Track] and [No] (no Later: it is a yes or a no). No is "dismiss", which
    every app already carries out (POST /api/watch/done with the card's ref)."""
    from odie.watch import cards as card_text
    ref = f"{REF}{offer['id']}"
    badge = ""
    if offer.get("due"):
        badge = card_text.day(offer["due"][:16])
    return {"ref": ref, "title": f"Track this? {offer['what']}", "why": f"You said: “{offer['said']}”", "brief": "",
            "icon": "bell", "badge": badge, "ask": f"About “{offer['what']}”",
            "main": {"label": "Track", "action": "track", "value": offer["id"]},
            "other": {"label": "No", "action": "dismiss", "value": ref},
            "pile": "alerts", "since": offer["at"], "decide": True, "evidence": []}


def cards(store, pid: str, now: datetime) -> list[dict]:
    """This owner's waiting offers as cards, newest first."""
    return [card(o) for o in reversed(open_offers(store, pid, now))]


def track(store, pid: str, offer_id: int, now: datetime) -> int | None:
    """His Track: a loop of his own, a card at once ("you", ready), due when he said, with a reminder that rings then
    (when he gave a time). Returns the loop's id; None when the offer isn't this owner's or isn't waiting any more."""
    from odie.loops import consolidate
    with WRITING:  # one Track per offer, even from two taps at once
        offer = get(store, pid, offer_id)
        if offer is None or offer["state"] != OPEN or faded(offer, now):
            return None
        _mark(store, pid, offer_id, TRACKED)
    lid = ledger.open_loop(store, pid, now, offer["what"], "commitment", owner="you", state="ready",
                           due_at=offer.get("due"), source="you", ref=f"chat:{offer['chat']}",
                           fact=f"You said in chat: “{offer['said']}” (tracked on your tap)",
                           card={"chat": offer["chat"]})
    ledger.update(store, lid, now, has_news=0, tapped="track")
    if offer.get("due"):
        consolidate.make_reminder(store, pid, now, lid, offer["what"], offer["due"])
    return lid


def decline(store, pid: str, offer_id: int) -> bool:
    """His No: the offer goes and nothing is tracked. False when it isn't this owner's waiting offer."""
    with WRITING:
        offer = get(store, pid, offer_id)
        if offer is None or offer["state"] != OPEN:
            return False
        _mark(store, pid, offer_id, DECLINED)
    return True


def number_of(ref: str) -> int | None:
    """The offer a card's ref names: "offer:3" -> 3; "offer:x", "loop:3" -> None."""
    if not ref.startswith(REF):
        return None
    rest = ref[len(REF):]
    if not rest.isdigit():
        return None
    return int(rest)
