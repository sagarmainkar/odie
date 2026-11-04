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
STATUSES = ("queued", "running", "done", "failed", "stopped")
OUTCOMES = ("ready", "blocked", "dropped")  # what a Worker may say in report


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


def ensure(store: Store) -> None:
    """Create the two tables if they are missing (safe to call on every start)."""
    with store._lock:
        store._conn.executescript(SCHEMA)


def new_id() -> str:
    """A short id nobody will mistake for a word: "job-3f9a2c"."""
    return "job-" + secrets.token_hex(3)


def create(store: Store, kind: str, title: str, brief: str, session_id: str | None, folder: Path,
           budget_seconds: int, model: str = "") -> Job:
    job = Job(new_id(), kind, title, brief, session_id, folder, budget_seconds, model)
    store.execute("insert into jobs(id,kind,title,brief,model,status,session_id,folder,budget_seconds,created_at) "
                  "values(?,?,?,?,?,?,?,?,?,?)",
                  (job.id, kind, title, brief, model, "queued", session_id, str(folder), budget_seconds, now_iso()))
    return job


def started(store: Store, job_id: str) -> None:
    """The Worker is running: one more run, and the start time."""
    store.execute("update jobs set status='running', runs=runs+1, started_at=? where id=?", (now_iso(), job_id))


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
    """Jobs still going (queued or running), oldest first."""
    return [dict(r) for r in store.query("select * from jobs where status in ('queued','running') order by created_at")]


def recent(store: Store, n: int = 10) -> list[dict]:
    """The last n jobs of any status, newest first."""
    return [dict(r) for r in store.query("select * from jobs order by created_at desc limit ?", (n,))]


def actions(store: Store, job_id: str) -> list[dict]:
    """Everything the Worker did on a job, in order."""
    return [dict(r) for r in store.query("select * from job_actions where job_id=? order by id", (job_id,))]
