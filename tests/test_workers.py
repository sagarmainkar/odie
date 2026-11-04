"""Workers (odie.workers): a job the chat hands to a background Worker, through the real ADK with a stand-in model.
The Worker gets only its kind's tools and the report tool; the shell runs without a tap but the pass's always-ask
rules refuse what they would stop in chat; every call is a row in job_actions; the chat gets one message at the end."""
from __future__ import annotations

import asyncio
from typing import ClassVar

import pytest
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from odie.store.db import Store
from odie.workers import router, worker
from odie.workers import store as jobs


class Chat:
    """Stands in for the runner: keeps every post_message call."""

    def __init__(self):
        self.posts = []

    async def post_message(self, text, session_id=None, media=None, kind="system"):
        self.posts.append({"text": text, "session_id": session_id, "media": media, "kind": kind})


class Scripted(BaseLlm):
    """Plays a script of replies: each is a tool call (name, args) or a text. Records every request."""
    script: ClassVar[list] = []
    seen: ClassVar[list] = []
    stall: ClassVar[bool] = False

    async def generate_content_async(self, llm_request, stream: bool = False):
        Scripted.seen.append(llm_request)
        if Scripted.stall:
            await asyncio.sleep(30)
        step = Scripted.script.pop(0) if Scripted.script else "done"
        if isinstance(step, str):
            part = types.Part(text=step)
        else:
            name, args = step
            part = types.Part(function_call=types.FunctionCall(id=f"call-{len(Scripted.seen)}", name=name, args=args))
        yield LlmResponse(content=types.Content(role="model", parts=[part]))


@pytest.fixture
def world(isolated_settings, tmp_path, monkeypatch):
    """A store with the workers' tables, a chat to post to, no pushes, a scripted model."""
    store = Store(tmp_path / "assistant.db")
    store.init_schema()
    jobs.ensure(store)
    chat = Chat()
    pushes = []
    monkeypatch.setattr(worker, "send_to_all", lambda store, title, body, url="/", tag=None: pushes.append((title, body, tag)))
    monkeypatch.setattr(worker, "model_for_kind", lambda store, kind: Scripted(model="scripted"))
    Scripted.script = []
    Scripted.seen = []
    Scripted.stall = False
    router.hooks.update(store=store, runner=chat)
    return store, chat, pushes


def a_job(store, tmp_path, title="Tides", budget=60):
    folder = tmp_path / "jobs" / "tides"
    folder.mkdir(parents=True)
    return jobs.create(store, "task", title, "Say hello from the shell, then report.", "chat-1", folder, budget)


# ── the record ───────────────────────────────────────────────────────────────

def test_the_tables_keep_a_job_from_start_to_end(world, tmp_path):
    store, _, _ = world
    job = a_job(store, tmp_path)
    assert job.id.startswith("job-") and jobs.get(store, job.id)["status"] == "queued"
    jobs.started(store, job.id)
    assert jobs.running(store)[0]["runs"] == 1
    jobs.record_action(store, job.id, "run_shell", {"command": "ls"}, result_chars=12)
    jobs.ended(store, job.id, "done", outcome="ready", report="hello")
    row = jobs.get(store, job.id)
    assert (row["status"], row["outcome"], row["report"]) == ("done", "ready", "hello")
    assert [a["tool"] for a in jobs.actions(store, job.id)] == ["run_shell"]
    assert jobs.running(store) == []
    jobs.ensure(store)  # again: nothing lost
    assert jobs.get(store, job.id)["report"] == "hello"


# ── the guard ────────────────────────────────────────────────────────────────

class Tool:
    def __init__(self, name):
        self.name = name


def test_the_guard_puts_the_shell_in_the_jobs_folder_and_refuses_what_the_pass_would(world, tmp_path):
    store, _, _ = world
    job = a_job(store, tmp_path)
    guard = worker.guard_for(store, job)
    args = {"command": "echo hi"}
    assert guard(Tool("run_shell"), args, None) is None
    assert args["cwd"] == str(job.folder)  # the Worker's commands start in its own folder
    assert guard(Tool("run_shell"), {"command": "echo x > notes.txt", "cwd": str(job.folder)}, None) is None  # its folder is a safe place
    bad = {"command": "rm old.txt", "cwd": str(job.folder)}
    refused = guard(Tool("run_shell"), bad, None)
    assert refused == {"error": "Not run: it deletes or stops something. Write files with write_file; find another way, or report it as blocked."}
    assert guard(Tool("web_search"), {"query": "tides"}, None) is None
    worker.after_for(store, job)(Tool("run_shell"), bad, None, refused)  # ADK calls after even for a refused call
    worker.after_for(store, job)(Tool("web_search"), {"query": "tides"}, None, {"results": []})
    recorded = jobs.actions(store, job.id)
    assert [(a["tool"], a["refused"], a["result_chars"]) for a in recorded] == [
        ("run_shell", "deletes or stops something", None), ("web_search", None, 15)]  # the refusal once, not twice


# ── a run, end to end ────────────────────────────────────────────────────────

async def test_a_worker_runs_the_shell_in_its_folder_reports_and_the_chat_hears_once(world, tmp_path):
    store, chat, pushes = world
    job = a_job(store, tmp_path)
    Scripted.script = [("run_shell", {"command": "echo hello && pwd"}),
                       ("report", {"outcome": "ready", "text": "The shell says hello."})]
    status = await worker.run(job, store, chat, model=Scripted(model="scripted"))
    assert status == "done"
    row = jobs.get(store, job.id)
    assert (row["status"], row["outcome"], row["report"], row["runs"]) == ("done", "ready", "The shell says hello.", 1)
    acted = jobs.actions(store, job.id)
    assert [a["tool"] for a in acted] == ["run_shell", "report"]
    assert acted[0]["result_chars"] > 0 and acted[0]["refused"] is None
    assert chat.posts == [{"text": f"✅ Task done: Tides ({job.id})\n\nThe shell says hello.", "session_id": "chat-1",
                           "media": None, "kind": "job"}]
    assert pushes[0][2] == job.id
    # the model saw only the kind's tools and report, and only the kind's instruction
    first = Scripted.seen[0]
    names = sorted(f.name for t in first.config.tools for f in t.function_declarations)
    assert names == ["read_file", "report", "run_shell", "web_fetch", "web_search", "write_file"]
    assert str(first.config.system_instruction).startswith("You are a Worker")
    assert str(job.folder) in str(first.config.system_instruction)
    # the shell ran in the job's folder (its answer, in the tool result the model got next)
    second = Scripted.seen[1]
    results = [p.function_response.response for c in second.contents for p in c.parts or [] if p.function_response]
    assert str(job.folder) in str(results[0])


async def test_a_worker_that_stops_without_a_report_is_nudged_once_then_fails(world, tmp_path):
    store, chat, _ = world
    job = a_job(store, tmp_path)
    Scripted.script = ["I think that's it.", "Yes, done."]
    status = await worker.run(job, store, chat, model=Scripted(model="scripted"))
    assert status == "failed"
    assert len(Scripted.seen) == 2  # the brief, then the nudge, then no more
    assert "Call report now" in Scripted.seen[1].contents[-1].parts[0].text
    assert jobs.get(store, job.id)["error"] == "stopped without a report"
    assert chat.posts[0]["text"] == f"❌ Tides didn't finish ({job.id}): stopped without a report"


async def test_a_worker_past_its_budget_is_stopped_and_the_job_fails(world, tmp_path):
    store, chat, _ = world
    job = a_job(store, tmp_path, budget=1)
    Scripted.stall = True
    status = await worker.run(job, store, chat, model=Scripted(model="scripted"))
    assert status == "failed"
    assert jobs.get(store, job.id)["error"] == "ran past its budget of 1 seconds"
    assert chat.posts[0]["text"].startswith("❌ Tides didn't finish")


async def test_a_blocked_report_reads_as_stuck_and_files_in_the_folder_ride_along(world, tmp_path):
    store, chat, _ = world
    job = a_job(store, tmp_path)
    (job.folder / "notes.txt").write_text("the notes")
    Scripted.script = [("report", {"outcome": "blocked", "text": "Need the API key.", "files": ["notes.txt", "/etc/hosts"]})]
    await worker.run(job, store, chat, model=Scripted(model="scripted"))
    post = chat.posts[0]
    assert post["text"] == f"⛔ Tides is stuck ({job.id})\n\nNeed the API key."
    assert [m["filename"] for m in post["media"]] == ["notes.txt"]  # /etc/hosts is outside the folder: left out


async def test_write_file_and_read_file_stay_inside_the_jobs_folder(world, tmp_path):
    store, _, _ = world
    job = a_job(store, tmp_path)
    from odie.workers.files import make_job_file_tools
    write_file, read_file = make_job_file_tools(job.folder)
    assert (await write_file.func("src/fib.py", "print(1)\n"))["bytes"] == 9
    assert (job.folder / "src" / "fib.py").read_text() == "print(1)\n"
    assert (await read_file.func("src/fib.py"))["text"] == "print(1)\n"
    assert "error" in await write_file.func("../escape.txt", "x")
    assert "error" in await write_file.func("/etc/hosts", "x")
    assert "error" in await read_file.func("missing.txt")
    assert not (tmp_path / "escape.txt").exists()


def test_budget_words():
    assert worker.budget_words(1800) == "30 minutes"
    assert worker.budget_words(60) == "1 minute"
    assert worker.budget_words(90) == "90 seconds"


# ── the router ───────────────────────────────────────────────────────────────

async def test_the_router_starts_a_job_in_its_own_folder_and_runs_it(world, monkeypatch):
    store, chat, _ = world
    Scripted.script = [("report", {"outcome": "ready", "text": "ok"})]
    job = router.start("task", "Tides report!", "Do it.", "chat-9")
    assert job.folder.is_dir() and job.folder.name.startswith("tides-report-")
    for _ in range(200):
        if jobs.get(store, job.id)["status"] == "done":
            break
        await asyncio.sleep(0.02)
    assert jobs.get(store, job.id)["status"] == "done"
    assert chat.posts[0]["session_id"] == "chat-9"


async def test_stop_cancels_a_running_job_and_marks_it_stopped(world):
    store, chat, _ = world
    Scripted.stall = True
    job = router.start("task", "Long one", "Take forever.", "chat-9")
    await asyncio.sleep(0.05)
    assert job.id in router.running_ids()
    assert router.stop(job.id) is True
    await asyncio.sleep(0.05)
    assert jobs.get(store, job.id)["status"] == "stopped"
    assert router.stop(job.id) is False
    assert chat.posts == []  # a stop says nothing in the chat: the user asked for it


# ── the switch ───────────────────────────────────────────────────────────────

def test_off_by_default_the_chat_has_no_worker_tools(world, monkeypatch):
    store, _, _ = world
    from odie.agent.agent import build_agent
    monkeypatch.delenv("ODIE_WORKERS", raising=False)
    assert "start_job" not in {t.name for t in build_agent(store).tools if hasattr(t, "name")}
    monkeypatch.setenv("ODIE_WORKERS", "1")
    names = {t.name for t in build_agent(store).tools if hasattr(t, "name")}
    assert {"start_job", "jobs_status", "stop_job"} <= names


async def test_start_job_from_the_chat_names_the_chat_it_came_from(world):
    store, _, _ = world
    from odie.workers.tools import make_worker_tools
    Scripted.script = [("report", {"outcome": "ready", "text": "ok"})]
    start_job, jobs_status, stop_job = make_worker_tools(store)

    class Ctx:
        class session:
            id = "chat-42"
    got = await start_job.func("Tides", "Do it.", tool_context=Ctx())
    assert got["status"] == "started"
    assert jobs.get(store, got["job_id"])["session_id"] == "chat-42"
    for _ in range(200):
        if jobs.get(store, got["job_id"])["status"] == "done":
            break
        await asyncio.sleep(0.02)
    status = await jobs_status.func()
    assert status["running"] == [] and status["recent"][0].startswith(got["job_id"])
    assert await stop_job.func(got["job_id"]) == {"error": f"{got['job_id']} isn't running."}


# ── the nudge ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text, expected", [
    ("Write a Python script that prints the first 20 primes and run it", True),
    ("Can you test the new parser and fix what breaks?", True),
    ("Check this Mac's disk and memory and tell me", True),
    ("Track the HN front page and report every hour", True),
    ("Do this in the background: tidy the downloads folder", True),
    ("How is the market today?", False),
    ("What does this script do?", False),
    ("Remind me to run the tests at 5", False),
    ("Make me a deck about tides", False),
    ("ls ~/Downloads", False),
])
def test_looks_like_a_job(text, expected):
    from odie.workers.nudge import looks_like_a_job
    assert looks_like_a_job(text) is expected


def test_the_job_nudge_rides_on_the_turn_only_with_workers_on(world, monkeypatch, tmp_path):
    store, _, _ = world
    from odie.app.runner import OdieRunner
    from odie.workers.nudge import NUDGE
    r = OdieRunner.__new__(OdieRunner)
    r.store = store
    monkeypatch.delenv("ODIE_WORKERS", raising=False)
    assert r._job_nudge("chat-1", "Write a script that sorts my photos and run it") == ""
    monkeypatch.setenv("ODIE_WORKERS", "1")
    assert r._job_nudge("chat-1", "Write a script that sorts my photos and run it") == "\n" + NUDGE
    assert r._job_nudge("chat-1", "How is the market today?") == ""
