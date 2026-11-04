"""The Router: plain code that turns a start_job call into a running Worker, and keeps count. It picks the kind,
makes the job's folder, writes the row, and runs the Worker in its own task. At most MAX_AT_ONCE Workers run at a
time; the rest wait in order. The chat agent is the one that decides to start a job; this module never judges a
brief."""
from __future__ import annotations

import asyncio
import contextvars
import logging
import re
from pathlib import Path

from odie.store.db import Store
from odie.workers import store as jobs
from odie.workers import worker
from odie.workers.kinds import KINDS
from odie.workers.store import Job

log = logging.getLogger("odie.workers")

MAX_AT_ONCE = 3
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


def start(kind_name: str, title: str, brief: str, session_id: str | None) -> Job:
    """Start a job: the row, the folder, and a task that runs the Worker when a slot is free. Needs the running loop."""
    kind = KINDS[kind_name]
    store = hooks["store"]
    job_id = jobs.new_id()
    folder = folder_for(title, job_id)
    job = jobs.create(store, kind.name, title, brief, session_id, folder, kind.budget_seconds)
    # The Worker starts in a fresh, empty context, not a copy of the chat turn's (the making queue does the same).
    task = asyncio.create_task(_run(job), context=contextvars.Context(), name=job.id)
    _tasks[job.id] = task
    task.add_done_callback(lambda t: _tasks.pop(job.id, None))
    return job


async def _run(job: Job) -> None:
    async with _slots_now():
        try:
            await worker.run(job, hooks["store"], hooks["runner"])
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 (worker.run tells the chat itself; this is the last net)
            log.exception("worker %s crashed", job.id)


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


async def stop_all() -> None:
    """Odie is shutting down: cancel every Worker and mark its job stopped."""
    for job_id in list(_tasks):
        stop(job_id)
    await asyncio.gather(*_tasks.values(), return_exceptions=True)
