"""Routines: a bot that runs by itself on a schedule (spike, Nov 2026), like OpenBot's (its "Stock Markets: morning
note", "Jyotish: daily almanac"). A routine is a bot, a brief, and when: every day or on chosen weekdays at a time,
or every few hours. It never ends by itself (a Workers reporter stops after 7 days); the user pauses or deletes it.

Each routine has a conversation of its own ("Runs by itself" in the drawer). A run puts a small note in it, then a job
of the bot answers there with the conversation so far in its brief (odie.workers.convs), so the bot sees its earlier
runs and can say what changed. The reply arrives with a push like any bot message.

The clock is the Workers' once-a-minute job (odie.app.main): tick() starts what is due. A run missed while the Mac
slept runs once when it wakes, never several times over. Run now starts one at once."""
from __future__ import annotations

import json
import logging
import secrets
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from odie.store.db import Store, now_iso

log = logging.getLogger("odie.workers")

KINDS = ("daily", "every")
MIN_EVERY_HOURS = 1
MAX_EVERY_HOURS = 24 * 7
DAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
BRIEF_MAX = 2000
TITLE_MAX = 60



def ensure(store: Store) -> None:
    """The table lives in the workers' schema.sql (made with the jobs table); kept for callers."""
    from odie.workers import store as jobs
    jobs.ensure(store)


def tz() -> ZoneInfo:
    from odie import config
    return ZoneInfo(config.settings.timezone)


def clean_schedule(schedule: dict) -> dict | str:
    """A schedule as stored, or a line saying what's wrong.
      {"kind": "daily", "at": "8:30"} -> {"kind": "daily", "at": "08:30", "days": [0..6]} (every day)
      {"kind": "daily", "at": "07:00", "days": [0, 1, 2, 3, 4]} -> weekdays at 7
      {"kind": "every", "hours": 3} -> every 3 hours;  {"kind": "every", "hours": 0} -> "Every 1 to 168 hours."
      {"kind": "daily", "at": "25:00"} -> "A time like 08:30.\""""
    if not isinstance(schedule, dict) or schedule.get("kind") not in KINDS:
        return "Say when: daily at a time, or every few hours."
    if schedule["kind"] == "every":
        try:
            hours = int(schedule.get("hours"))
        except (TypeError, ValueError):
            return f"Every {MIN_EVERY_HOURS} to {MAX_EVERY_HOURS} hours."
        if not MIN_EVERY_HOURS <= hours <= MAX_EVERY_HOURS:
            return f"Every {MIN_EVERY_HOURS} to {MAX_EVERY_HOURS} hours."
        return {"kind": "every", "hours": hours}
    at = str(schedule.get("at") or "").strip()
    try:
        hh, mm = (int(x) for x in at.split(":", 1))
    except ValueError:
        return "A time like 08:30."
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        return "A time like 08:30."
    days = schedule.get("days")
    if days is None:
        days = list(range(7))
    days = sorted({int(d) for d in days if isinstance(d, int | float) and 0 <= int(d) <= 6})
    if not days:
        return "Pick at least one day."
    return {"kind": "daily", "at": f"{hh:02d}:{mm:02d}", "days": days}


def next_run(schedule: dict, after: datetime, zone: ZoneInfo | None = None) -> datetime:
    """When a routine runs next, strictly after `after` (UTC in, UTC out). Daily: the next chosen weekday at its local
    time; every N hours: N hours after `after`.
      daily 08:30, every day, after Mon 09:00 IST -> Tue 08:30 IST;  after Mon 08:00 IST -> Mon 08:30 IST
      daily 08:30 weekdays, after Fri 09:00 IST -> Mon 08:30 IST;  every 3 hours, after 10:00 -> 13:00"""
    zone = zone or tz()
    if schedule["kind"] == "every":
        return after + timedelta(hours=schedule["hours"])
    hh, mm = (int(x) for x in schedule["at"].split(":"))
    local = after.astimezone(zone)
    for step in range(8):
        day = (local + timedelta(days=step)).date()
        when = datetime(day.year, day.month, day.day, hh, mm, tzinfo=zone)
        if when > local and day.weekday() in schedule["days"]:
            return when.astimezone(UTC)
    raise ValueError("no day chosen")


def when_words(schedule: dict) -> str:
    """A schedule in words: daily 08:30 every day -> "Every day at 08:30"; weekdays -> "Weekdays at 08:30";
    Mon and Thu -> "Mon, Thu at 08:30"; every 3 hours -> "Every 3 hours"; every 1 hour -> "Every hour"."""
    if schedule["kind"] == "every":
        hours = schedule["hours"]
        return "Every hour" if hours == 1 else f"Every {hours} hours"
    days = schedule["days"]
    if days == list(range(7)):
        which = "Every day"
    elif days == [0, 1, 2, 3, 4]:
        which = "Weekdays"
    elif days == [5, 6]:
        which = "Weekends"
    else:
        which = ", ".join(DAY_NAMES[d] for d in days)
    return f"{which} at {schedule['at']}"


def _row(r) -> dict:
    out = dict(r)
    out["schedule"] = json.loads(out.pop("schedule_json"))
    out["when"] = when_words(out["schedule"])
    out["paused"] = bool(out["paused"])
    return out


def get(store: Store, routine_id: str) -> dict | None:
    r = store.one("select * from bot_routines where id=?", (routine_id,))
    return _row(r) if r else None


def of_bot(store: Store, bot: str) -> list[dict]:
    return [_row(r) for r in store.query("select * from bot_routines where bot=? order by created_at", (bot,))]


def make(store: Store, bot: str, title: str, brief: str, schedule: dict, now: datetime | None = None) -> dict | str:
    """A new routine for a bot, with its own conversation. Returns it, or a line saying what's wrong."""
    from odie.workers import bots, convs
    if bots.get(store, bot) is None:
        return f"There's no bot called {bot}."
    sched = clean_schedule(schedule)
    if isinstance(sched, str):
        return sched
    brief = (brief or "").strip()[:BRIEF_MAX]
    if not brief:
        return "Say what it should do each time."
    title = " ".join((title or "").split())[:TITLE_MAX] or brief.splitlines()[0][:TITLE_MAX]
    now = now or datetime.now(UTC)
    routine_id = "rt-" + secrets.token_hex(3)
    conv_id = convs.make(store, bot, title, origin="routine")
    nxt = next_run(sched, now).isoformat(timespec="seconds")
    store.execute("insert into bot_routines(id,bot,title,brief,schedule_json,paused,conv_id,next_run_at,created_at) "
                  "values(?,?,?,?,?,?,?,?,?)", (routine_id, bot, title, brief, json.dumps(sched), 0, conv_id, nxt, now_iso()))
    convs.add(store, conv_id, "note", f"Runs by itself: {when_words(sched)}. {brief}")
    return get(store, routine_id)


def edit(store: Store, routine_id: str, title: str | None = None, brief: str | None = None,
         schedule: dict | None = None, paused: bool | None = None, now: datetime | None = None) -> dict | str:
    """Change what is given. A new schedule or a resume sets the next run from now; pausing clears it."""
    r = get(store, routine_id)
    if r is None:
        return "There's no such routine."
    now = now or datetime.now(UTC)
    sched = r["schedule"]
    if schedule is not None:
        got = clean_schedule(schedule)
        if isinstance(got, str):
            return got
        sched = got
    new_title = " ".join(title.split())[:TITLE_MAX] if title is not None else r["title"]
    new_brief = brief.strip()[:BRIEF_MAX] if brief is not None else r["brief"]
    is_paused = r["paused"] if paused is None else bool(paused)
    timing_changed = schedule is not None or is_paused != r["paused"]
    if is_paused:
        nxt = None
    elif timing_changed:
        nxt = next_run(sched, now).isoformat(timespec="seconds")
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
        nxt = None if routine["paused"] else next_run(routine["schedule"], now).isoformat(timespec="seconds")
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
