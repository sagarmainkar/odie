"""The follow-up ladder (proactive design §8), on the background's 5-minute tick. Code alone: it judges nothing but
"is it time?", and every push goes through the day's shared budget (odie.watch.pushes).

His move (owner you, a card on Pulse):
  day 0      the card (shown_at)
  day 2      a line in the morning hello (hello_lines, read by the brief's watch part)
  due - 1 d  a push, once ("Due tomorrow"); never between 22:00 and 07:00 (it waits for the morning)
  day 7      Sunday's one "Still care?" card (odie.loops.cards.waits_for_sunday)
  day 14     dropped, with why, kept in the ledger (Reopen for 7 days); never pushed. A card whose due date is still
             ahead waits for it.
Their move (owner them, waiting on someone): after 3 quiet days (no new evidence, and past the day it was expected),
one nudge card ("Draft a nudge", written in chat on his tap), never twice.
Pull requests and other playbook loops follow their playbook (odie.loops.choose), not this ladder."""
from __future__ import annotations

from datetime import datetime, timedelta

from odie.loops import cards, clock, ledger

HELLO_AFTER = timedelta(days=2)
DROP_AFTER = timedelta(days=14)
QUIET_FOR = timedelta(days=3)
DUE_PUSH_WITHIN = timedelta(hours=24)
DUE_PUSH = "due-push"  # the evidence ref that says the day-before push was made (or held)


def night(now: datetime) -> bool:
    """No ladder push from 22:00 to 07:00: 23:00 -> True; 07:05 -> False."""
    return now.hour >= 22 or now.hour < 7


def has_step(store, loop_id: int, ref: str) -> bool:
    return store.one("select 1 from loop_events where loop_id=? and ref=?", (int(loop_id), ref)) is not None


def due_soon(loop: dict, now: datetime) -> bool:
    """Whether his card is due within a day and not past: due 20 hours from now -> True; in 5 days -> False; due an
    hour ago -> False; no due date -> False."""
    if not loop.get("due_at"):
        return False
    due = datetime.fromisoformat(loop["due_at"])
    return now < due <= now + DUE_PUSH_WITHIN


def stale(loop: dict, now: datetime) -> bool:
    """Whether his card has waited DROP_AFTER since it was shown with no date still ahead: shown 15 days ago, no due
    date -> True; the same with a due date in 20 days -> False; shown 3 days ago -> False."""
    shown = loop.get("shown_at") or loop["created_at"]
    if now - datetime.fromisoformat(shown) < DROP_AFTER:
        return False
    if loop.get("due_at") and datetime.fromisoformat(loop["due_at"]) > now:
        return False
    return True


def quiet_since(store, loop: dict) -> datetime:
    """When anything last happened on a loop: its newest evidence, or its due date when that is later (an order
    expected Friday isn't quiet before Friday)."""
    row = store.one("select max(at) at from loop_events where loop_id=?", (loop["id"],))
    last = datetime.fromisoformat((row and row["at"]) or loop["created_at"])
    if loop.get("due_at"):
        last = max(last, datetime.fromisoformat(loop["due_at"]))
    return last


def wants_a_nudge(store, loop: dict, now: datetime) -> bool:
    """Whether a loop waiting on someone gets its one nudge card now: their move, followed (waiting), no playbook,
    never nudged, and QUIET_FOR without news past the day it was expected. Asked Asha 4 days ago, nothing since ->
    True; asked yesterday -> False; nudged once already -> False; an order due in 2 days -> False."""
    if loop["owner"] != "them" or loop["state"] != "waiting" or loop["playbook"] or loop["nudges"]:
        return False
    return now - quiet_since(store, loop) >= QUIET_FOR


def push_due(store, loop: dict, now: datetime, push) -> str:
    from odie.watch import pushes
    ledger.add_event(store, loop["id"], now, "odie", DUE_PUSH, "Said: due tomorrow")
    if push is None:
        return "due tomorrow"
    pushes.started_by_odie(store, now, loop["personality"], loop["title"], "Due tomorrow", push,
                           ref=f"loop:{loop['id']}")
    return "due tomorrow"


def nudge(store, loop: dict, now: datetime) -> None:
    """Their move went quiet: one card, "No word in 4 days", with "Draft a nudge" (chat writes it on his tap)."""
    days = (now - quiet_since(store, loop)).days
    ledger.update(store, loop["id"], now, state="ready", nudges=1, result=f"No word in {days} days: a nudge?",
                  shown_at=now.isoformat(timespec="seconds"))
    ledger.merge_card(store, loop["id"], now, {"suggestion": "Draft a nudge"})
    ledger.add_event(store, loop["id"], now, "odie", "nudge", f"No word in {days} days")


def run(store, now: datetime, push_for=None) -> list[tuple[int, str]]:
    """One tick of the ladder for every owner the clock runs (everyday Odie, personalities switched on). push_for(pid)
    gives that owner's push, or None for no pushes. Returns [(loop id, what happened)]."""
    done = []
    for pid in clock.owners(store):
        push = None
        if push_for is not None:
            push = push_for(pid)
        for loop in ledger.open_loops(store, pid):
            if loop["playbook"]:
                continue
            if loop["owner"] == "you" and loop["state"] == "ready":
                if stale(loop, now):
                    ledger.close(store, loop["id"], now, "odie", "No move in 14 days: dropped (kept for 30 days)",
                                 state="dropped")
                    done.append((loop["id"], "dropped"))
                    continue
                skip = night(now) or cards.hidden(loop, now) or has_step(store, loop["id"], DUE_PUSH)
                if not skip and due_soon(loop, now):
                    done.append((loop["id"], push_due(store, loop, now, push)))
                continue
            if wants_a_nudge(store, loop, now):
                nudge(store, loop, now)
                done.append((loop["id"], "nudge"))
    return done


def hello_lines(store, pid: str, now: datetime) -> list[str]:
    """The morning hello's lines from the ladder: his cards waiting since day 2, oldest first. "Reply to Asha (waiting
    on you 3 days)"; a card shown this morning isn't one yet."""
    out = []
    ready = [lp for lp in ledger.open_loops(store, pid) if lp["state"] == "ready" and lp["owner"] == "you"]
    for loop in ready:
        shown = datetime.fromisoformat(loop.get("shown_at") or loop["created_at"])
        waited = now - shown
        if waited < HELLO_AFTER:
            continue
        out.append(f"{loop['title']} (waiting on you {waited.days} days)")
    return out
