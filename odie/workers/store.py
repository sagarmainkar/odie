"""The jobs and job_actions tables (odie/store/schema.sql): the record of every job and everything its Worker did. The
router writes jobs, the Worker's callbacks write actions, the watchdog and Pulse read both."""
from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from odie.store.db import Store, now_iso

STATUSES = ("queued", "running", "done", "failed", "stopped")
OUTCOMES = ("ready", "blocked", "dropped")  # what a Worker may say in report
GOING = ("queued", "running")


@dataclass
class Job:
    id: str
    kind: str              # "task" (a Worker) or "pr_test" (code runs a pull request's tests)
    title: str
    brief: str
    session_id: str | None  # the chat it came from, where its report goes (None: Odie's own)
    folder: Path
    budget_seconds: int
    personality: str = ""  # whose job it is: "" everyday Odie, else a personality's id
    started_by: str = "you"  # "you" (from chat) or "odie" (its own, a loop's step)
    loop_id: int | None = None
    status: str = "queued"
    runs: int = 0
    allowed: list = None  # what the user's tap allowed for this run (odie.workers.allow)

    @property
    def odies_own(self) -> bool:
        """Started by Odie itself (a loop's step) -> True; started from chat -> False."""
        return self.started_by == "odie"


def new_id() -> str:
    """A short id nobody will mistake for a word: "job-3f9a2c"."""
    return "job-" + secrets.token_hex(3)


def create(store: Store, kind: str, title: str, brief: str, session_id: str | None, folder: Path,
           budget_seconds: int, personality: str = "", started_by: str = "you", loop_id: int | None = None,
           job_id: str = "") -> Job:
    """A new row, queued. job_id: one made beforehand (the router names the folder after it); else a new one."""
    if not job_id:
        job_id = new_id()
    job = Job(job_id, kind, title, brief, session_id, folder, budget_seconds, personality, started_by, loop_id,
              allowed=[])
    store.execute("insert into jobs(id,kind,title,brief,personality,started_by,loop_id,status,session_id,folder,"
                  "budget_seconds,created_at) values(?,?,?,?,?,?,?,?,?,?,?,?)",
                  (job.id, kind, title, brief, personality or None, started_by, loop_id, "queued", session_id,
                   str(folder), budget_seconds, now_iso()))
    return job


def from_row(row: dict) -> Job:
    """A Job from its row (retry, recovery after a restart, the watchdog)."""
    return Job(row["id"], row["kind"], row["title"], row["brief"], row["session_id"], Path(row["folder"]),
               row["budget_seconds"], row["personality"] or "", row["started_by"], row["loop_id"], row["status"],
               row["runs"], loads(row["allowed_json"]))


def loads(text: str | None) -> list:
    """A JSON list column read back; anything else is []: '[{"why": "x"}]' -> [{"why": "x"}]; None or '{}' -> []."""
    try:
        value = json.loads(text or "[]")
    except ValueError:
        return []
    if not isinstance(value, list):
        return []
    return value


def started(store: Store, job: Job) -> int:
    """The run is starting: one more run, and the start time. Returns the run number (1 for the first)."""
    store.execute("update jobs set status='running', runs=runs+1, started_at=? where id=?", (now_iso(), job.id))
    job.runs = store.one("select runs from jobs where id=?", (job.id,))["runs"]
    return job.runs


def ended(store: Store, job_id: str, status: str, outcome: str | None = None, report: str | None = None,
          error: str | None = None) -> None:
    """How the job ended: done with the Worker's outcome and report, or failed/stopped with why."""
    if status not in ("done", "failed", "stopped"):
        raise ValueError(f"not an end: {status}")
    store.execute("update jobs set status=?, outcome=?, report=?, error=?, ended_at=? where id=?",
                  (status, outcome, report, error, now_iso(), job_id))


def queued_again(store: Store, job_id: str, allowed: list) -> None:
    """A retry: queued again with what the user's tap allowed for this run ([] for none), and no needs yet."""
    store.execute("update jobs set status='queued', outcome=null, error=null, ended_at=null, cleared=0, "
                  "needed_json='[]', allowed_json=? where id=?", (json.dumps(allowed), job_id))


def record_action(store: Store, job_id: str, tool: str, args: Any = None, result_chars: int | None = None,
                  refused: str | None = None, error: str | None = None) -> None:
    """One row per tool call: what was called, with what, and how it went."""
    args_json = None
    if args is not None:
        args_json = json.dumps(args, default=str)[:4000]
    store.execute("insert into job_actions(job_id,ts,tool,args_json,result_chars,refused,error) values(?,?,?,?,?,?,?)",
                  (job_id, now_iso(), tool, args_json, result_chars, refused, error))


def note_needed(store: Store, job_id: str, need: dict) -> None:
    """Something the Worker was refused, kept once ({"tool", "command" or "args", "why"}), for the report and the card."""
    row = get(store, job_id)
    if row is None:
        return
    kept = needed(row)
    if need in kept:
        return
    kept.append(need)
    store.execute("update jobs set needed_json=? where id=?", (json.dumps(kept[-10:]), job_id))


def needed(row: dict) -> list[dict]:
    return loads(row.get("needed_json"))


def set_allowed(store: Store, job_id: str, allowed: list) -> None:
    store.execute("update jobs set allowed_json=? where id=?", (json.dumps(allowed), job_id))


def clear(store: Store, job_id: str) -> None:
    """Its card goes off Pulse (forget_job, or the card's Done)."""
    store.execute("update jobs set cleared=1 where id=?", (job_id,))


def get(store: Store, job_id: str) -> dict | None:
    row = store.one("select * from jobs where id=?", (job_id,))
    if row is None:
        return None
    return dict(row)


def running(store: Store) -> list[dict]:
    """Jobs still going (queued or running), oldest first."""
    rows = store.query("select * from jobs where status in ('queued','running') order by created_at")
    return [dict(r) for r in rows]


def _whose(pid: str) -> tuple[str, tuple]:
    if not pid:
        return "personality is null", ()
    return "personality = ?", (pid,)


def of_owner(store: Store, pid: str, n: int = 20) -> list[dict]:
    """One owner's last n jobs of any status, newest first: everyday Odie's ("") or a personality's."""
    mine, values = _whose(pid)
    rows = store.query(f"select * from jobs where {mine} order by created_at desc limit ?", (*values, n))
    return [dict(r) for r in rows]


def started_today_by_odie(store: Store, now: datetime) -> int:
    """How many jobs Odie started itself today (its own budget, 8 a day), on the user's clock."""
    since = datetime.combine(now.date(), datetime.min.time(), now.tzinfo)
    rows = store.query("select created_at from jobs where started_by='odie'")
    count = 0
    for row in rows:
        at = datetime.fromisoformat(row["created_at"].replace("Z", "+00:00"))
        if at >= since:
            count += 1
    return count


def actions(store: Store, job_id: str) -> list[dict]:
    """Everything the Worker did on a job, in order."""
    return [dict(r) for r in store.query("select * from job_actions where job_id=? order by id", (job_id,))]


def forget_personality(store: Store, pid: str) -> None:
    """A personality was deleted: its jobs and their records go."""
    if not pid:
        return
    for row in store.query("select id from jobs where personality=?", (pid,)):
        store.execute("delete from job_actions where job_id=?", (row["id"],))
    store.execute("delete from jobs where personality=?", (pid,))
