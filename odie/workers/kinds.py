"""The kinds of Worker. A kind fixes what a Worker may do before it reads anything: its tools, its instruction, its
budget. Nothing a Worker reads later can widen that. In this step there is one kind, task: shell, files and web reads,
for coding, testing and system checks. Later steps add reporter (a schedule and a report each time) and mail (may
send, has no shell, recipients fixed when the job starts)."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from odie.store.db import Store
from odie.workers.store import Job

TASK_INSTRUCTION = """You are a Worker: one background job for the user, unattended. Nobody reads along and nobody \
answers questions, so decide for yourself and keep going.

- Work in your own folder, {folder}; run_shell starts there. Write every file with write_file and read with \
read_file; the shell is for running things. Leave the rest of the computer as you found it unless the job says otherwise.
- A command the rules refuse is not run; the answer says why. Don't retry it in another form: find another way (a \
file through write_file, say), or report it as blocked.
- Verify before you say something works: run it, read the output.
- Finish by calling report, once, with what you did and what you found. Keep the text short, in plain words: a result \
the user can use or a clear question they must answer. Never stop without calling report."""


@dataclass
class WorkerKind:
    """name: the kind's name, what start_job is called with ("task").
    word: how the chat names a job of this kind ("task" -> "The task 'Tides' is done.").
    instruction: the Worker's whole system prompt; {folder} is filled with the job's folder.
    tools(store, job): the tools the Worker gets, besides report. Fixed by the kind, never by the job.
    budget_seconds: wall time the Worker gets before it is stopped and the job fails.
    max_llm_calls: model calls one message may lead to (a model looping on a tool runs out and the job fails).
    model_slot: which chosen model runs it (odie.models.resolve_selection's slot); "chat" is the user's chat model."""
    name: str
    word: str
    instruction: str
    tools: Callable[[Store, Job], list]
    budget_seconds: int = 30 * 60
    max_llm_calls: int = 80
    model_slot: str = "chat"


def task_tools(store: Store, job: Job) -> list:
    """The task kind's tools: the shell without the tap (the guard applies the pass's always-ask rules instead and
    refuses with a line), write_file and read_file in the job's folder, and web search and fetch. No mail, no browser,
    no memory."""
    from odie.agent.free import unlocked
    from odie.agent.tools.shell import make_shell_tool
    from odie.agent.tools.web import make_web_tools
    from odie.workers.files import make_job_file_tools
    shell = unlocked(make_shell_tool(store=store))
    return [shell, *make_job_file_tools(job.folder), *make_web_tools(store=store, browser_for=None, ask_first=False)]


REPORTER_INSTRUCTION = """You are a Worker that checks on something for the user on a schedule, unattended. This is one \
run; the same job runs again later in a fresh session, so nothing you remember survives except what you write down.

- Work in your own folder, {folder}; run_shell starts there. Keep what the next run needs (numbers seen, what was \
already said) in notes.md with write_file; read it first with read_file.
- Do the check the brief asks for. Compare with your last report, given below when there is one. Say what changed and \
what matters; when nothing changed, say so in one line.
- A command the rules refuse is not run; the answer says why. Find another way, or report it as blocked.
- Finish by calling report, once: short, plain words. Never stop without calling report."""


TASK = WorkerKind(name="task", word="task", instruction=TASK_INSTRUCTION, tools=task_tools)
# The reporter runs again every so often (the Router keeps the schedule); each run is short.
REPORTER = WorkerKind(name="reporter", word="report", instruction=REPORTER_INSTRUCTION, tools=task_tools,
                      budget_seconds=10 * 60, max_llm_calls=40)

KINDS: dict[str, WorkerKind] = {TASK.name: TASK, REPORTER.name: REPORTER}
