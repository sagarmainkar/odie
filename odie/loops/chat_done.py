"""His Done, said in chat (19 Nov 2026, the phase-3 security pass): "close the venue card, I replied from my phone".
One decision for every way a model may do his Done — watch_close on a card, task_update ticking a loop's reminder —
because a model can be steered by what it read, and Done silences a thing for weeks (odie.loops.ledger.remembered).
The tap routes in the app (/api/loops/{id}/done, /api/tasks/{id}/done) need none of this: a tap is his."""
from __future__ import annotations

from datetime import datetime

from odie.loops import ledger

OK, TAP, REFUSE = "ok", "tap", "refuse"


def decide(store, loop: dict, tool_context) -> tuple[str, str]:
    """Whether a model may close this loop as his Done now: (OK | TAP | REFUSE, why in words).
      a pull request's loop (a playbook)                -> REFUSE: GitHub's facts close it, or his tap on its card
      a turn from the terminal, or a background run      -> REFUSE: only he may, in the app
      a chat that has read mail, web pages or a job      -> TAP: his tap on the approval card
      a clean chat in the app (his own words)            -> OK"""
    from odie.agent import turns
    from odie.agent.context import session_id_of
    from odie.workers import taint
    if loop["playbook"]:
        return REFUSE, "Not in chat: a pull request closes from GitHub's facts, or tap Done on its card."
    session_id = session_id_of(tool_context)
    if not session_id or turns.kind_of(session_id) in (turns.TERMINAL, turns.BACKGROUND):
        return REFUSE, "Only you can close this, with Done on its card in the app."
    if taint.of_chat(store, session_id):
        return TAP, "This chat read outside text: closing it needs your tap."
    return OK, ""


def close(store, loop: dict, now: datetime, why: str) -> None:
    """Closes a loop as his Done said in chat: remembered like a Done, shown in Done today with Reopen, and its
    evidence says how ("Done by you in chat: replied from my phone")."""
    ledger.close(store, loop["id"], now, ledger.CLOSED_IN_CHAT, why)
    ledger.add_event(store, loop["id"], now, ledger.CLOSED_IN_CHAT, "", f"Done by you in chat: {why}")
    ledger.update(store, loop["id"], now, tapped="done in chat")
