"""His Done, said in chat (19 Nov 2026, the phase-3 security passes): "close the venue card, I replied from my phone".
One decision for every way a model may change a loop as him — watch_close on a card, task_update ticking, dropping or
moving a loop's reminder — because a model can be steered by what it read, and Done silences a thing for weeks
(odie.loops.ledger.remembered). Always his tap; never a pull request, the terminal or a background run.
The tap routes in the app (/api/loops/{id}/done, /api/tasks/{id}/done) need none of this: a tap is his."""
from __future__ import annotations

from datetime import datetime

from odie.loops import ledger

TAP, REFUSE = "tap", "refuse"


def decide(store, loop: dict, tool_context) -> tuple[str, str]:
    """Whether a model may change this loop (close it, tick or move its reminder) as his: (TAP | REFUSE, why in words).
    Any such change from chat needs his tap, every time: a chat's context always carries titles that came from mail.
      a pull request's loop (a playbook)            -> REFUSE: GitHub's facts close it, or his tap on its card
      a turn from the terminal, or a background run -> REFUSE: only he may, in the app
      any chat in the app                           -> TAP: the approval card, his tap"""
    from odie.agent import turns
    from odie.agent.context import session_id_of
    if loop["playbook"]:
        return REFUSE, "Not in chat: a pull request closes from GitHub's facts, or tap Done on its card."
    session_id = session_id_of(tool_context)
    if not session_id or turns.kind_of(session_id) in (turns.TERMINAL, turns.BACKGROUND):
        return REFUSE, "Only you can close this, with Done on its card in the app."
    return TAP, ""


def close(store, loop: dict, now: datetime, why: str) -> None:
    """Closes a loop as his Done said in chat: remembered like a Done, shown in Done today with Reopen, and its
    evidence says how ("Done by you in chat: replied from my phone")."""
    ledger.close(store, loop["id"], now, ledger.CLOSED_IN_CHAT, why)
    ledger.add_event(store, loop["id"], now, ledger.CLOSED_IN_CHAT, "", f"Done by you in chat: {why}")
    ledger.update(store, loop["id"], now, tapped="done in chat")
