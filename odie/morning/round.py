"""The morning round: the brief when it's due, then the day's hello when none is saved yet, from one gathering.

The 07:30 cron and the catch-up job at startup both run it, and the web may ask while one runs: a module-level lock
lets one round run at a time, and the hello is saved with `insert or ignore`, so a day has one hello and one model
call writes it."""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import asdict
from datetime import date, datetime, timedelta

from odie.jobs.brief import gather_inputs, missed_today, run_brief
from odie.morning.gather import gather, user_tz
from odie.morning.write import write_card
from odie.store.db import Store

log = logging.getLogger("odie.morning.round")

DAY_STARTS = 5  # the hello's day starts at 05:00 local time; before it, the hello is yesterday's
BRIEF_MARK = "\n\nThe morning brief: "  # what starts a brief's line added to a day summary after the hello

_round_lock = asyncio.Lock()


def morning_day(now: datetime) -> str:
    """The day the hello belongs to: today from 05:00, yesterday before it. 04:30 on 5 Nov -> "2026-11-04";
    05:00 on 5 Nov -> "2026-11-05"."""
    local = now.astimezone(user_tz())
    if local.hour < DAY_STARTS:
        local = local - timedelta(days=1)
    return local.date().isoformat()


def day_before(day: str) -> str:
    """"2026-11-04" -> "2026-11-03"."""
    return (date.fromisoformat(day) - timedelta(days=1)).isoformat()


def hello_for(store: Store, day: str) -> dict | None:
    """The hello saved for a morning day: {"card", "summary", "made_at"}, or None when that day has none."""
    row = store.one("select card_json, summary, made_at from mornings where day = ?", (day,))
    if row is None:
        return None
    return {"card": json.loads(row["card_json"]), "summary": row["summary"], "made_at": row["made_at"]}


def hello_due(store: Store, now: datetime) -> bool:
    """Whether today's hello is still to be written: it's 05:00 or later and none is saved for today. 06:10 with none
    saved -> True; 15:00 with none saved (the Mac was off all morning) -> True; 04:30 -> False (the day hasn't
    started); 09:00 with one saved at 07:30 -> False."""
    local = now.astimezone(user_tz())
    if local.hour < DAY_STARTS:
        return False
    return hello_for(store, morning_day(now)) is None


def hello_words(hello: dict | None) -> str:
    """What a saved hello said, for the writer to say something different: its greeting, then each paragraph on its
    own line. No hello -> ""."""
    if hello is None:
        return ""
    card = hello["card"]
    lines = [card.get("greeting", ""), *card.get("say", [])]
    return "\n".join(line for line in lines if line)


def todays_brief_text(store: Store, now: datetime) -> str:
    """The newest brief written today (the `briefs` row's date is the brief's own local date), or ""."""
    row = store.one("select text from briefs where date = ? order by id desc limit 1", (now.strftime("%Y-%m-%d"),))
    if row is None:
        return ""
    return row["text"]


def summary_with_brief(summary: str, brief_text: str) -> str:
    """The day summary with the brief's line at its end. A line an earlier brief added is replaced, never repeated.
    ("Dev wrote about the lease.", "Dentist at 10.") -> "Dev wrote about the lease.\n\nThe morning brief: Dentist at 10.";
    that summary and a second brief "Rain at 4." -> "Dev wrote about the lease.\n\nThe morning brief: Rain at 4."."""
    earlier = summary.rfind(BRIEF_MARK)
    if earlier != -1:
        summary = summary[:earlier]
    return summary + BRIEF_MARK + brief_text.strip()


def add_brief_to_hello(store: Store, now: datetime, brief_text: str) -> bool:
    """Whether a brief written after the day's hello was added to that hello's summary. A chat that starts from the
    summary gets no [today's brief] block, so a brief written later must reach it through the summary.
    Hello at 06:10, brief at 07:30 -> True (the summary ends with the brief's line); no hello saved yet (the hello is
    written next, with the brief among its inputs) -> False; an empty brief -> False."""
    if not brief_text.strip():
        return False
    day = morning_day(now)
    hello = hello_for(store, day)
    if hello is None:
        return False
    summary = summary_with_brief(hello["summary"], brief_text)
    store.execute("update mornings set summary = ? where day = ?", (summary, day))
    return True


def round_running() -> bool:
    """Whether a morning round is running right now (the web shows "making" while it is). A round holding the lock ->
    True; the lock free (no round, or the last one finished) -> False."""
    return _round_lock.locked()


async def morning_round(store: Store, now: datetime, runner=None, push: bool = True) -> None:
    """The brief when it's due, then today's hello when it's due; a second call while one runs returns at once."""
    if round_running():
        log.info("morning: a round is already running")
        return
    async with _round_lock:
        await run_round(store, now, runner, push)


async def run_round(store: Store, now: datetime, runner, push: bool) -> None:
    # The brief is due on the one rule the cron and the startup catch-up share: past 07:30, before noon, none today.
    brief_due = missed_today(store, now)
    hello_wanted = hello_due(store, now)
    if not brief_due and not hello_wanted:
        return

    post_message = None
    if runner is not None:
        post_message = runner.post_message
    # One gathering for both. Only the brief itself empties the watch's held list; a hello-only round (06:10)
    # reads it and leaves it for the 07:30 brief.
    brief_inputs = await gather_inputs(store, now, post_message=post_message, clear_held=brief_due)

    brief_text = ""
    if brief_due:
        try:
            brief_text = await run_brief(store, now, post_message=post_message, push=push, inputs=brief_inputs)
        except Exception:
            log.warning("morning: the brief couldn't be written; the hello goes on", exc_info=True)

    if not hello_wanted:
        # Today's hello was made before the brief (06:10, then 07:30): the brief joins its summary.
        added = add_brief_to_hello(store, now, brief_text)
        if added and runner is not None:
            runner.invalidate_prompt()  # open chats take the brief on their next message
        return
    await make_hello(store, now, brief_inputs, brief_text)
    if runner is not None:
        runner.invalidate_prompt()  # open chats take the day's summary on their next message


async def make_hello(store: Store, now: datetime, brief_inputs, brief_text: str) -> None:
    """Gather, write and save today's hello (one per day: a row already there is kept)."""
    day = morning_day(now)
    inp = await gather(store, now, brief_inputs)
    inp.yesterday_hello = hello_words(hello_for(store, day_before(day)))
    inp.brief_line = brief_text
    if not inp.brief_line:
        inp.brief_line = todays_brief_text(store, now)

    card = await write_card(store, now, inp)
    card["day"] = day  # the morning's day (write_card sets the calendar date)
    store.execute("insert or ignore into mornings(day, card_json, summary, made_at, inputs_json) values(?,?,?,?,?)",
                  (day, json.dumps(card), card["summary"], card["made_at"], json.dumps(asdict(inp))))
    store.audit("job", "morning", result_summary=card.get("greeting", ""))
