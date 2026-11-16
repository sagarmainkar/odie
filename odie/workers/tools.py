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


def until_in_users_time(until: str) -> str | None:
    """The model's `until`, a local date-time, with the user's time zone on it; empty or unreadable -> None (the
    Router's default end). "2026-11-04T18:00" in Asia/Kolkata -> "2026-11-04T18:00:00+05:30"; "tomorrow" -> None."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from odie import config
    text = (until or "").strip()
    if not text:
        return None
    try:
        asked = datetime.fromisoformat(text)
    except ValueError:
        return None
    if asked.tzinfo is None:
        asked = asked.replace(tzinfo=ZoneInfo(config.settings.timezone))
    return asked.isoformat(timespec="seconds")


def team_card(job_id: str, bot_name: str) -> dict:
    """The live team card shown under the chat's reply (the app polls /api/jobs/{id}/team): the media's id, kind and
    title, as a tool's result carries it."""
    import json

    from odie import media
    title = "The team at work" if bot_name == "chief" else f"{bot_name} at work"
    made = media.save(json.dumps({"job": job_id}).encode(), "team", "team", "application/json", title,
                      {"job": job_id, "bot": bot_name})
    return {k: made[k] for k in ("id", "kind", "title")}


PRIVATE_CHAT = ("This chat has read a signed-in page, and a background Worker "
                "has nobody to ask before it searches: start a new chat for it, or ask a bot (ask_bot), whose steps "
                "wait for your tap.")


def bring_privacy_in(store: Store, job_ids: list[str], session_id: str | None) -> None:
    """Reports read into this chat carry what their jobs read: the chat turns as private as the most private of them
    (odie.workers.privacy). A shopper's orders report shown here -> the chat is private from now on."""
    from odie.agent import turn
    from odie.workers import privacy
    for job_id in job_ids:
        sites, reads = privacy.marks_of(store, job_id)
        for site in sites:
            turn.mark_private(site)
        for label in reads:
            turn.mark_read(label)
        if session_id:
            privacy.carry(store, session_id, sites, reads)


def make_worker_tools(store: Store) -> list[FunctionTool]:
    async def start_job(title: str, brief: str, every_minutes: int = 0, until: str = "", notify: str = "always",
                        condition: str = "", tool_context: ToolContext = None) -> dict:
        """Hand a long job to a background Worker and answer the user now. A job is: code to write and run, a test to run, a check that takes more than one shell command, anything that repeats, or anything that would take you over a minute. Coding, testing, a system check, a report that takes digging. One read or one command: do it here yourself, as before; a question (today's market, a sum, a note, a picture): answer here. If unsure, start the job. The Worker runs alone with the shell, files and the web, never asks the user anything, and posts its report into this chat when done or stuck. title: a few words the user will recognise. brief: everything the Worker needs, in full: the goal, where things are, what done looks like, what to leave alone. The Worker has a folder of its own for what it makes: name no paths for that unless the user did. every_minutes: for something to check again and again ("track X and report every hour" -> 60): the same Worker runs that often and posts a report each time, until `until` (a local date-time like 2026-11-04T18:00; left out: 24 hours) or stop_job. notify, for a repeating check: "always" (every run posts), "change" (the first run, then only when the facts changed: an order's status, a score), or "condition" (only when `condition` holds: "price below 3000"; put the condition in the brief too). Tell the user it started and that the result will come here."""
        from odie.signin import guard
        if guard.query_needs_tap(store):  # a plain Worker has no tap: a signed-in page this chat read can't go with it
            return {"error": PRIVATE_CHAT}
        until_at = until_in_users_time(until)
        job = router.start("task", title.strip()[:80] or "Job", brief.strip(), session_id_of(tool_context),
                           every_minutes=int(every_minutes or 0), until_at=until_at, notify=notify.strip().lower(),
                           condition=condition.strip())
        out = {"job_id": job.id, "folder": str(job.folder), "status": "started"}
        if job.repeats:
            out["repeats"] = f"every {job.every_minutes} minutes until {job.until_at}, telling you: {job.notify}"
        return out

    async def jobs_status(tool_context: ToolContext = None) -> dict:
        """The background jobs: what is running or waiting, and the last few that ended, with their reports."""
        going = [job_line(j) for j in jobs.running(store)]
        recent = [j for j in jobs.recent(store, 5) if j["status"] not in ("queued", "running")]
        ended = [f"{job_line(j)}: {(j.get('report') or j.get('error') or '')[:200]}" for j in recent]
        bring_privacy_in(store, [j["id"] for j in recent], session_id_of(tool_context))
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

    async def forget_job(job_id: str) -> dict:
        """Take a failed or stuck job's card off Today, when the user dismisses it or says to forget the job."""
        from odie.watch import report as watch_report
        card = store.get_setting(watch_report.CARD) or {}
        before = len(card.get("needs_you", []))
        card["needs_you"] = [i for i in card.get("needs_you", []) if i.get("ref") != f"job:{job_id}"]
        store.set_setting(watch_report.CARD, card)
        return {"forgotten": job_id} if len(card["needs_you"]) < before else {"error": f"{job_id} has no card on Today."}

    async def ask_bot(bot: str, title: str, request: str, every_minutes: int = 0, until: str = "", notify: str = "always",
                      condition: str = "", tool_context: ToolContext = None) -> dict:
        """Hand the user's request to one of their bots, which works on it in the background and reports into this chat. Use it when the user names a bot ("@chief …", "ask the researcher to …"), or asks for the team or the chief. The chief leads the team: it splits a big question among specialists it makes, runs them side by side and gives one answer; send it anything that needs research from several sides, a comparison, or checking. bot: its name, without the @. title: a few words the user will recognise. request: the user's request in full, with everything the bot needs (it sees nothing else of this chat). For something that should run for good on a schedule ("every morning at 8"), use make_routine instead. For a short watch that ends: every_minutes, until (a local date-time; left out: 24 hours, at most 7 days), notify ("always", "change": only when the facts changed, or "condition": only when `condition` holds). Tell the user it started and that the answer will come here."""
        from odie.workers import bots
        name = bots.clean_name(bot)
        found = bots.get(store, name) if name else None
        if found is None:
            names = ", ".join(b.name for b in bots.all_bots(store))
            return {"error": f"There's no bot called {bot}. The bots: {names}."}
        from odie.workers import convs, privacy
        session_id = session_id_of(tool_context)
        shown_title = title.strip()[:80] or found.name
        conv_id = convs.make(store, found.name, shown_title, origin="chat")  # the bot's own history has it too
        convs.add(store, conv_id, "user", request.strip())
        job = router.start_bot(found.name, shown_title, request.strip(), session_id,
                               every_minutes=int(every_minutes or 0), until_at=until_in_users_time(until),
                               notify=notify.strip().lower(), condition=condition.strip(),
                               private=privacy.of_this_turn(store, session_id), conv_id=conv_id)
        out = {"job_id": job.id, "bot": found.name, "status": "started", "media": team_card(job.id, found.name)}
        if job.repeats:
            out["repeats"] = f"every {job.every_minutes} minutes until {job.until_at}, telling you: {job.notify}"
        return out

    async def make_routine(bot: str, title: str, request: str, when: str, tool_context: ToolContext = None) -> dict:
        """Set up a bot to do something by itself on a schedule (until the user pauses or deletes it, or the words end it): "every morning at 8, @researcher …", "every weekday at 9:15 give me a market note", "every 3 hours check …". bot: its name. title: a few words ("Morning market note"). request: what to do each time, in full (it sees nothing else of this chat; each run also sees its own earlier runs). when: the user's timing in plain words, as they said it: "weekdays at 9:15 and 6pm", "every 30 minutes from 9 to 6", "every 2 hours on weekends", "1st and 15th at 9", "last Friday of the month at 5pm", "tomorrow 3pm", "every day at 8 until 30 Nov", "every day at 8 for 2 weeks". If the answer is an error, it says what wasn't understood: say it another way. Each run answers in the routine's own conversation with a push; tell the user when it runs (the "when" in the answer) and the next run. For a short watch that should end within hours ("until the match ends") use ask_bot with every_minutes instead."""
        from odie.workers import bots, routines
        name = bots.clean_name(bot)
        if not name or bots.get(store, name) is None:
            return {"error": f"There's no bot called {bot}."}
        got = routines.make(store, name, title, request, words=when)
        if isinstance(got, str):
            return {"error": got}
        from odie.workers import privacy  # what this chat read goes with the request, into every run
        privacy.carry(store, got["conv_id"], *privacy.of_this_turn(store, session_id_of(tool_context)))
        return {"routine": got["id"], "bot": name, "when": got["when"], "next_run_utc": got["next_run_at"]}

    return [FunctionTool(start_job), FunctionTool(jobs_status), FunctionTool(stop_job), FunctionTool(retry_job),
            FunctionTool(forget_job), FunctionTool(ask_bot), FunctionTool(make_routine)]
