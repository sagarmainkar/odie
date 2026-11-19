"""Workers on Pulse (Workers design): each personality's own jobs, in the same shapes as the loops'.
  - "on it": a job queued or running, one line each, with Stop;
  - a card in Needs you: a job the user started that failed, got stuck, or needed a step the rules refuse. It lists
    every step it needed, in full: plain words first, the exact command after, and whether a tap may allow it. Its
    move, written here, is "Allow it and run again" when some step may be allowed (exactly those calls, on the next
    run: odie.workers.allow), else "Retry"; Done takes the card off. No Later: a stuck job is run again or cleared;
  - a card in Needs you, too, for a job that finished with something worth keeping and a folder of his named for it:
    its move is "Keep it in <folder>" (odie.workers.keep: his tap copies it there); once kept, it is a Done today row
    that says where it went;
  - Done today: a job that finished today with nothing needed, or that he kept today.
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
        may_read = [home_form(d) for d in jobs.loads(row.get("read_dirs_json"))]
        next_words = uses_line(row).replace("Uses:", "uses")
        if may_read:
            next_words += "; may read " + ", ".join(may_read)
        out.append({"id": row["id"], "title": row["title"], "state": STATE_OF[row["status"]], "next": next_words,
                    "stop": row["id"]})
    return out


def needs_a_card(row: dict, now: datetime) -> bool:
    """Whether a job is a card on Pulse: the user started it, it ended in the last CARD_DAYS, wasn't cleared, and
    failed or got stuck (blocked), or finished with something he may keep (odie.workers.keep.offered). One that
    finished otherwise isn't, even if a step was refused on the way (it did it another way: worker.needs_shown).
      failed yesterday -> True;  done, blocked -> True;  done, a step refused but finished -> False;  done cleanly -> False
      done, a cloned repo to keep and ~/code/demos named -> True;  the same once kept -> False
      cleared -> False;  failed 4 days ago -> False;  Odie's own (a PR test) -> False;  still running -> False"""
    from odie.workers import keep as job_keep
    if row["started_by"] != "you" or row["cleared"] or row["status"] in jobs.GOING:
        return False
    ended = _ended(row)
    if ended is None or ended < now - timedelta(days=CARD_DAYS):
        return False
    went_wrong = row["status"] == "failed" or row["outcome"] == "blocked"
    return went_wrong or job_keep.offered(row)


def allowable(row: dict) -> list[dict]:
    """The needs his tap may allow for the next run: every recorded need a job card may offer (allow.offerable)."""
    return [n for n in jobs.needed(row) if allow.offerable(n)]


def steps_of(row: dict) -> list[dict]:
    """Every step the job needed, for the card: {"words": "Delete or stop something", "raw": "rm build.log",
    "allowed": True}; a step a job may never do: {"words": "Read secrets (only you can, in chat)", …, "allowed": False}."""
    out = []
    for need in jobs.needed(row):
        offered = allow.offerable(need)
        words = allow.plain(need)
        if not offered:
            words += " (only you can, in chat)"
        out.append({"words": words, "raw": allow.raw(need), "allowed": offered})
    return out


def _count(n: int, one: str, many: str) -> str:
    if n == 1:
        return f"1 {one}"
    return f"{n} {many}"


def why_of(row: dict) -> str:
    """The card's line: how many steps need his OK and how many it can't do as a job ("It needs your OK for 2 steps";
    "It needs your OK for 1 step; 1 it can't do as a job"), else why it failed, else the report's first line."""
    needed = jobs.needed(row)
    if needed:
        may = len(allowable(row))
        never = len(needed) - may
        parts = []
        if may:
            parts.append(f"It needs your OK for {_count(may, 'step', 'steps')}")
        if never:
            parts.append(f"{never} it can't do as a job")
        words = "; ".join(parts)
        if not may:
            words = f"It needed {_count(never, 'step', 'steps')} it can't do as a job"
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
    from odie.workers import keep as job_keep
    main = {"label": "Retry", "action": "job_retry", "value": row["id"]}
    if allowable(row):
        main = {"label": "Allow it and run again", "action": "job_allow", "value": row["id"]}
    if job_keep.offered(row):  # a new action: an app that doesn't know it says to update, never a dead button
        main = {"label": f"Keep it in {home_form(row['keep_to'])}", "action": "job_keep", "value": row["id"]}
    brief = ""
    if row["report"]:
        brief = row["report"][:BRIEF_MOST]
    badge = ""
    if row.get("taint"):
        badge = f"Brief: your own words (the chat read {row['taint']})"
    read_dirs = jobs.loads(row.get("read_dirs_json"))
    return {"ref": f"job:{row['id']}", "title": row["title"], "why": why_of(row), "brief": brief, "icon": "terminal",
            "badge": badge, "ask": f"What happened with job {row['id']} ({row['title']})?", "main": main,
            "other": {"label": "Done", "action": "job_clear", "value": row["id"]}, "pile": "alerts",
            "since": row["ended_at"] or "", "decide": False, "steps": steps_of(row),
            "allow_hash": allow.needs_hash(allowable(row)), "may_read": [home_form(d) for d in read_dirs],
            "uses": uses_line(row)}


def uses_line(row: dict) -> str:
    """What the card says the job may reach besides the folders it may read (its "May read" line): "Uses: the web";
    "Uses: the web and your mail"; an older row started without the web: "Uses: nothing outside its folder"."""
    from odie.workers.tools import uses_words
    uses = row.get("uses") or "web"
    return f"Uses: {uses_words(uses)}"


def home_form(path: str) -> str:
    """A path as the user writes it: "/Users/me/work/app" -> "~/work/app"; elsewhere -> as it is."""
    from pathlib import Path
    home = str(Path.home())
    if path.startswith(home + "/"):
        return "~" + path[len(home):]
    return path


def cards(store, pid: str, now: datetime) -> list[dict]:
    """This owner's job cards, newest first."""
    return [card(row) for row in jobs.of_owner(store, pid, 30) if needs_a_card(row, now)]


def done_today(store, pid: str, now: datetime) -> list[dict]:
    """This owner's jobs that finished cleanly today, for Done today: {"id", "title", "why": "done 10:42", "closed"};
    and the ones he kept today, saying where they went: "why": "kept in ~/code/demos/app (10:47)". A job with a keep
    waiting is a card instead (needs_a_card)."""
    from odie.workers import keep as job_keep
    start = datetime.combine(now.date(), time(0, 0), now.tzinfo)
    out = []
    for row in jobs.of_owner(store, pid, 30):
        if row["started_by"] != "you":
            continue
        kept = jobs.kept_of(row)
        if kept.get("at"):
            kept_at = datetime.fromisoformat(kept["at"].replace("Z", "+00:00"))
            if kept_at >= start:
                at = kept_at.astimezone(now.tzinfo).strftime("%H:%M")
                out.append({"id": row["id"], "title": row["title"], "why": f"{kept_line(kept)} ({at})",
                            "closed": kept["at"]})
            continue
        ended = _ended(row)
        clean = row["status"] == "done" and row["outcome"] != "blocked" and not jobs.needed(row)
        if not clean or ended is None or ended < start or job_keep.offered(row):
            continue
        at = ended.astimezone(now.tzinfo).strftime("%H:%M")
        out.append({"id": row["id"], "title": row["title"], "why": f"done {at}", "closed": row["ended_at"]})
    return out


def kept_line(kept: dict) -> str:
    """Where a kept job went, as its row says it: {"path": "<home>/code/demos/app"} -> "kept in
    ~/code/demos/app"; with 2 links left out -> "kept in ~/code/demos/app; left out 2 links that point outside
    it"."""
    from pathlib import Path

    from odie.workers.keep import Kept
    where = Kept(Path(kept.get("path") or ""))
    where.links_left_out = int(kept.get("links_left_out") or 0)
    where.others_left_out = int(kept.get("others_left_out") or 0)
    where.git_reset = bool(kept.get("git_reset"))
    line = where.line(home_form)
    return line[0].lower() + line[1:]
