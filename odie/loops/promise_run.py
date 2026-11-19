"""A promise Odie made in chat, carried out when it is due (proactive design §17, phase 4). The chat read
(odie.loops.chat_read) made it a loop of Odie's with the playbook "promise"; the clock (odie.loops.clock) hands it here
when its time comes.

ONE background turn on the owner's brain does it, reading only:
  - an allow-list of tools that only read (keeps): the web, his notes and memory, the calendar and mail reads, a job's
    status, a card on Pulse, a connected app's reads; anything else is never even declared to the model;
  - the trackers' guard as the second lock (nothing that needs his tap runs in the background), and no web once the
    turn has read something of his own (his mail, notes, memory, calendar), so nothing of his can leave in an address.
Done -> the follow-up is posted in the chat it was promised in (fenced for the model, shown as written), the loop
closes ("Did it: …") and one push goes out within the day's shared three (never at night).
Not done (it needs him, a step it may not take, a failed turn, today's PROMISE_DAILY used) -> the loop becomes his
card: "I said I'd do this … but couldn't on my own" with [Check now] (to chat, his tap), [Done] and [Later]. A promise
never makes Odie take a step that needs his tap."""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime

from odie.loops import budget, ledger, playbooks

log = logging.getLogger("odie.loops")
PLAYBOOK = "promise"
PROMISE_DAILY = 8
KEY = "loops.promise_runs"  # {"day": "2026-11-19", "used": 2}
# Odie's own tools that only read. Anything else of Odie's (task_add, update_memory, start_job, run_shell, make_*,
# watch_close, track …) is never handed to a promise's turn.
READS = frozenset({"now", "web_search", "web_fetch", "recall", "search_everything", "related_notes", "read_note",
                   "fetch_memory", "task_list", "list_trackers", "jobs_status", "watch_item", "market_history",
                   "quarterly_financials", "mac_calendar_events", "mac_mail_new", "mac_mail_read", "mac_reminders",
                   "load_skill", "read_skill", "skill_guide", "odie_features"})
WEB = frozenset({"web_search", "web_fetch"})
REFUSED = "Not in a promise's check: it may only read. Say what is missing in your JSON instead."
NO_WEB = ("Not now: this check has read something of the user's own, so it may not use the web any more (nothing of "
          "his leaves in an address). Answer with what you have.")


def keeps(name: str) -> bool:
    """Whether a tool is handed to a promise's turn at all: one of Odie's reads (READS), or a connected app's tool
    whose name says it only reads (gmail_find_email; odie.plugins.mcp.is_read_name).
      "web_search", "recall", "jobs_status", "gmail_find_email" -> True;
      "task_add", "update_memory", "start_job", "run_shell", "watch_close", "gmail_send_email", "make_research" -> False"""
    from odie.plugins.mcp import is_read_name
    if name in READS:
        return True
    if name.startswith("mac_"):
        return False  # this Mac's own tools: only the reads listed above
    return is_read_name(name)


def guard_for():
    """The before-tool guard for one promise's turn (it keeps what the turn has read): see guard."""
    from odie.agent.confidential import label_for
    from odie.trackers import guard as trackers_guard
    read_his_own: set[str] = set()

    def guard(tool, args, tool_context) -> dict | None:
        """Whether a tool call in a promise's turn runs (None) or is refused (an error the model reads):
          a tool keeps() doesn't keep (task_add, gmail_send_email, start_job) -> refused
          a tool that would need his tap (the trackers' guard: an app tool that asks, run_shell) -> refused
          web_search or web_fetch after the turn read his mail, notes, memory or calendar -> refused
          recall, then jobs_status -> both run;  web_search first, then recall -> both run"""
        name = tool.name
        if not keeps(name):
            return {"error": REFUSED}
        refused = trackers_guard(tool, args, tool_context)
        if refused is not None:
            return refused
        if name in WEB and read_his_own:
            return {"error": NO_WEB}
        label = label_for(name)
        if label:
            read_his_own.add(label)
        return None
    return guard


def used_today(store, now: datetime) -> int:
    saved = store.get_setting(KEY) or {}
    if saved.get("day") != now.date().isoformat():
        return 0
    return int(saved.get("used") or 0)


def spend(store, now: datetime) -> bool:
    """Takes one promise run from today's: True when one is left (counted, and spent from the proactive budget);
    False when PROMISE_DAILY ran today or the proactive budget is gone. 7 ran -> True; 8 ran -> False."""
    used = used_today(store, now)
    if used >= PROMISE_DAILY:
        return False
    if not budget.spend(store, now):
        return False
    store.set_setting(KEY, {"day": now.date().isoformat(), "used": used + 1})
    return True


def prompt_for(loop: dict) -> str:
    """What the turn reads: the promise, the words Odie said and what he had asked then."""
    card = loop["card"]
    asked = card.get("asked") or "(a button sent that turn)"
    return (f"The promise: {loop['title']}\nDue: {loop.get('due_at') or 'now'}\n"
            f"What you said in the chat: “{card.get('said') or loop['title']}”\nWhat the user had asked then: {asked}\n\n"
            "Do it now if reading is enough, then end with the JSON.")


def parse(text: str) -> dict | None:
    """The turn's answer: {"done": True, "message": …} or {"done": False, "why": …} from the last JSON object in its
    reply; None when there is none. A "done" with no message uses the words before the JSON.
      'Checked. {"done": true, "message": "CI is green now."}' -> {"done": True, "message": "CI is green now."}
      '{"done": false, "why": "needs your login"}' -> {"done": False, "why": "needs your login"};  "hm" -> None"""
    found = None
    for match in re.finditer(r"\{[^{}]*\}", text or "", re.S):
        found = match
    if found is None:
        return None
    try:
        raw = json.loads(found.group(0))
    except ValueError:
        return None
    if not isinstance(raw, dict) or "done" not in raw:
        return None
    if raw["done"] is True:
        message = str(raw.get("message") or "").strip() or (text or "")[:found.start()].strip()
        if not message:
            return None
        return {"done": True, "message": message[:1500]}
    return {"done": False, "why": str(raw.get("why") or "").strip()[:200]}


def night(now: datetime) -> bool:
    """No push from 22:00 to 07:00 (the post and the card still wait in the app): 23:00 -> True; 21:00 -> False."""
    return now.hour >= 22 or now.hour < 7


def push_once(store, loop: dict, now: datetime, push, body: str) -> None:
    from odie.watch import pushes
    if push is None or night(now):
        return
    pushes.started_by_odie(store, now, loop["personality"], loop["title"], body, push, ref=f"loop:{loop['id']}")


def his_card(store, loop: dict, now: datetime, why: str, push=None) -> str:
    """The promise becomes his card: owner you, no playbook (the clock stops; the ladder follows it as any card of
    his), its why in words and [Check now] as its move (a chat request written by code, sent by his tap)."""
    from odie.watch import cards as card_text
    when = loop.get("due_at") or now.isoformat(timespec="seconds")
    result = f"I said I'd do this by {card_text.day(when[:16])} but couldn't on my own"
    if why:
        result += f": {why}"
    ledger.update(store, loop["id"], now, owner="you", state="ready", playbook="", has_news=0, next_check_at=None,
                  result=result[:300], shown_at=now.isoformat(timespec="seconds"), attempts=0)
    ledger.merge_card(store, loop["id"], now, {"suggestion": "Check now"})
    ledger.add_event(store, loop["id"], now, "odie", "promise", f"Couldn't do it alone: {why or 'no clear answer'}")
    push_once(store, ledger.get(store, loop["id"]), now, push, "I said I'd do this; it needs you.")
    return "card"


async def run(store, loop: dict, now: datetime, act, tell, push=None) -> str:
    """Carries out one due promise. act(prompt, instruction, keep, guard): the background turn on the owner's brain
    with only these tools; tell(session_id, text): posts Odie's follow-up into that chat; push(title, body): a push.
    Returns "done" or "card"."""
    book = playbooks.get(PLAYBOOK)
    if not spend(store, now):
        return his_card(store, loop, now, "today's background checks were used up", push)
    try:
        reply = await act(prompt_for(loop), book.text, keeps, guard_for())
    except Exception as e:  # noqa: BLE001 (a failed turn: his card, never a crash of the clock)
        log.warning("promise #%s: the turn failed", loop["id"], exc_info=True)
        return his_card(store, loop, now, f"the check failed ({type(e).__name__})", push)
    answer = parse(reply)
    if answer is None:
        return his_card(store, loop, now, "", push)
    if not answer["done"]:
        return his_card(store, loop, now, answer["why"], push)
    chat = loop["card"].get("chat") or ""
    await tell(chat, answer["message"])
    first = answer["message"].splitlines()[0][:200]
    ledger.add_event(store, loop["id"], now, "odie", "promise", f"Followed up in chat: {first}")
    ledger.close(store, loop["id"], now, "odie", f"Did it: {first}")
    push_once(store, loop, now, push, first)
    return "done"
