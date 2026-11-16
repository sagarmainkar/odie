"""Routines: a bot that runs by itself on a schedule (spike, Nov 2026), like OpenBot's (a morning market note, a
daily digest). A routine is a bot, a brief, and when, said in words (odie.workers.when): "weekdays at 9:15 and 6pm",
"every 2 hours from 9 to 6", "1st and 15th at 9", "last Friday at 5pm", "tomorrow 3pm", "… until 30 Nov". It runs
until the user pauses or deletes it, or its words end it (a once, an until); a Workers reporter stops after 7 days.

Each routine has a conversation of its own ("Runs by itself" in the drawer). A run puts a small note in it, then a job
of the bot answers there with the conversation so far in its brief (odie.workers.convs), so the bot sees its earlier
runs and can say what changed. The reply arrives with a push like any bot message.

The clock is the Workers' once-a-minute job (odie.app.main): tick() starts what is due. A run missed while the Mac
slept runs once when it wakes, never several times over. Run now starts one at once."""
from __future__ import annotations

import json
import logging
import secrets
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from odie.store.db import Store, now_iso
from odie.workers import when

log = logging.getLogger("odie.workers")

BRIEF_MAX = 2000
TITLE_MAX = 60


def ensure(store: Store) -> None:
    """The table lives in the workers' schema.sql (made with the jobs table); kept for callers."""
    from odie.workers import store as jobs
    jobs.ensure(store)


def tz() -> ZoneInfo:
    from odie import config
    return ZoneInfo(config.settings.timezone)


def schedule_from(schedule: dict | None, words: str | None, now: datetime) -> dict | str:
    """A routine's schedule from the user's words ("weekdays at 9 and 6pm": odie.workers.when.parse) or a stored-form
    dict (when.clean), or a line saying what's wrong. Words win when both come."""
    if words is not None and words.strip():
        return when.parse(words, now, tz())
    return when.clean(schedule or {})


def _row(r) -> dict:
    """A routine as the app and tools see it: its schedule (an older stored form read as today's), the schedule in
    words, and whether it is finished (not paused, and no run left: a once that ran, or past its until)."""
    out = dict(r)
    stored = json.loads(out.pop("schedule_json"))
    cleaned = when.clean(stored)
    out["schedule"] = stored if isinstance(cleaned, str) else cleaned
    out["when"] = when.words(out["schedule"]) if not isinstance(cleaned, str) else "?"
    out["paused"] = bool(out["paused"])
    out["finished"] = not out["paused"] and out["next_run_at"] is None
    return out


def get(store: Store, routine_id: str) -> dict | None:
    r = store.one("select * from bot_routines where id=?", (routine_id,))
    return _row(r) if r else None


def of_bot(store: Store, bot: str) -> list[dict]:
    return [_row(r) for r in store.query("select * from bot_routines where bot=? order by created_at", (bot,))]


def make(store: Store, bot: str, title: str, brief: str, schedule: dict | None = None, now: datetime | None = None,
         words: str | None = None) -> dict | str:
    """A new routine for a bot, with its own conversation, timed by `words` ("weekdays at 9:15") or a stored-form
    `schedule`. Returns it, or a line saying what's wrong."""
    from odie.workers import bots, convs
    if bots.get(store, bot) is None:
        return f"There's no bot called {bot}."
    now = now or datetime.now(UTC)
    sched = schedule_from(schedule, words, now)
    if isinstance(sched, str):
        return sched
    first = when.next_run(sched, now, tz())
    if first is None:
        return "That time has passed."
    brief = (brief or "").strip()[:BRIEF_MAX]
    if not brief:
        return "Say what it should do each time."
    title = " ".join((title or "").split())[:TITLE_MAX] or brief.splitlines()[0][:TITLE_MAX]
    routine_id = "rt-" + secrets.token_hex(3)
    conv_id = convs.make(store, bot, title, origin="routine")
    nxt = first.isoformat(timespec="seconds")
    store.execute("insert into bot_routines(id,bot,title,brief,schedule_json,paused,conv_id,next_run_at,created_at) "
                  "values(?,?,?,?,?,?,?,?,?)", (routine_id, bot, title, brief, json.dumps(sched), 0, conv_id, nxt, now_iso()))
    convs.add(store, conv_id, "note", f"Runs by itself: {when.words(sched)}. {brief}")
    return get(store, routine_id)


def edit(store: Store, routine_id: str, title: str | None = None, brief: str | None = None,
         schedule: dict | None = None, paused: bool | None = None, now: datetime | None = None,
         words: str | None = None) -> dict | str:
    """Change what is given. A new schedule (`words` or `schedule`) or a resume sets the next run from now; pausing
    clears it. A new time with no run left (a once in the past) -> a line saying so, and nothing changes."""
    r = get(store, routine_id)
    if r is None:
        return "There's no such routine."
    now = now or datetime.now(UTC)
    sched = r["schedule"]
    new_timing = schedule is not None or (words is not None and words.strip() != "")
    if new_timing:
        got = schedule_from(schedule, words, now)
        if isinstance(got, str):
            return got
        sched = got
    new_title = " ".join(title.split())[:TITLE_MAX] if title is not None else r["title"]
    new_brief = brief.strip()[:BRIEF_MAX] if brief is not None else r["brief"]
    is_paused = r["paused"] if paused is None else bool(paused)
    timing_changed = new_timing or is_paused != r["paused"]
    if is_paused:
        nxt = None
    elif timing_changed:
        upcoming = when.next_run(sched, now, tz())
        if upcoming is None:
            return "It has no runs left: change when it runs."
        nxt = upcoming.isoformat(timespec="seconds")
    else:
        nxt = r["next_run_at"]  # a new name or brief keeps the next run where it was
    store.execute("update bot_routines set title=?, brief=?, schedule_json=?, paused=?, next_run_at=? where id=?",
                  (new_title or r["title"], new_brief or r["brief"], json.dumps(sched), int(is_paused), nxt, routine_id))
    return get(store, routine_id)


def delete(store: Store, routine_id: str) -> bool:
    """The routine stops for good; its conversation stays, with what it already said."""
    if get(store, routine_id) is None:
        return False
    store.execute("delete from bot_routines where id=?", (routine_id,))
    return True


def due(store: Store, now: datetime) -> list[dict]:
    """Routines whose next run has come (not paused), oldest due first."""
    rows = store.query("select * from bot_routines where paused=0 and next_run_at is not null and next_run_at<=? "
                       "order by next_run_at", (now.isoformat(timespec="seconds"),))
    return [_row(r) for r in rows]


def run(store: Store, routine: dict, now: datetime | None = None, scheduled: bool = True):
    """One run: a note in its conversation, then a job of its bot answering there (the brief carries the earlier runs).
    A scheduled run sets the next one from now, so a run missed while the Mac slept happens once; a run still going ->
    None (a scheduled one is skipped, the next stays set; Run now changes nothing)."""
    from odie.workers import convs, privacy, router
    now = now or datetime.now(UTC)
    busy = convs.running_job(store, routine["conv_id"]) is not None
    if busy and not scheduled:
        return None
    if scheduled:
        nxt = None
        if not routine["paused"]:
            upcoming = when.next_run(routine["schedule"], now, tz())  # None: a once, or past its until: finished
            if upcoming is not None:
                nxt = upcoming.isoformat(timespec="seconds")
        store.execute("update bot_routines set last_run_at=?, next_run_at=? where id=?",
                      (now.isoformat(timespec="seconds"), nxt, routine["id"]))
    else:
        store.execute("update bot_routines set last_run_at=? where id=?", (now.isoformat(timespec="seconds"), routine["id"]))
    if busy:
        return None
    local = now.astimezone(tz()).strftime("%a %d %b, %H:%M")
    brief = convs.brief_for(store, routine["conv_id"], ROUTINE_BRIEF.format(when=local, brief=routine["brief"]))
    convs.add(store, routine["conv_id"], "note", f"⏰ {routine['title']} · {local}")
    return router.start_bot(routine["bot"], routine["title"], brief, None, conv_id=routine["conv_id"],
                            private=privacy.marks_of(store, routine["conv_id"]))


ROUTINE_BRIEF = ("This is a scheduled run ({when}) of a routine the user set up: nobody typed this now. Do it, and say "
                 "what changed since your last run in this conversation; if nothing did, say so in one line.\n\n"
                 "The routine: {brief}")


async def tick(store: Store, now: datetime | None = None) -> list[str]:
    """The once-a-minute check: start every routine that is due. Returns one line per run, for the log and tests."""
    now = now or datetime.now(UTC)
    lines = []
    for r in due(store, now):
        try:
            job = run(store, r, now)
        except Exception:  # noqa: BLE001 (one broken routine never stops the others)
            log.warning("routine %s failed to start", r["id"], exc_info=True)
            continue
        lines.append(f"{r['id']}: {'started ' + job.id if job else 'still running, skipped'}")
    for line in lines:
        log.info("routines: %s", line)
    return lines
