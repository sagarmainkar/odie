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
    async def start_job(title: str, brief: str, tool_context: ToolContext = None) -> dict:
        """Hand a long job to a background Worker and answer the user now. Use it when the job needs many steps, the shell, repeated checks or minutes of work: coding, testing, a system check, a report that takes digging. Answer in the chat yourself when one turn with reads and a quick draw will do (today's market, a note, a sum, a picture); if unsure, ask in one line. The Worker runs alone with the shell, files and the web, never asks the user anything, and posts its report into this chat when done or stuck. title: a few words the user will recognise. brief: everything the Worker needs, in full: the goal, where things are, what done looks like, what to leave alone. The Worker has a folder of its own for what it makes: name no paths for that unless the user did. Tell the user it started and that the result will come here."""
        job = router.start("task", title.strip()[:80] or "Job", brief.strip(), session_id_of(tool_context))
        return {"job_id": job.id, "folder": str(job.folder), "status": "started"}

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

    return [FunctionTool(start_job), FunctionTool(jobs_status), FunctionTool(stop_job)]
