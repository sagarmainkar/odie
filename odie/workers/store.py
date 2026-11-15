"""The jobs and job_actions tables (schema.sql next to this file): the record of every job and everything its Worker
did. The Router writes jobs, the Worker's callbacks write actions, and the watchdog (a later step) reads both."""
from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from odie.store.db import Store, now_iso

SCHEMA = Path(__file__).with_name("schema.sql").read_text()
STATUSES = ("queued", "running", "waiting", "done", "failed", "stopped")
OUTCOMES = ("ready", "blocked", "dropped")  # what a Worker may say in report
NOTIFY = ("always", "change", "condition")  # when a reporter's run is told


@dataclass
class Job:
    id: str
    kind: str
    title: str
    brief: str
    session_id: str | None
    folder: Path
    budget_seconds: int
    model: str = ""
    status: str = "queued"
    every_minutes: int = 0        # a reporter: runs again this often; 0 = a job that runs once
    until_at: str | None = None   # a reporter's last run is before this (UTC ISO)
    runs: int = 0
    notify: str = "always"        # a reporter speaks: always, on change of state, or when its condition is met
    condition: str = ""
    bot: str = ""                 # the bot this job runs as ("researcher"); "" = a plain Worker of its kind
    parent_id: str = ""           # a teammate's job asked for by a lead bot (ask_bots): reports to it, not to the chat
    conv_id: str = ""             # the conversation with its bot this job answers in (odie.workers.convs)

    @property
    def repeats(self) -> bool:
        """A reporter (every_minutes > 0) -> True; a plain job -> False."""
        return self.every_minutes > 0


# Columns added after the first spike: a home made before them gets them on start.
LATER_COLUMNS = (("jobs", "bot", "text not null default ''"), ("jobs", "parent_id", "text not null default ''"),
                 ("jobs", "conv_id", "text not null default ''"), ("bots", "look_json", "text"))


def ensure(store: Store) -> None:
    """Create the tables if they are missing, and add the later columns to an older jobs table (safe on every start)."""
    with store._lock:
        store._conn.executescript(SCHEMA)
        for table, column, kind in LATER_COLUMNS:
            have = {r[1] for r in store._conn.execute(f"pragma table_info({table})")}
            if column not in have:
                store._conn.execute(f"alter table {table} add column {column} {kind}")


def new_id() -> str:
    """A short id nobody will mistake for a word: "job-3f9a2c"."""
    return "job-" + secrets.token_hex(3)


def create(store: Store, kind: str, title: str, brief: str, session_id: str | None, folder: Path,
           budget_seconds: int, model: str = "", every_minutes: int = 0, until_at: str | None = None,
           notify: str = "always", condition: str = "", bot: str = "", parent_id: str = "", conv_id: str = "") -> Job:
    notify = notify if notify in NOTIFY else "always"
    job = Job(new_id(), kind, title, brief, session_id, folder, budget_seconds, model, every_minutes=every_minutes,
              until_at=until_at, notify=notify, condition=condition, bot=bot, parent_id=parent_id, conv_id=conv_id)
    store.execute("insert into jobs(id,kind,title,brief,model,status,session_id,folder,budget_seconds,every_minutes,"
                  "until_at,notify,condition,bot,parent_id,conv_id,created_at) values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (job.id, kind, title, brief, model, "queued", session_id, str(folder), budget_seconds, every_minutes,
                   until_at, notify, condition, bot, parent_id, conv_id, now_iso()))
    return job


def from_row(row: dict) -> Job:
    """A Job from its row (recovery after a restart, the watchdog)."""
    return Job(row["id"], row["kind"], row["title"], row["brief"], row["session_id"], Path(row["folder"]),
               row["budget_seconds"], row["model"], row["status"], row["every_minutes"], row["until_at"], row["runs"],
               row["notify"], row["condition"], row["bot"] or "", row["parent_id"] or "", row["conv_id"] or "")


def started(store: Store, job: Job) -> int:
    """The Worker is running: one more run, and the start time. Returns the run number (1 for the first)."""
    store.execute("update jobs set status='running', runs=runs+1, started_at=?, next_run_at=null where id=?",
                  (now_iso(), job.id))
    job.runs = store.one("select runs from jobs where id=?", (job.id,))["runs"]
    return job.runs


def waiting(store: Store, job_id: str, next_run_at: str) -> None:
    """A reporter between runs: when it runs next."""
    store.execute("update jobs set status='waiting', next_run_at=? where id=?", (next_run_at, job_id))


def ended(store: Store, job_id: str, status: str, outcome: str | None = None, report: str | None = None,
          error: str | None = None) -> None:
    """How the job ended: done with the Worker's outcome and report, or failed/stopped with why."""
    assert status in ("done", "failed", "stopped")
    store.execute("update jobs set status=?, outcome=?, report=?, error=?, ended_at=? where id=?",
                  (status, outcome, report, error, now_iso(), job_id))


def record_action(store: Store, job_id: str, tool: str, args: Any = None, result_chars: int | None = None,
                  refused: str | None = None, error: str | None = None) -> None:
    """One row per tool call: what was called, with what, and how it went."""
    store.execute("insert into job_actions(job_id,ts,tool,args_json,result_chars,refused,error) values(?,?,?,?,?,?,?)",
                  (job_id, now_iso(), tool, json.dumps(args, default=str)[:4000] if args is not None else None,
                   result_chars, refused, error))


def get(store: Store, job_id: str) -> dict | None:
    row = store.one("select * from jobs where id=?", (job_id,))
    return dict(row) if row else None


def running(store: Store) -> list[dict]:
    """Jobs still going (queued, running, or a reporter waiting for its next run), oldest first."""
    return [dict(r) for r in store.query("select * from jobs where status in ('queued','running','waiting') order by created_at")]


def recent(store: Store, n: int = 10) -> list[dict]:
    """The last n jobs of any status, newest first."""
    return [dict(r) for r in store.query("select * from jobs order by created_at desc limit ?", (n,))]


def actions(store: Store, job_id: str) -> list[dict]:
    """Everything the Worker did on a job, in order."""
    return [dict(r) for r in store.query("select * from job_actions where job_id=? order by id", (job_id,))]
