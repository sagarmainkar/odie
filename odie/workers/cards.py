"""Workers on Pulse (Workers design): each personality's own jobs, in the same shapes as the loops'.
  - "on it": a job queued or running, one line each, with Stop;
  - a card in Needs you: a job the user started that failed, got stuck, or needed a step the rules refuse. Its move,
    written here, is "Allow it and run again" when a step was refused (odie.workers.allow), else "Retry"; Done takes
    the card off. No Later: a stuck job is either run again or cleared;
  - Done today: a job that finished today with nothing needed.
Odie's own jobs (a pull request's test) are on "on it" while they run; their result is the loop's card."""
from __future__ import annotations

from datetime import datetime, time, timedelta

from odie.workers import allow
from odie.workers import store as jobs

CARD_DAYS = 3  # a stuck job's card stays this long unless cleared or run again
BRIEF_MOST = 160  # characters of the report a card shows (the whole report is in the chat)
STATE_OF = {"queued": "waiting for a slot", "running": "working"}


def _ended(row: dict) -> datetime | None:
    if not row.get("ended_at"):
        return None
    return datetime.fromisoformat(row["ended_at"].replace("Z", "+00:00"))


def on_it(store, pid: str) -> list[dict]:
    """This owner's jobs going now, for "on it": {"id": "job-3f9a2c", "title": "Tides", "state": "working", "next":
    "", "stop": "job-3f9a2c"}."""
    out = []
    for row in jobs.of_owner(store, pid, 30):
        if row["status"] not in jobs.GOING:
            continue
        out.append({"id": row["id"], "title": row["title"], "state": STATE_OF[row["status"]], "next": "",
                    "stop": row["id"]})
    return out


def needs_a_card(row: dict, now: datetime) -> bool:
    """Whether a job is a card on Pulse: the user started it, it ended in the last CARD_DAYS, wasn't cleared, and
    failed, got stuck or needed something.
      failed yesterday -> True;  done, a step refused -> True;  done, blocked -> True;  done cleanly -> False
      cleared -> False;  failed 4 days ago -> False;  Odie's own (a PR test) -> False;  still running -> False"""
    if row["started_by"] != "you" or row["cleared"] or row["status"] in jobs.GOING:
        return False
    ended = _ended(row)
    if ended is None or ended < now - timedelta(days=CARD_DAYS):
        return False
    went_wrong = row["status"] == "failed" or row["outcome"] == "blocked"
    return went_wrong or bool(jobs.needed(row))


def why_of(row: dict) -> str:
    """The card's line: what was needed, the first need with a long command cut ("I needed to: `x` (why) and 1 more"),
    else why it failed, else the report's first line."""
    needed = jobs.needed(row)
    if needed:
        words = "I needed to: " + allow.line(needed[0], short=True)
        if len(needed) > 1:
            words += f" and {len(needed) - 1} more"
        return words
    if row["status"] == "failed":
        return f"Didn't finish: {row['error'] or 'it stopped'}"
    if row["status"] == "stopped":
        return "Stopped"
    first = (row["report"] or "").strip().splitlines()
    if first:
        return first[0][:200]
    return "Stuck"


def card(row: dict) -> dict:
    """A job as a Pulse card, in the shape odie.watch.needs gives every card; its buttons are written here."""
    main = {"label": "Retry", "action": "job_retry", "value": row["id"]}
    if jobs.needed(row):
        main = {"label": "Allow it and run again", "action": "job_allow", "value": row["id"]}
    brief = ""
    if row["report"]:
        brief = row["report"][:BRIEF_MOST]
    return {"ref": f"job:{row['id']}", "title": row["title"], "why": why_of(row), "brief": brief, "icon": "terminal",
            "badge": "", "ask": f"What happened with job {row['id']} ({row['title']})?", "main": main,
            "other": {"label": "Done", "action": "job_clear", "value": row["id"]}, "pile": "alerts",
            "since": row["ended_at"] or "", "decide": False}


def cards(store, pid: str, now: datetime) -> list[dict]:
    """This owner's job cards, newest first."""
    return [card(row) for row in jobs.of_owner(store, pid, 30) if needs_a_card(row, now)]


def done_today(store, pid: str, now: datetime) -> list[dict]:
    """This owner's jobs that finished cleanly today, for Done today: {"id", "title", "why": "done 10:42", "closed"}."""
    start = datetime.combine(now.date(), time(0, 0), now.tzinfo)
    out = []
    for row in jobs.of_owner(store, pid, 30):
        ended = _ended(row)
        clean = row["status"] == "done" and row["outcome"] != "blocked" and not jobs.needed(row)
        if not clean or ended is None or ended < start or row["started_by"] != "you":
            continue
        at = ended.astimezone(now.tzinfo).strftime("%H:%M")
        out.append({"id": row["id"], "title": row["title"], "why": f"done {at}", "closed": row["ended_at"]})
    return out
