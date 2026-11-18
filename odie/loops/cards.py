"""Loops on Pulse (proactive design §8): a ready loop is one card, with the same three buttons as every card
(odie.watch.needs): its one move, Done and Later. The move and its link are written by code from the loop's checked
ref (phase 1: open the pull request or the issue). Loops Odie is still working on are listed under "Odie is on it";
the ones it closed today, with why, under "Done today", each with Reopen."""
from __future__ import annotations

from datetime import datetime, time

from odie.loops import github, ledger

ON_IT_STATES = ("new", "working", "waiting")


def hidden(loop: dict, now: datetime) -> bool:
    """Whether a loop's card is put off (Later): hidden until 09:00 tomorrow, asked at 12:00 today -> True; at 09:00
    tomorrow -> False; never put off -> False."""
    until = loop.get("hidden_until")
    if not until:
        return False
    return datetime.fromisoformat(until) > now


def move_of(loop: dict) -> dict:
    """The card's one move, built by code: a pull request's or issue's page from its checked ref ("Open PR #49" ->
    https://github.com/example/app/pull/49); with no such ref, "Tell me more" in chat."""
    ref = None
    for text in loop["refs"]:
        ref = github.parse(text)
        if ref is not None:
            break
    if ref is None:
        return {"label": "Tell me more", "action": "chat", "value": f"Tell me about loop #{loop['id']}: {loop['title']}"}
    label = f"Open PR #{ref.number}"
    if "issue" in (loop["kind"] or "").lower():
        label = f"Open issue #{ref.number}"
    return {"label": label, "action": "open", "value": github.link(ref, loop["kind"])}


def card(loop: dict) -> dict:
    """A ready loop as a Pulse card, in the shape odie.watch.needs gives every card."""
    ref = f"loop:{loop['id']}"
    ask = f"Tell me about loop #{loop['id']}: {loop['title']}"
    return {"ref": ref, "title": loop["title"], "why": loop["result"], "brief": loop["brief"], "icon": "terminal",
            "badge": "", "ask": ask, "main": move_of(loop), "other": {"label": "Done", "action": "loop_done", "value": loop["id"]},
            "later": {"label": "Later", "action": "later", "value": ref}, "pile": "alerts",
            "since": loop.get("shown_at") or loop["updated_at"], "decide": False}


def cards(store, pid: str, now: datetime) -> list[dict]:
    """This owner's ready loops as cards, not the ones put off with Later; newest first."""
    ready = [lp for lp in ledger.open_loops(store, pid) if lp["state"] == "ready" and not hidden(lp, now)]
    ready.sort(key=lambda lp: lp["id"], reverse=True)
    return [card(lp) for lp in ready]


def later(store, loop_id: int, until: str, pid: str, now: datetime) -> bool:
    """Puts a loop's card off until then; False when it isn't this owner's open loop."""
    loop = ledger.get(store, loop_id)
    if loop is None or loop["personality"] != pid or loop["state"] not in ledger.OPEN:
        return False
    ledger.update(store, loop_id, now, hidden_until=until, tapped="later")
    return True


def on_it(store, pid: str) -> list[dict]:
    """What Odie is still working on for this owner, one line each: "app #51 · waiting · CI still running"."""
    out = []
    for lp in ledger.open_loops(store, pid):
        if lp["state"] not in ON_IT_STATES:
            continue
        out.append({"id": lp["id"], "title": lp["title"], "state": lp["state"], "next": lp["next_step"]})
    return out


def start_of_day(now: datetime) -> datetime:
    return datetime.combine(now.date(), time(0, 0), now.tzinfo)


def done_today(store, pid: str, now: datetime) -> list[dict]:
    """The loops Odie closed today for this owner, with why, newest first (each gets Reopen on Pulse)."""
    closed = ledger.closed_since(store, pid, start_of_day(now))
    return [{"id": lp["id"], "title": lp["title"], "why": lp["closed_why"] or "", "closed": lp["closed_at"]}
            for lp in closed]
