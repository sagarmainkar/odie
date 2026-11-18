"""Loops on Pulse (proactive design §8): a ready loop is one card, with the same three buttons as every card
(odie.watch.needs): its one move, Done and Later. The move and its link are written by code from the loop's checked
ref: open the pull request or the issue; for a pull request Odie tested (odie.loops.pr_test), [Merge] when the tests
passed and CI isn't failing, [Show failures] when they failed. Every loop card carries its last evidence for "Why?". Loops Odie is still working on are listed under "Odie is on it";
the ones it closed today, with why, under "Done today", each with Reopen."""
from __future__ import annotations

from datetime import datetime, time

from odie.loops import github, ledger, pr_test

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


EVIDENCE_SHOWN = 8


def may_merge(tested: dict | None) -> bool:
    """Whether a tested card offers [Merge]: its card is up for this test (the head it tested is still the head), the
    tests passed, and GitHub's CI is green or absent.
      passed, CI green -> True;  passed, no CI -> True;  passed, CI failing -> False;  passed, CI still running ->
      False;  failed -> False;  new commits since (no longer carded) -> False;  never tested -> False"""
    if not tested or not tested.get("carded"):
        return False
    return bool(tested.get("ok")) and tested.get("checks") in ("green", "none")


def tested_move(loop: dict, tested: dict | None) -> tuple[dict | None, str]:
    """A tested card's move and the output it shows, or (None, "") for an untested one: Merge (pinned later, by
    odie.loops.merge, to the tested commit) when may_merge; Show failures with the output's tail when the tests failed."""
    if not tested or not tested.get("carded"):
        return None, ""
    if may_merge(tested):
        return {"label": "Merge", "action": "merge", "value": loop["id"]}, ""
    if not tested.get("ok") and tested.get("tail"):
        return {"label": "Show failures", "action": "show_output", "value": loop["id"]}, tested["tail"]
    return None, ""


def card(loop: dict, tested: dict | None = None, evidence: list[dict] | None = None) -> dict:
    """A ready loop as a Pulse card, in the shape odie.watch.needs gives every card; with its test (when Odie tested
    it) and its last evidence (Why?)."""
    ref = f"loop:{loop['id']}"
    ask = f"Tell me about loop #{loop['id']}: {loop['title']}"
    main = move_of(loop)
    title = loop["title"]
    move, output = tested_move(loop, tested)
    if move is not None:
        main = move
        title = tested.get("title") or title
    why_lines = [{"at": e["at"], "source": e["source"], "fact": e["fact"]} for e in (evidence or [])[-EVIDENCE_SHOWN:]]
    out = {"ref": ref, "title": title, "why": loop["result"], "brief": loop["brief"], "icon": "terminal",
           "badge": "", "ask": ask, "main": main, "other": {"label": "Done", "action": "loop_done", "value": loop["id"]},
           "later": {"label": "Later", "action": "later", "value": ref}, "pile": "alerts",
           "since": loop.get("shown_at") or loop["updated_at"], "decide": False, "evidence": why_lines}
    if output:
        out["output"] = output
    return out


def cards(store, pid: str, now: datetime) -> list[dict]:
    """This owner's ready loops as cards, not the ones put off with Later; newest first; then the "Use this" cards
    asking for a repo's test command (odie.loops.recipes)."""
    from odie.loops import recipes
    ready = [lp for lp in ledger.open_loops(store, pid) if lp["state"] == "ready" and not hidden(lp, now)]
    ready.sort(key=lambda lp: lp["id"], reverse=True)
    out = [card(lp, pr_test.result_for(store, lp["id"]), ledger.events(store, lp["id"])) for lp in ready]
    return out + recipes.cards(store, pid)


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
