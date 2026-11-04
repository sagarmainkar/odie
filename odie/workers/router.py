"""The Router: plain code that turns a start_job call into a running Worker, and keeps count. It picks the kind,
makes the job's folder, writes the row, and runs the Worker in its own task. At most MAX_AT_ONCE Workers run at a
time; the rest wait in order. The chat agent is the one that decides to start a job; this module never judges a
brief."""
from __future__ import annotations

import asyncio
import contextvars
import logging
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

from odie.store.db import Store
from odie.workers import store as jobs
from odie.workers import worker
from odie.workers.kinds import KINDS
from odie.workers.store import Job

log = logging.getLogger("odie.workers")

MAX_AT_ONCE = 3
DEFAULT_REPORTER_HOURS = 24  # a reporter with no end runs this long
MAX_REPORTER_DAYS = 7
MIN_EVERY_MINUTES = 5
hooks: dict = {}  # runner (posts the messages) and store; set by setup()
_tasks: dict[str, asyncio.Task] = {}
_slots: asyncio.Semaphore | None = None


def setup(store: Store, runner) -> None:
    """Called once at startup when workers are on: remember the runner and the store, and make sure the tables exist."""
    hooks.update(store=store, runner=runner)
    jobs.ensure(store)


def slug_of(title: str) -> str:
    """A folder name from a title: "Tides report!" -> "tides-report"; "" -> "job"."""
    s = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40]
    return s or "job"


def folder_for(title: str, job_id: str) -> Path:
    """The job's own folder under the workspace: <workspace>/jobs/<slug>-<id tail>/, made now."""
    from odie.agent.tools.files import workspace
    folder = workspace() / "jobs" / f"{slug_of(title)}-{job_id.removeprefix('job-')}"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _slots_now() -> asyncio.Semaphore:
    global _slots
    if _slots is None:
        _slots = asyncio.Semaphore(MAX_AT_ONCE)
    return _slots


def now_utc() -> datetime:
    return datetime.now(UTC)


def until_for(every_minutes: int, until_at: str | None, now: datetime) -> str | None:
    """When a reporter stops: the asked time, capped at MAX_REPORTER_DAYS; none asked -> DEFAULT_REPORTER_HOURS from now;
    a plain job (every_minutes 0) -> None."""
    if every_minutes <= 0:
        return None
    cap = now + timedelta(days=MAX_REPORTER_DAYS)
    end = cap
    if until_at:
        try:
            asked = datetime.fromisoformat(until_at)
            if asked.tzinfo is None:
                asked = asked.replace(tzinfo=UTC)
            end = min(asked, cap)
        except ValueError:
            end = now + timedelta(hours=DEFAULT_REPORTER_HOURS)
    else:
        end = now + timedelta(hours=DEFAULT_REPORTER_HOURS)
    return end.isoformat(timespec="seconds")


def start(kind_name: str, title: str, brief: str, session_id: str | None, every_minutes: int = 0,
          until_at: str | None = None) -> Job:
    """Start a job: the row, the folder, and a task that runs the Worker when a slot is free. every_minutes > 0 makes
    it a reporter: the kind becomes reporter and the task runs again every so often until until_at (until_for).
    Needs the running loop."""
    every_minutes = max(every_minutes, MIN_EVERY_MINUTES) if every_minutes > 0 else 0
    kind = KINDS["reporter"] if every_minutes else KINDS[kind_name]
    store = hooks["store"]
    job_id = jobs.new_id()
    folder = folder_for(title, job_id)
    job = jobs.create(store, kind.name, title, brief, session_id, folder, kind.budget_seconds,
                      every_minutes=every_minutes, until_at=until_for(every_minutes, until_at, now_utc()))
    launch(job)
    return job


def launch(job: Job) -> asyncio.Task:
    """Run the job's Worker in its own task (a reporter: again and again). Used by start, and by recovery after a
    restart. The Worker starts in a fresh, empty context, not a copy of the chat turn's (the making queue does the same)."""
    body = _repeat(job) if job.repeats else _run(job)
    task = asyncio.create_task(body, context=contextvars.Context(), name=job.id)
    _tasks[job.id] = task
    task.add_done_callback(lambda t: _tasks.pop(job.id, None))
    return task


async def _run(job: Job) -> None:
    async with _slots_now():
        try:
            await worker.run(job, hooks["store"], hooks["runner"])
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 (worker.run tells the chat itself; this is the last net)
            log.exception("worker %s crashed", job.id)


async def sleep(seconds: float) -> None:
    await asyncio.sleep(seconds)


async def _repeat(job: Job) -> None:
    """A reporter's life: run, wait every_minutes, run again, until until_at has passed; then the row says done and
    the chat hears once. A run that fails doesn't end the reporter (the next run may work; the watchdog counts). A
    reporter launched again (after a restart) first waits for the next_run_at its row kept, when that is still ahead."""
    store = hooks["store"]
    end = datetime.fromisoformat(job.until_at) if job.until_at else None
    kept = (jobs.get(store, job.id) or {}).get("next_run_at")
    if kept and datetime.fromisoformat(kept) > now_utc():
        jobs.waiting(store, job.id, kept)
        await sleep((datetime.fromisoformat(kept) - now_utc()).total_seconds())
    while True:
        await _run(job)
        next_at = now_utc() + timedelta(minutes=job.every_minutes)
        if end is not None and next_at >= end:
            break
        jobs.waiting(store, job.id, next_at.isoformat(timespec="seconds"))
        await sleep((next_at - now_utc()).total_seconds())
    jobs.ended(store, job.id, "done", outcome="ready", report=(jobs.get(store, job.id) or {}).get("report"))
    await hooks["runner"].post_message(f"🔁 {job.title} ({job.id}) finished after {job.runs} reports.", job.session_id, kind="job")


def stop(job_id: str) -> bool:
    """Stop a running or waiting job: its task is cancelled (a shell command in flight dies with it) and the row says
    stopped. A job that is not running -> False."""
    task = _tasks.get(job_id)
    if task is None or task.done():
        return False
    task.cancel()
    jobs.ended(hooks["store"], job_id, "stopped", error="stopped by the user")
    return True


def running_ids() -> list[str]:
    return [job_id for job_id, t in _tasks.items() if not t.done()]


async def fail(job_id: str, why: str) -> None:
    """The watchdog's verdict: cancel the job's task, mark the row failed with why, and tell its chat. A reporter is
    failed as a whole (its schedule ends); Retry starts it again."""
    store = hooks["store"]
    task = _tasks.get(job_id)
    if task is not None and not task.done():
        task.cancel()
    row = jobs.get(store, job_id)
    if row is None:
        return
    jobs.ended(store, job_id, "failed", error=why)
    await hooks["runner"].post_message(f"❌ {row['title']} didn't finish ({job_id}): {why}. Say \"retry {job_id}\" to start it again.",
                                       row["session_id"], kind="job")


def retry(job_id: str) -> Job | None:
    """Start a failed or stopped job again, same row, same folder, same brief (a reporter: its schedule again from
    now). A job still going, or unknown -> None."""
    store = hooks["store"]
    row = jobs.get(store, job_id)
    if row is None or row["status"] not in ("failed", "stopped"):
        return None
    if row["every_minutes"] and row["until_at"] and datetime.fromisoformat(row["until_at"]) <= now_utc():
        return None  # its schedule is over
    store.execute("update jobs set status='queued', error=null, ended_at=null, next_run_at=null where id=?", (job_id,))
    job = jobs.from_row(jobs.get(store, job_id))
    launch(job)
    return job


async def recover() -> list[str]:
    """Odie started: a job that was running or queued is told as cut off (its Worker is gone); a reporter that was
    running or waiting is launched again and keeps its schedule. Returns one line per job, for the log."""
    store = hooks["store"]
    lines = []
    for row in jobs.running(store):
        job = jobs.from_row(row)
        if job.repeats:
            launch(job)
            lines.append(f"{job.id}: reporter launched again")
            continue
        jobs.ended(store, job.id, "failed", error="Odie restarted")
        await hooks["runner"].post_message(f"❌ {job.title} didn't finish ({job.id}): Odie restarted. Say \"retry {job.id}\" to start it again.",
                                           job.session_id, kind="job")
        lines.append(f"{job.id}: cut off by the restart")
    for line in lines:
        log.info("workers: %s", line)
    return lines


async def stop_all() -> None:
    """Odie is shutting down: cancel every Worker and mark its job stopped."""
    for job_id in list(_tasks):
        stop(job_id)
    await asyncio.gather(*_tasks.values(), return_exceptions=True)
