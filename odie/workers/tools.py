"""The chat agent's three tools for workers: start a job, see the jobs, stop one. Their docstrings are the model's
guidance on when a job is for a Worker and when the chat should just answer."""
from __future__ import annotations

from google.adk.tools import FunctionTool, ToolContext

from odie.agent.context import session_id_of
from odie.store.db import Store
from odie.workers import router
from odie.workers import store as jobs


def job_line(j: dict) -> str:
    """One line for a job in jobs_status: "job-3f9a2c · running · Tides report (started 10:42)"."""
    when = (j.get("ended_at") or j.get("started_at") or j.get("created_at") or "")[11:16]
    tail = f" ({j['status']} {when})" if when else ""
    return f"{j['id']} · {j['status']} · {j['title']}{tail}"


def make_worker_tools(store: Store) -> list[FunctionTool]:
    async def start_job(title: str, brief: str, every_minutes: int = 0, until: str = "", tool_context: ToolContext = None) -> dict:
        """Hand a long job to a background Worker and answer the user now. A job is: code to write and run, a test to run, a check that takes more than one shell command, anything that repeats, or anything that would take you over a minute. Coding, testing, a system check, a report that takes digging. One read or one command: do it here yourself, as before; a question (today's market, a sum, a note, a picture): answer here. If unsure, start the job. The Worker runs alone with the shell, files and the web, never asks the user anything, and posts its report into this chat when done or stuck. title: a few words the user will recognise. brief: everything the Worker needs, in full: the goal, where things are, what done looks like, what to leave alone. The Worker has a folder of its own for what it makes: name no paths for that unless the user did. every_minutes: for something to check again and again ("track X and report every hour" -> 60): the same Worker runs that often and posts a report each time, until `until` (a local date-time like 2026-11-04T18:00; left out: 24 hours) or stop_job. Tell the user it started and that the result will come here."""
        until_at = until.strip() or None
        if until_at:
            from datetime import datetime
            from zoneinfo import ZoneInfo

            from odie import config
            try:
                asked = datetime.fromisoformat(until_at)
                if asked.tzinfo is None:
                    asked = asked.replace(tzinfo=ZoneInfo(config.settings.timezone))
                until_at = asked.isoformat(timespec="seconds")
            except ValueError:
                until_at = None
        job = router.start("task", title.strip()[:80] or "Job", brief.strip(), session_id_of(tool_context),
                           every_minutes=int(every_minutes or 0), until_at=until_at)
        out = {"job_id": job.id, "folder": str(job.folder), "status": "started"}
        if job.repeats:
            out["repeats"] = f"every {job.every_minutes} minutes until {job.until_at}"
        return out

    async def jobs_status() -> dict:
        """The background jobs: what is running or waiting, and the last few that ended, with their reports."""
        going = [job_line(j) for j in jobs.running(store)]
        ended = [f"{job_line(j)}: {(j.get('report') or j.get('error') or '')[:200]}" for j in jobs.recent(store, 5)
                 if j["status"] not in ("queued", "running")]
        return {"running": going, "recent": ended}

    async def stop_job(job_id: str) -> dict:
        """Stop a background job by its id (job-…). The user asked, or the job is no longer wanted."""
        if router.stop(job_id):
            return {"stopped": job_id}
        return {"error": f"{job_id} isn't running."}

    async def retry_job(job_id: str) -> dict:
        """Start a failed or stopped job again by its id, with the same brief and folder: when the user says retry, or asks for it again after it didn't finish."""
        job = router.retry(job_id)
        if job is None:
            return {"error": f"{job_id} can't be retried: it is still going, its schedule is over, or there's no such job."}
        return {"job_id": job.id, "status": "started again", "run": job.runs + 1}

    return [FunctionTool(start_job), FunctionTool(jobs_status), FunctionTool(stop_job), FunctionTool(retry_job)]
