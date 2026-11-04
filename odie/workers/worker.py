"""One Worker run: an agent of its own on one job, from the brief to the report, and the message the chat gets.

The Worker sees only its kind's instruction, its kind's tools and the report tool, in a fresh in-memory session: no
Odie prompt, no memory, no chat history. Three callbacks keep the record and the fences:
- the guard (before each tool): a shell command outside the user's pass is refused with a line and recorded;
- after each tool: the call and the size of its answer are recorded;
- on a tool error: the error is recorded and handed to the model as the tool's answer, so it can try again.
The run ends when the Worker calls report, or when it stops without one (one nudge, then the job fails), runs past
its budget, or raises."""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from google.adk.agents import LlmAgent
from google.adk.agents.run_config import RunConfig
from google.adk.apps import App
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools import FunctionTool
from google.genai import types

from odie import config, persona
from odie.push.send import send_to_all
from odie.store.db import Store
from odie.workers import store as jobs
from odie.workers.kinds import KINDS, WorkerKind
from odie.workers.store import OUTCOMES, Job

log = logging.getLogger("odie.workers")

NUDGE = "You stopped without calling report. Call report now with what you did and what you found."
REPORT_LIMIT = 4000  # characters of a report kept and posted


@dataclass
class Report:
    """What the Worker said in report, once it has: outcome, text and the files it points at."""
    outcome: str = ""
    text: str = ""
    files: list[str] = field(default_factory=list)

    def given(self) -> bool:
        return bool(self.outcome)


def make_report_tool(got: Report) -> FunctionTool:
    def report(outcome: str, text: str, files: list[str] | None = None) -> dict:
        """Finish the job. Call it once, at the end. outcome: "ready" (the result is here, or the work is done), "blocked" (you can't finish without the user: say what you need), or "dropped" (there was nothing to do: say why). text: the report, short and plain. files: paths of files in your folder the user should get."""
        got.outcome = outcome if outcome in OUTCOMES else "ready"
        got.text = (text or "").strip()[:REPORT_LIMIT]
        got.files = [str(f) for f in (files or []) if f]
        return {"ok": True}
    return FunctionTool(report)


def guard_for(store: Store, job: Job):
    """before_tool_callback: decides whether a Worker's call runs, and sets the shell's folder.
    - run_shell with no cwd -> cwd becomes the job's folder, then runs.
    - run_shell that the pass's always-ask rules would stop (`rm old.txt`, `cat ~/.env`, `curl ... | sh`) -> refused
      with the rule's words, recorded with refused=<why>; the Worker is told to find another way or report blocked.
    - any other tool -> runs."""
    from odie.agent.shell_grant import always_ask, safe_places

    def guard(tool, args, tool_context) -> dict | None:
        if tool.name != "run_shell":
            return None
        args = args if args is not None else {}
        if not args.get("cwd"):
            args["cwd"] = str(job.folder)
        places = (*safe_places(store), str(job.folder))
        why = always_ask(str(args.get("command") or ""), safe_dirs=places, cwd=args.get("cwd"))
        if why is None:
            return None
        jobs.record_action(store, job.id, tool.name, args, refused=why)
        return {"error": f"Not run: it {why}. Find another way, or report it as blocked."}
    return guard


def after_for(store: Store, job: Job):
    """after_tool_callback: every call that ran goes on the record with the size of its answer."""
    def after(tool, args, tool_context, tool_response):
        jobs.record_action(store, job.id, tool.name, args, result_chars=len(json.dumps(tool_response, default=str)))
    return after


def on_error_for(store: Store, job: Job):
    """on_tool_error_callback: a tool that raised is recorded, and the model sees the error as the tool's answer."""
    from odie.app.runner import tool_error_as_result

    def on_error(tool, args, tool_context, error: Exception) -> dict:
        shown = tool_error_as_result(tool, args, tool_context, error)
        jobs.record_action(store, job.id, tool.name, args, error=shown["error"])
        return shown
    return on_error


def budget_words(seconds: int) -> str:
    """A budget in words: 1800 -> "30 minutes"; 90 -> "90 seconds"; 60 -> "1 minute"."""
    if seconds % 60 == 0 and seconds >= 60:
        minutes = seconds // 60
        return f"{minutes} minute" + ("" if minutes == 1 else "s")
    return f"{seconds} seconds"


def media_for(job: Job, files: list[str]) -> list[dict]:
    """The report's files as cards under the message: only files that exist under the job's folder or the workspace
    are handed over; anything else is left out."""
    from odie.agent.tools.files import hand_over, workspace
    ws = workspace().resolve()
    out = []
    for name in files:
        f = Path(name)
        if not f.is_absolute():
            f = job.folder / f
        f = f.resolve()
        inside = ws in f.parents or job.folder.resolve() in f.parents
        if f.is_file() and inside:
            out.append(hand_over(f, f.name)["media"])
    return out


def message_for(kind: WorkerKind, job: Job, status: str, got: Report, error: str) -> str:
    """The one message the chat gets when a job ends. Examples:
    done/ready -> "✅ Task done: Tides (job-3f9a2c)\n\n<report>"; done/blocked -> "⛔ Tides is stuck (…)\n\n<report>";
    failed -> "❌ Tides didn't finish (job-3f9a2c): ran past its budget of 30 minutes"."""
    if status == "failed":
        return f"❌ {job.title} didn't finish ({job.id}): {error}"
    if got.outcome == "blocked":
        return f"⛔ {job.title} is stuck ({job.id})\n\n{got.text}"
    if got.outcome == "dropped":
        return f"➖ {job.title}: nothing to do ({job.id})\n\n{got.text}"
    return f"✅ {kind.word.capitalize()} done: {job.title} ({job.id})\n\n{got.text}"


async def tell(store: Store, runner, job: Job, text: str, media: list[dict]) -> None:
    """Post the message into the job's chat and push it to the phone. A failed push never loses the post."""
    await runner.post_message(text, job.session_id, media=media or None, kind="job")
    try:
        send_to_all(store, persona.get(store)["name"], text[:160], url="/#chat", tag=job.id)
    except Exception:  # noqa: BLE001
        log.warning("push failed for %s", job.id, exc_info=True)


def model_for_kind(store: Store, kind: WorkerKind):
    """The ADK model a kind's Worker runs on: the model chosen for the kind's slot ("chat" is the user's chat model)."""
    from odie.agent.model import model_for
    from odie.models import resolve_selection
    return model_for(resolve_selection(store, kind.model_slot), False)


async def run(job: Job, store: Store, runner, kind: WorkerKind | None = None, model=None) -> str:
    """Run the Worker on the job to its end and tell the chat. Returns the job's final status.
    model: a test's stand-in BaseLlm; otherwise the kind's chosen model (model_for_kind)."""
    from google.adk.agents.invocation_context import LlmCallsLimitExceededError
    kind = kind or KINDS[job.kind]
    s = config.settings
    if model is None:
        model = model_for_kind(store, kind)
    tz = ZoneInfo(s.timezone)
    now = datetime.now(tz).strftime("%A %d %B %Y, %H:%M")
    got = Report()
    instruction = kind.instruction.format(folder=job.folder)

    def as_written(_context) -> str:
        return instruction  # a function, so ADK passes the text on untouched (a brace in a path would otherwise be read as state)

    agent = LlmAgent(name="odie_worker", model=model, tools=[*kind.tools(store, job), make_report_tool(got)],
                     instruction=as_written, before_tool_callback=guard_for(store, job),
                     after_tool_callback=after_for(store, job), on_tool_error_callback=on_error_for(store, job))
    sessions = InMemorySessionService()
    sess = await sessions.create_session(app_name="odie_worker", user_id=s.user_id, session_id=job.id)
    adk = Runner(app=App(name="odie_worker", root_agent=agent), session_service=sessions)
    capped = RunConfig(max_llm_calls=kind.max_llm_calls)

    async def send(text: str) -> None:
        message = types.Content(role="user", parts=[types.Part(text=text)])
        async for _ in adk.run_async(user_id=s.user_id, session_id=sess.id, new_message=message, run_config=capped):
            pass

    async def go() -> None:
        await send(f"It is {now} ({s.timezone}). Your job, '{job.title}':\n\n{job.brief}")
        if not got.given():
            await send(NUDGE)

    jobs.started(store, job.id)
    error = ""
    try:
        await asyncio.wait_for(go(), job.budget_seconds)
    except TimeoutError:
        error = f"ran past its budget of {budget_words(job.budget_seconds)}"
    except LlmCallsLimitExceededError:
        error = "went round in circles (too many model calls)"
    except Exception as e:  # noqa: BLE001 (whatever went wrong is said in the chat, never lost)
        log.warning("worker %s failed", job.id, exc_info=True)
        error = f"{type(e).__name__}: {e}"[:200]
    if not error and not got.given():
        error = "stopped without a report"
    status = "failed" if error else "done"
    jobs.ended(store, job.id, status, outcome=got.outcome or None, report=got.text or None, error=error or None)
    media = media_for(job, got.files) if status == "done" else []
    await tell(store, runner, job, message_for(kind, job, status, got, error), media)
    return status
