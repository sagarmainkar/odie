"""The router: plain code that turns a start into a running job, and keeps count. It makes the job's folder, writes the
row and runs the job in its own task. At most MAX_AT_ONCE jobs run at a time; the rest wait in order. Odie's own jobs
(a loop's step) take at most ODIE_AT_ONCE of those slots, so one is always free for the user's, and at most ODIE_DAILY
start a day. The chat agent decides to start a user's job; this module never judges a brief."""
from __future__ import annotations

import asyncio
import contextvars
import logging
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from odie import config
from odie.store.db import Store
from odie.workers import store as jobs
from odie.workers import worker
from odie.workers.store import Job

log = logging.getLogger("odie.workers")

MAX_AT_ONCE = 3
ODIE_AT_ONCE = 2  # Odie's own jobs: one of the three slots is always the user's
ODIE_DAILY = 8
MAX_WAITING = 6  # an owner's jobs waiting for a slot; one more is refused (TooMany)
hooks: dict = {}  # store and runner (which posts the messages); set by setup()
_tasks: dict[str, asyncio.Task] = {}
_slots: dict[str, asyncio.Semaphore] = {}


class TooMany(Exception):
    """An owner already has MAX_WAITING jobs waiting for a slot: said in words for the chat."""


def setup(store: Store, runner) -> None:
    """Called once at startup (and by tests): the store and the runner, and fresh slots."""
    hooks.update(store=store, runner=runner)
    _tasks.clear()
    _slots.update(all=asyncio.Semaphore(MAX_AT_ONCE), odie=asyncio.Semaphore(ODIE_AT_ONCE))


def slug_of(title: str) -> str:
    """A folder name from a title: "Tides report!" -> "tides-report"; "" -> "job"."""
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40]
    if not slug:
        return "job"
    return slug


def folder_for(title: str, job_id: str) -> Path:
    """The job's own folder under the workspace: <workspace>/jobs/<slug>-<id tail>/, made now."""
    from odie.agent.tools.files import workspace
    folder = workspace() / "jobs" / f"{slug_of(title)}-{job_id.removeprefix('job-')}"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def now_local() -> datetime:
    return datetime.now(ZoneInfo(config.settings.timezone))


def odie_left_today(store: Store) -> int:
    """How many more jobs Odie may start itself today: ODIE_DAILY less the ones it started since midnight."""
    return max(0, ODIE_DAILY - jobs.started_today_by_odie(store, now_local()))


def waiting_for(store: Store, personality: str) -> int:
    """How many of this owner's own jobs (not Odie's) are queued, waiting for a slot."""
    rows = jobs.of_owner(store, personality, 50)
    return len([r for r in rows if r["status"] == "queued" and r["started_by"] == "you"])


def start(title: str, brief: str, session_id: str | None, personality: str = "", kind: str = "task",
          started_by: str = "you", loop_id: int | None = None, taint: str = "") -> Job | None:
    """Start a job: the row, the folder, and a task that runs it when a slot is free. Returns the job, or None when it
    is Odie's own and today's ODIE_DAILY are used. A user's job with MAX_WAITING of theirs already waiting raises
    TooMany. taint: the outside text the starting chat had read (no web, no apps for its Worker). Needs the running loop."""
    store = hooks["store"]
    if started_by == "odie" and odie_left_today(store) <= 0:
        log.info("workers: Odie's own jobs for today are used (%d)", ODIE_DAILY)
        return None
    if started_by == "you" and waiting_for(store, personality) >= MAX_WAITING:
        raise TooMany(f"{MAX_WAITING} jobs are already waiting for a slot; stop one, or start this when one ends.")
    job_id = jobs.new_id()
    folder = folder_for(title, job_id)
    job = jobs.create(store, kind, title, brief, session_id, folder, worker.BUDGET_SECONDS, personality=personality,
                      started_by=started_by, loop_id=loop_id, job_id=job_id, taint=taint)
    launch(job)
    return job


def launch(job: Job) -> asyncio.Task:
    """Run the job in its own task, in a fresh, empty context (not a copy of the chat turn's)."""
    task = asyncio.create_task(_run(job), context=contextvars.Context(), name=job.id)
    _tasks[job.id] = task
    task.add_done_callback(lambda t: _forget_task(job.id, t))
    return task


def _forget_task(job_id: str, task: asyncio.Task) -> None:
    if _tasks.get(job_id) is task:
        _tasks.pop(job_id, None)


async def _body(job: Job) -> str:
    """What runs in the slot: a Worker for a user's task; code for a pull request's test (odie.loops.pr_test)."""
    store = hooks["store"]
    if job.kind == "pr_test":
        from odie.loops import pr_test
        return await pr_test.run_job(job, store)
    return await worker.run(job, store, hooks["runner"])


async def _run(job: Job) -> str:
    """The job, once its slots are free: Odie's own first wait for one of its ODIE_AT_ONCE, then any job for one of the
    MAX_AT_ONCE. Returns its status ("done" or "failed")."""
    try:
        if job.odies_own:
            async with _slots["odie"]:
                async with _slots["all"]:
                    return await _body(job)
        async with _slots["all"]:
            return await _body(job)
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001 (the run tells the chat itself; this is the last net)
        log.exception("job %s crashed", job.id)
        jobs.ended(hooks["store"], job.id, "failed", error="crashed")
        return "failed"


def stop(job_id: str) -> bool:
    """Stop a queued or running job: its task is cancelled (a shell command in flight dies with it) and the row says
    stopped. A job that is not going -> False."""
    from odie.workers.shell import kill_job
    task = _tasks.get(job_id)
    if task is None or task.done():
        return False
    task.cancel()
    kill_job(job_id)  # its commands' processes, background children too
    jobs.ended(hooks["store"], job_id, "stopped", error="stopped by you")
    return True


def stop_for(personality: str) -> None:
    """A personality is being deleted: every job of its that is going stops."""
    for row in jobs.running(hooks["store"]):
        if (row["personality"] or "") == personality:
            stop(row["id"])


def running_ids() -> list[str]:
    return [job_id for job_id, t in _tasks.items() if not t.done()]


async def tell_cut_off(row: dict, why: str) -> None:
    """A job ended without its own words (the watchdog, a restart): a user's job says so in its chat; Odie's own (a
    pull request's test) writes it on its loop instead."""
    if row["kind"] == "pr_test":
        from odie.loops import pr_test
        pr_test.cut_off(hooks["store"], row, why)
        return
    text = (f"❌ {row['title']} didn't finish ({row['id']}): {why}. Say \"retry {row['id']}\", or tap Retry on "
            "Pulse.")
    await hooks["runner"].post_message(text, row["session_id"], kind="job")


async def fail(job_id: str, why: str) -> None:
    """The watchdog's verdict: cancel the job's task, mark the row failed with why, and tell (tell_cut_off)."""
    from odie.workers.shell import kill_job
    store = hooks["store"]
    task = _tasks.get(job_id)
    if task is not None and not task.done():
        task.cancel()
    kill_job(job_id)
    row = jobs.get(store, job_id)
    if row is None:
        return
    jobs.ended(store, job_id, "failed", error=why)
    await tell_cut_off(row, why)


def may_retry(row: dict | None) -> bool:
    """Whether a job may be started again: a user's task that ended. Still going -> False; a pull request's test
    (Odie's own: it goes through the rail and the daily count again, never a plain retry) -> False; unknown -> False."""
    if row is None or row["status"] in jobs.GOING:
        return False
    return row["kind"] == "task" and row["started_by"] == "you"


def retry(job_id: str, allowed: list | None = None) -> Job | None:
    """Start a job that ended again: same row, same folder, same brief. allowed: what the user's tap in the app lets
    through on this run (odie.workers.allow); the chat's retry_job passes none. One that may_retry refuses -> None."""
    store = hooks["store"]
    row = jobs.get(store, job_id)
    if not may_retry(row):
        return None
    jobs.queued_again(store, job_id, list(allowed or []))
    job = jobs.from_row(jobs.get(store, job_id))
    launch(job)
    return job


async def recover() -> list[str]:
    """Odie started: a job that was queued or running is told as cut off (its task is gone). Returns one line per
    job, for the log."""
    store = hooks["store"]
    lines = []
    for row in jobs.running(store):
        jobs.ended(store, row["id"], "failed", error="Odie restarted")
        await tell_cut_off(row, "Odie restarted")
        lines.append(f"{row['id']}: cut off by the restart")
    for line in lines:
        log.info("workers: %s", line)
    return lines


async def stop_all() -> None:
    """Odie is shutting down: cancel every job's task and leave the rows as they are, so recover() at the next start
    tells the cut-off jobs."""
    from odie.workers.shell import kill_job
    tasks = list(_tasks.items())
    for job_id, task in tasks:
        task.cancel()
        kill_job(job_id)
    await asyncio.gather(*(t for _, t in tasks), return_exceptions=True)
