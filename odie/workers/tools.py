"""The chat agent's tools for Workers: start a job, see the jobs, stop one, retry one, clear a failed one's card.
Their docstrings are the model's guidance on when a job is for a Worker and when the chat should just answer. Each
works on the jobs of whoever the chat belongs to (everyday Odie or a personality), never another's."""
from __future__ import annotations

from google.adk.tools import FunctionTool, ToolContext

from odie.agent.context import session_id_of
from odie.store.db import Store
from odie.workers import router
from odie.workers import store as jobs

ONLY_IN_CHAT = "Jobs start only from a chat with the user."


def job_line(j: dict) -> str:
    """One line for a job in jobs_status: "job-3f9a2c · running · Tides report (10:42)" (the time in UTC, as stored)."""
    when = (j.get("ended_at") or j.get("started_at") or j.get("created_at") or "")[11:16]
    line = f"{j['id']} · {j['status']} · {j['title']}"
    if when:
        line += f" ({when})"
    return line


def chat_of(tool_context) -> str | None:
    """The chat thread a tool call came from, or None when it isn't a chat (a background check, the watch): "chat-
    2026-11-18" -> itself; a watch turn's throwaway session -> None. So nothing in the background starts a job."""
    from odie import threads
    sid = session_id_of(tool_context)
    if not threads.valid_id(sid or ""):
        return None
    return sid


def owner_of(store: Store, tool_context) -> str:
    from odie import personalities
    return personalities.of_session(store, session_id_of(tool_context))


def own_job(store: Store, job_id: str, owner: str) -> dict | None:
    """The job when it belongs to this owner; another's (or none) -> None."""
    row = jobs.get(store, job_id)
    if row is None or (row["personality"] or "") != owner:
        return None
    return row


def make_worker_tools(store: Store) -> list[FunctionTool]:
    async def start_job(title: str, brief: str, tool_context: ToolContext = None) -> dict:
        """Hand a long job to a background Worker and answer the user now. A job is: code to write and run, a test to run, a check that takes more than one shell command, or anything that would take you over a minute. One read or one command: do it here yourself; a question (today's market, a sum, a note, a picture): answer here. If unsure, start the job. The Worker runs alone with the shell, its own folder, the web and your apps, never asks the user anything (a step that would need their tap is skipped and named in its report), and posts its report into this chat when done or stuck. title: a few words the user will recognise. brief: everything the Worker needs, in full: the goal, where things are, what done looks like, what to leave alone. Tell the user it started and that the result will come here."""
        session_id = chat_of(tool_context)
        if session_id is None:
            return {"error": ONLY_IN_CHAT}
        clean_title = title.strip()[:80]
        if not clean_title:
            clean_title = "Job"
        job = router.start(clean_title, brief.strip(), session_id, personality=owner_of(store, tool_context))
        return {"job_id": job.id, "status": "started", "folder": str(job.folder)}

    async def jobs_status(tool_context: ToolContext = None) -> dict:
        """The background jobs: what is running or waiting for a slot, and the last few that ended, with their reports."""
        owner = owner_of(store, tool_context)
        mine = jobs.of_owner(store, owner, 10)
        going = [job_line(j) for j in mine if j["status"] in jobs.GOING]
        ended = []
        for j in mine:
            if j["status"] in jobs.GOING:
                continue
            said = j.get("report") or j.get("error") or ""
            ended.append(f"{job_line(j)}: {said[:200]}")
        return {"running": going, "recent": ended[:5]}

    async def stop_job(job_id: str, tool_context: ToolContext = None) -> dict:
        """Stop a background job by its id (job-…): the user asked, or the job is no longer wanted."""
        if own_job(store, job_id, owner_of(store, tool_context)) is None or not router.stop(job_id):
            return {"error": f"{job_id} isn't running."}
        return {"stopped": job_id}

    async def retry_job(job_id: str, tool_context: ToolContext = None) -> dict:
        """Start a job that ended (failed, stopped, stuck) again by its id, with the same brief and folder: when the user says retry. A step it needed the user's OK for stays refused: only their tap on Pulse ("Allow it and run again") lets it run."""
        if chat_of(tool_context) is None or own_job(store, job_id, owner_of(store, tool_context)) is None:
            return {"error": f"{job_id} can't be retried here."}
        job = router.retry(job_id)
        if job is None:
            return {"error": f"{job_id} can't be retried: it is still going."}
        return {"job_id": job.id, "status": "started again"}

    async def forget_job(job_id: str, tool_context: ToolContext = None) -> dict:
        """Take a failed or stuck job's card off Pulse, when the user dismisses it or says to forget the job."""
        if own_job(store, job_id, owner_of(store, tool_context)) is None:
            return {"error": f"There's no job {job_id} here."}
        jobs.clear(store, job_id)
        return {"forgotten": job_id}

    return [FunctionTool(start_job), FunctionTool(jobs_status), FunctionTool(stop_job), FunctionTool(retry_job),
            FunctionTool(forget_job)]
