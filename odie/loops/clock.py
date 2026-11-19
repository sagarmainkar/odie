"""Stage 3, the clock (proactive design §6), on the background's 5-minute tick: which loops are due. It judges
nothing; it asks "is it time?". Due: open, with a playbook, its next check passed or news arrived, not put off with
Later, and its owner is everyday Odie or a personality whose Proactive intelligence is on. Ordered by due date (none
last), then the model's priority, then age. Each due loop goes to stage 4 while the day's budget lasts; a promise Odie
made in chat goes to its own reading turn (odie.loops.promise_run)."""
from __future__ import annotations

from datetime import datetime

from odie.loops import budget, choose, ledger, promise_run

PER_TICK = 5  # loops looked at in one wake-up; the rest wait for the next
RANK = {"high": 0, "normal": 1, "low": 2}


def is_due(loop: dict, now: datetime) -> bool:
    """Whether a loop's time has come: news arrived, or its next check has passed; never while put off with Later.
    News -> True; next check 09:00, at 10:00 -> True; next check 12:00, at 10:00 -> False; hidden until tomorrow
    09:00 -> False; no playbook -> False (nothing to run)."""
    if not loop["playbook"]:
        return False
    hidden = loop.get("hidden_until")
    if hidden and datetime.fromisoformat(hidden) > now:
        return False
    if loop["has_news"]:
        return True
    next_check = loop.get("next_check_at")
    if not next_check:
        return False
    return datetime.fromisoformat(next_check) <= now


def owners(store) -> list[str]:
    """Whose loops the clock runs: everyday Odie's, and each personality's with its switch on."""
    from odie.watch import owner
    return ["", *owner.proactive_owners(store)]


def order_key(loop: dict) -> tuple:
    due = loop.get("due_at") or "9999"
    return (due, RANK.get(loop["priority"], 1), loop["id"])


def due(store, now: datetime) -> list[dict]:
    out = []
    for pid in owners(store):
        out += [loop for loop in ledger.open_loops(store, pid) if is_due(loop, now)]
    out.sort(key=order_key)
    return out


async def run(store, now: datetime, think_for, push_for=None, most: int = PER_TICK, act_for=None,
              tell=None) -> list[tuple[int, str]]:
    """Runs stage 4 for the due loops, at most `most`, while today's budget of calls lasts. think_for(pid) gives the
    model call for that owner's brain; push_for(pid) its push (opening that owner's Pulse), or None for no pushes.
    A promise Odie made in chat (playbook "promise") goes to odie.loops.promise_run instead: act_for(pid) gives its
    reading turn on that owner's brain and tell(session_id, text) posts the follow-up; with no act_for it waits.
    Returns [(loop id, what happened)]."""
    ran = []
    for loop in due(store, now)[:most]:
        if budget.left(store, now) <= 0:
            break
        push = None
        if push_for is not None:
            push = push_for(loop["personality"])
        if loop["playbook"] == promise_run.PLAYBOOK:
            if act_for is None:
                continue
            got = await promise_run.run(store, loop, now, act_for(loop["personality"]), tell, push)
        else:
            got = await choose.choose(store, loop, now, think_for(loop["personality"]), push)
        ran.append((loop["id"], got))
    return ran
