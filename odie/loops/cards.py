"""Loops on Pulse (proactive design §8): cards are a view of the ledger. A ready loop is one card, never two, with the
same three buttons as every card (odie.watch.needs): its one move, Done and Later; with "Why?" (its evidence, each
line with its time) and a small menu (Split, when a merge was wrong). The move is written by code: for a pull request
or an issue, its page from the loop's checked ref; for a pull request Odie tested (odie.loops.pr_test), [Merge] when
the tests passed and CI isn't failing, [Show failures] when they failed; for anything else, the draft Odie wrote
("Show the draft"), the one move the check suggested, or "Tell me more" in chat. Loops Odie is still working on or
waiting on are listed under "Odie is on it"; the ones it closed today, with why, under "Done today", each with Reopen.
On Sundays, cards waiting over a week fold into one "Still care?" card (the follow-up ladder, odie.loops.ladder)."""
from __future__ import annotations

from datetime import datetime, time, timedelta

from odie.loops import github, ledger, pr_test
from odie.watch import cards as card_text

ON_IT_STATES = ("new", "working", "waiting")
BATCH = "batch:sunday"
STILL_CARE_DAYS = 7  # a card waiting this long goes into Sunday's "Still care?" batch
SUNDAY = 6  # datetime.weekday()


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


def icon_of(loop: dict) -> str:
    """A loop card's icon: a pull request's or issue's "terminal"; else its pile's (bills -> "rupee", personal ->
    "heart"); from an event "cal"; from a mail "mail"; anything else "bell"."""
    if loop["playbook"]:
        return "terminal"
    pile = loop["card"].get("pile", "")
    if pile in card_text.PILE_ICON:
        return card_text.PILE_ICON[pile]
    if any(r.startswith("event:") for r in loop["refs"]):
        return "cal"
    if any(r.startswith("mail:") for r in loop["refs"]):
        return "mail"
    return "bell"


def pile_of(loop: dict) -> str:
    """The Mac app's bucket for a loop card: its pile when the check gave one, "events" for one from the calendar,
    else "alerts"."""
    from odie.watch import report
    pile = loop["card"].get("pile", "")
    if pile in report.PILES:
        return pile
    if any(r.startswith("event:") for r in loop["refs"]) and not loop["playbook"]:
        return "events"
    return "alerts"


def badge_of(loop: dict, now: datetime) -> str:
    """The pill at the end of a loop's card: its amount; else "Overdue" past its due day; else its due day ("21 Nov",
    "21 Nov, 15:00"); else "". A pull request's card has none."""
    if loop["playbook"]:
        return ""
    if loop["card"].get("amount"):
        return card_text.money(loop["card"]["amount"])
    due = loop.get("due_at")
    if not due:
        return ""
    if due[:10] < now.strftime("%Y-%m-%d"):
        return "Overdue"
    shown = loop["card"].get("due")
    if shown and due.startswith(shown[:10]) and "T" not in shown:
        return card_text.day(shown)  # a date the check gave without a time: "21 Nov"
    return card_text.day(due[:16])


def chat_move(loop: dict) -> dict:
    """The one move of a loop that isn't GitHub's, written by code (the check wrote only its words): its draft ("Show
    the draft for loop #3"), the move the check suggested ("Loop #3: Remind me Thursday"), else "Tell me more"."""
    lid = loop["id"]
    label = str(loop["card"].get("suggestion") or "").strip()
    if loop["card"].get("draft"):
        return {"label": label or "Show the draft", "action": "chat", "value": f"Show the draft for loop #{lid}"}
    if label:
        return {"label": label, "action": "chat", "value": f"Loop #{lid}: {label}"}
    return {"label": "Tell me more", "action": "chat", "value": ask_of(loop)}


def ask_of(loop: dict) -> str:
    return f"Tell me about loop #{loop['id']}: {loop['title']}"


def why_lines(evidence: list[dict]) -> list[dict]:
    """A card's "Why?": its last EVIDENCE_SHOWN lines of evidence, each with its time, where from and its id (Split
    names lines by id). The Later taps are left out: they say nothing about the thing."""
    shown = [e for e in evidence if e["ref"] != "later"][-EVIDENCE_SHOWN:]
    return [{"id": e["id"], "at": e["at"], "source": e["source"], "fact": e["fact"]} for e in shown]


def card(loop: dict, tested: dict | None = None, evidence: list[dict] | None = None,
         now: datetime | None = None) -> dict:
    """A ready loop as a Pulse card, in the shape odie.watch.needs gives every card (the Mac app reads the same
    fields); with its test (when Odie tested it), its evidence (Why?) and its menu (Split)."""
    ref = f"loop:{loop['id']}"
    main = move_of(loop)
    if not loop["playbook"]:
        main = chat_move(loop)
    title = loop["title"]
    move, output = tested_move(loop, tested)
    if move is not None:
        main = move
        title = tested.get("title") or title
    when = now or datetime.fromisoformat(loop["updated_at"])
    decide = main["label"] == "Tell me more"  # no move of Odie's: the choice is his
    out = {"ref": ref, "title": title, "why": loop["result"], "brief": loop["brief"], "icon": icon_of(loop),
           "badge": badge_of(loop, when), "ask": ask_of(loop), "main": main,
           "other": {"label": "Done", "action": "loop_done", "value": loop["id"]},
           "later": {"label": "Later", "action": "later", "value": ref}, "pile": pile_of(loop),
           "since": loop.get("shown_at") or loop["updated_at"], "decide": decide,
           "evidence": why_lines(evidence or []), "more": [{"label": "Split", "action": "split", "value": loop["id"]}]}
    if output:
        out["output"] = output
    return out


def waits_for_sunday(loop: dict, now: datetime) -> bool:
    """Whether a card goes into Sunday's "Still care?" batch instead of showing on its own: it is Sunday, it is his
    (no playbook), and it has waited STILL_CARE_DAYS since it was first shown. Shown 8 days ago, asked on a Sunday ->
    True; the same on a Monday -> False; shown yesterday -> False; a pull request -> False."""
    if now.weekday() != SUNDAY or loop["playbook"] or loop["owner"] != "you":
        return False
    shown = loop.get("shown_at") or loop["created_at"]
    return now - datetime.fromisoformat(shown) >= timedelta(days=STILL_CARE_DAYS)


def batch_card(loops: list[dict]) -> dict:
    """Sunday's one "Still care?" card for the cards waiting over a week (design §8, the follow-up ladder): its Why?
    lists them; "Drop them" lets them all go (his Done, remembered); Later puts them off to next Sunday."""
    names = [lp["title"] for lp in loops]
    why = ", ".join(names[:3])
    if len(names) > 3:
        why += f" and {len(names) - 3} more"
    lines = [{"id": lp["id"], "at": lp.get("shown_at") or lp["created_at"], "source": "odie", "fact": lp["title"]}
             for lp in loops]
    ask = "Go through the loops waiting over a week with me: " + "; ".join(f"#{lp['id']} {lp['title']}" for lp in loops)
    return {"ref": BATCH, "title": f"Still care? {len(loops)} waiting over a week", "why": why[:200], "brief": "",
            "icon": "bell", "badge": "", "ask": ask[:500], "main": {"label": "Go through them", "action": "chat",
                                                                     "value": ask[:500]},
            "other": {"label": "Drop them", "action": "dismiss", "value": BATCH},
            "later": {"label": "Later", "action": "later", "value": BATCH}, "pile": "alerts",
            "since": lines[0]["at"], "decide": False, "evidence": lines}


def ready_loops(store, pid: str, now: datetime) -> list[dict]:
    """This owner's ready loops, not put off with Later, newest first."""
    ready = [lp for lp in ledger.open_loops(store, pid) if lp["state"] == "ready" and not hidden(lp, now)]
    ready.sort(key=lambda lp: lp["id"], reverse=True)
    return ready


def cards(store, pid: str, now: datetime) -> list[dict]:
    """This owner's ready loops as cards, newest first (on Sundays the week-old ones as one "Still care?" card); then
    the "Use this" cards asking for a repo's test command (odie.loops.recipes)."""
    from odie.loops import recipes
    ready = ready_loops(store, pid, now)
    batch = [lp for lp in ready if waits_for_sunday(lp, now)]
    out = [card(lp, pr_test.result_for(store, lp["id"]), ledger.events(store, lp["id"]), now)
           for lp in ready if lp not in batch]
    if batch:
        out.append(batch_card(batch))
    return out + recipes.cards(store, pid)


def next_sunday(now: datetime) -> str:
    """09:00 on the next Sunday (never today): Thursday 19 Nov -> "2026-11-22T09:00:00+05:30"; Sunday 22 Nov ->
    29 Nov."""
    days = (SUNDAY - now.weekday()) % 7
    if days == 0:
        days = 7
    day = now.date() + timedelta(days=days)
    return datetime.combine(day, time(9, 0), now.tzinfo).isoformat(timespec="seconds")


LATERS_TO_SUNDAY = 3  # the third Later on one loop sends it to Sunday (design §8)


def later(store, loop_id: int, until: str, pid: str, now: datetime) -> str | None:
    """Puts a loop's card off and says until when; None when it isn't this owner's open loop. The third Later on one
    loop sends it to Sunday's batch instead of tomorrow: put off twice already, asked Thursday -> Sunday 09:00."""
    loop = ledger.get(store, loop_id)
    if loop is None or loop["personality"] != pid or loop["state"] not in ledger.OPEN:
        return None
    if ledger.laters(store, loop_id) + 1 >= LATERS_TO_SUNDAY:
        until = next_sunday(now)
    ledger.note_later(store, loop_id, now, until)
    return until


def later_batch(store, pid: str, now: datetime) -> str | None:
    """Later on Sunday's "Still care?" card: each loop in it is put off to next Sunday. None when there is no batch."""
    batch = [lp for lp in ready_loops(store, pid, now) if waits_for_sunday(lp, now)]
    if not batch:
        return None
    until = next_sunday(now)
    for lp in batch:
        ledger.note_later(store, lp["id"], now, until)
    return until


def drop_batch(store, pid: str, now: datetime) -> int:
    """"Drop them" on Sunday's "Still care?" card: each loop in it closes as his (dropped, remembered like a Done).
    Returns how many."""
    batch = [lp for lp in ready_loops(store, pid, now) if waits_for_sunday(lp, now)]
    for lp in batch:
        ledger.close(store, lp["id"], now, ledger.CLOSED_BY_USER, "Not any more (Sunday's still care?)", state="dropped")
        ledger.update(store, lp["id"], now, tapped="drop")
    return len(batch)


def on_it(store, pid: str) -> list[dict]:
    """What Odie is still working on for this owner, one line each: "app #51 · waiting · CI still running"."""
    out = []
    for lp in ledger.open_loops(store, pid):
        if lp["state"] not in ON_IT_STATES:
            continue
        next_words = lp["next_step"] or lp["result"]  # a loop from the watch says what it waits for in its why
        out.append({"id": lp["id"], "title": lp["title"], "state": lp["state"], "next": next_words})
    return out


def start_of_day(now: datetime) -> datetime:
    return datetime.combine(now.date(), time(0, 0), now.tzinfo)


def done_today(store, pid: str, now: datetime) -> list[dict]:
    """The loops Odie closed today for this owner, with why, newest first (each gets Reopen on Pulse)."""
    closed = ledger.closed_since(store, pid, start_of_day(now))
    return [{"id": lp["id"], "title": lp["title"], "why": lp["closed_why"] or "", "closed": lp["closed_at"]}
            for lp in closed]
