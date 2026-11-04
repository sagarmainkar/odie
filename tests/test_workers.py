"""Workers (odie.workers): a job the chat hands to a background Worker, through the real ADK with a stand-in model.
The Worker gets only its kind's tools and the report tool; the shell runs without a tap but the pass's always-ask
rules refuse what they would stop in chat; every call is a row in job_actions; the chat gets one message at the end."""
from __future__ import annotations

import asyncio
from pathlib import Path
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
    assert jobs.started(store, job) == 1
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
    assert {"start_job", "jobs_status", "stop_job", "retry_job", "forget_job"} <= names


async def test_start_job_from_the_chat_names_the_chat_it_came_from(world):
    store, _, _ = world
    from odie.workers.tools import make_worker_tools
    Scripted.script = [("report", {"outcome": "ready", "text": "ok"})]
    start_job, jobs_status, stop_job, _, _ = make_worker_tools(store)

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


# ── reporters ────────────────────────────────────────────────────────────────

def test_until_for_caps_and_defaults():
    from datetime import UTC, datetime
    now = datetime(2026, 11, 4, 10, 0, tzinfo=UTC)
    assert router.until_for(0, None, now) is None
    assert router.until_for(60, None, now) == "2026-11-05T10:00:00+00:00"  # 24 hours
    assert router.until_for(60, "2026-11-04T18:00:00+00:00", now) == "2026-11-04T18:00:00+00:00"
    assert router.until_for(60, "2026-12-01T00:00:00+00:00", now) == "2026-11-11T10:00:00+00:00"  # 7 days at most
    assert router.until_for(60, "not a time", now) == "2026-11-05T10:00:00+00:00"


async def test_a_reporter_runs_again_sees_its_last_report_and_finishes(world, monkeypatch):
    from datetime import UTC, datetime, timedelta
    store, chat, _ = world
    clock = {"now": datetime(2026, 11, 4, 10, 0, tzinfo=UTC)}
    monkeypatch.setattr(router, "now_utc", lambda: clock["now"])

    async def no_wait(seconds):
        clock["now"] += timedelta(seconds=seconds)
    monkeypatch.setattr(router, "sleep", no_wait)
    Scripted.script = [("report", {"outcome": "ready", "text": "Front page: 3 new posts."}), "Done.",
                       ("report", {"outcome": "ready", "text": "Nothing changed."}), "Done."]
    job = router.start("task", "HN front page", "Check news.ycombinator.com.", "chat-1", every_minutes=60,
                       until_at="2026-11-04T11:30:00+00:00")
    assert job.kind == "reporter" and job.repeats
    for _ in range(300):
        if jobs.get(store, job.id)["status"] == "done":
            break
        await asyncio.sleep(0.01)
    row = jobs.get(store, job.id)
    assert (row["status"], row["runs"], row["report"]) == ("done", 2, "Nothing changed.")
    texts = [p["text"] for p in chat.posts]
    assert texts[0] == f"🔁 Report 1: HN front page ({job.id})\n\nFront page: 3 new posts."
    assert texts[1] == f"🔁 Report 2: HN front page ({job.id})\n\nNothing changed."
    assert texts[2] == f"🔁 HN front page ({job.id}) finished after 2 reports."
    # the second run was told the first run's report; the first run was told nothing of the kind
    first_prompt = Scripted.seen[0].contents[0].parts[0].text
    second_prompt = Scripted.seen[2].contents[0].parts[0].text
    assert "Your last report" not in first_prompt
    assert "This is run 2. Your last report:\nFront page: 3 new posts." in second_prompt
    assert str(Scripted.seen[2].config.system_instruction).startswith("You are a Worker that checks")


async def test_a_reporter_waiting_between_runs_can_be_stopped(world, monkeypatch):
    store, chat, _ = world
    Scripted.script = [("report", {"outcome": "ready", "text": "First look."})]
    job = router.start("task", "Disk", "Check disk.", "chat-1", every_minutes=5)
    for _ in range(300):
        if jobs.get(store, job.id)["status"] == "waiting":
            break
        await asyncio.sleep(0.01)
    row = jobs.get(store, job.id)
    assert row["status"] == "waiting" and row["next_run_at"] is not None
    assert jobs.running(store)[0]["id"] == job.id  # still on the running list while it waits
    assert router.stop(job.id) is True
    await asyncio.sleep(0.05)
    assert jobs.get(store, job.id)["status"] == "stopped"
    assert len(chat.posts) == 1  # the one report; a stop says nothing


async def test_start_job_with_every_minutes_makes_a_reporter_in_the_users_time(world, monkeypatch):
    store, _, _ = world
    from odie.workers.tools import make_worker_tools
    start_job, _, stop_job, _, _ = make_worker_tools(store)
    Scripted.stall = True
    got = await start_job.func("Mail count", "Count unread.", every_minutes=30, until="2026-11-04T18:00")
    row = jobs.get(store, got["job_id"])
    assert row["kind"] == "reporter" and row["every_minutes"] == 30
    assert row["until_at"] == "2026-11-04T18:00:00+05:30"  # Asia/Kolkata, the tests' timezone
    assert got["repeats"] == "every 30 minutes until 2026-11-04T18:00:00+05:30, telling you: always"
    assert await stop_job.func(got["job_id"]) == {"stopped": got["job_id"]}


# ── the watchdog, retry and recovery ─────────────────────────────────────────

def _row(**over):
    base = {"id": "job-1", "status": "running", "budget_seconds": 1800, "started_at": "2026-11-04T10:00:00.000Z",
            "next_run_at": None, "every_minutes": 0}
    return {**base, **over}


def test_why_stuck_reads_budget_stall_and_repeated_errors():
    from datetime import UTC, datetime

    from odie.workers import watchdog
    at = lambda h, m: datetime(2026, 11, 4, h, m, tzinfo=UTC)  # noqa: E731
    act = lambda h, m, **k: {"ts": f"2026-11-04T{h:02d}:{m:02d}:00.000Z", "refused": None, "error": None, **k}  # noqa: E731
    assert watchdog.why_stuck(_row(), [act(10, 1)], at(10, 2)) is None
    assert watchdog.why_stuck(_row(), [act(10, 1)], at(10, 12)) == "made no progress for 10 minutes"
    assert watchdog.why_stuck(_row(), [], at(10, 11)) == "made no progress for 10 minutes"  # no call since the start
    assert watchdog.why_stuck(_row(), [act(10, 39)], at(10, 40)) == "ran past its budget and didn't stop"
    same = [act(10, 1, refused="deletes or stops something") for _ in range(3)]
    assert watchdog.why_stuck(_row(), same, at(10, 2)) == "hit the same refusal 3 times: deletes or stops something"
    mixed = [act(10, 1, refused="x"), act(10, 1, refused="y"), act(10, 1, refused="x")]
    assert watchdog.why_stuck(_row(), mixed, at(10, 2)) is None


def test_missed_run_waits_for_the_grace():
    from datetime import UTC, datetime

    from odie.workers import watchdog
    waiting = _row(status="waiting", next_run_at="2026-11-04T10:00:00+00:00", every_minutes=60)
    assert watchdog.missed_run(waiting, datetime(2026, 11, 4, 10, 3, tzinfo=UTC)) is False
    assert watchdog.missed_run(waiting, datetime(2026, 11, 4, 10, 7, tzinfo=UTC)) is True
    assert watchdog.missed_run(_row(), datetime(2026, 11, 4, 12, 0, tzinfo=UTC)) is False


async def test_the_watchdog_fails_a_stalled_job_and_tells_the_chat(world, monkeypatch):
    from datetime import UTC, datetime, timedelta

    from odie.workers import watchdog
    store, chat, _ = world
    Scripted.stall = True
    job = router.start("task", "Slow one", "Take forever.", "chat-1")
    await asyncio.sleep(0.05)
    later = datetime.now(UTC) + timedelta(minutes=11)
    done = await watchdog.check(store, later)
    assert done == [f"{job.id}: failed, made no progress for 10 minutes"]
    await asyncio.sleep(0.05)
    row = jobs.get(store, job.id)
    assert (row["status"], row["error"]) == ("failed", "made no progress for 10 minutes")
    assert job.id not in router.running_ids()
    assert chat.posts[-1]["text"] == f'❌ Slow one didn\'t finish ({job.id}): made no progress for 10 minutes. Say "retry {job.id}" to start it again.'
    assert await watchdog.check(store, later) == []  # nothing left to do


async def test_retry_runs_a_failed_job_again_in_the_same_folder(world):
    store, _, _ = world
    Scripted.script = ["I give up.", "Really."]  # no report: fails
    job = router.start("task", "Flaky", "Try.", "chat-1")
    for _ in range(300):
        if jobs.get(store, job.id)["status"] == "failed":
            break
        await asyncio.sleep(0.01)
    Scripted.script = [("report", {"outcome": "ready", "text": "Second time lucky."})]
    again = router.retry(job.id)
    assert again is not None and again.folder == job.folder
    for _ in range(300):
        if jobs.get(store, job.id)["status"] == "done":
            break
        await asyncio.sleep(0.01)
    row = jobs.get(store, job.id)
    assert (row["status"], row["runs"], row["report"], row["error"]) == ("done", 2, "Second time lucky.", None)
    assert router.retry(job.id) is None  # done: nothing to retry
    assert router.retry("job-nothere") is None


async def test_recover_after_a_restart_tells_cut_off_jobs_and_relaunches_reporters(world, monkeypatch):
    store, chat, _ = world
    # rows as a restart finds them: a plain job that was running, a reporter waiting for a run far ahead
    cut = jobs.create(store, "task", "Cut off", "…", "chat-1", store.path.parent / "a", 60)
    jobs.started(store, cut)
    rep = jobs.create(store, "reporter", "Hourly", "…", "chat-1", store.path.parent / "b", 60, every_minutes=60,
                      until_at="2099-01-01T00:00:00+00:00")
    jobs.started(store, rep)
    jobs.waiting(store, rep.id, "2099-01-01T00:00:00+00:00")
    slept = []

    async def record(seconds):
        slept.append(seconds)
        await asyncio.sleep(3600)
    monkeypatch.setattr(router, "sleep", record)
    lines = await router.recover()
    await asyncio.sleep(0.05)
    assert lines == [f"{cut.id}: cut off by the restart", f"{rep.id}: reporter launched again"]
    assert jobs.get(store, cut.id)["status"] == "failed" and jobs.get(store, cut.id)["error"] == "Odie restarted"
    assert chat.posts[0]["text"].startswith(f"❌ Cut off didn't finish ({cut.id}): Odie restarted.")
    assert jobs.get(store, rep.id)["status"] == "waiting" and rep.id in router.running_ids()
    assert slept and slept[0] > 3600  # it waits for the next_run_at its row kept, not a run now
    router.stop(rep.id)


async def test_retry_job_from_the_chat(world):
    store, _, _ = world
    from odie.workers.tools import make_worker_tools
    _, _, _, retry_job, _ = make_worker_tools(store)
    assert "error" in await retry_job.func("job-nothere")
    Scripted.stall = True
    job = router.start("task", "Stop me", "…", "chat-1")
    await asyncio.sleep(0.02)
    router.stop(job.id)
    await asyncio.sleep(0.02)
    got = await retry_job.func(job.id)
    assert got == {"job_id": job.id, "status": "started again", "run": 2}
    router.stop(job.id)


# ── a model per kind ─────────────────────────────────────────────────────────

def test_light_kinds_run_on_the_small_model_when_one_is_chosen(world):
    store, _, _ = world
    from odie.workers.kinds import REPORTER, TASK
    store.set_setting("model.chat", {"provider": "ollama", "model": "deepseek-v4.1-flash:cloud"})
    assert worker.selection_for_kind(store, REPORTER).model == "deepseek-v4.1-flash:cloud"  # nothing chosen: the chat's
    store.set_setting("model.workers.auto", {"provider": "ollama", "model": "lfm3:latest"})  # Odie's own pick
    assert worker.selection_for_kind(store, REPORTER).model == "lfm3:latest"
    store.set_setting("model.workers", {"provider": "lmstudio", "model": "google/gemma-4-12b-qat"})  # the user's wins
    chosen = worker.selection_for_kind(store, REPORTER)
    assert (chosen.provider.id, chosen.model) == ("lmstudio", "google/gemma-4-12b-qat")
    assert worker.selection_for_kind(store, TASK).model == "deepseek-v4.1-flash:cloud"  # the task kind: the main model
    store.set_setting("model.workers", {"provider": "gone", "model": "x"})
    assert worker.selection_for_kind(store, REPORTER).model == "lfm3:latest"  # a provider that is gone: the next in line


def test_pick_small_model_prefers_lfm3_on_ollama():
    listing = [{"id": "lmstudio", "models": [{"id": "lfm3-big"}]},
               {"id": "ollama", "models": [{"id": "phonon:latest"}, {"id": "lfm2.5:1.2b"}, {"id": "lfm3:latest"}]}]
    assert worker.pick_small_model(listing) == {"provider": "ollama", "model": "lfm3:latest"}
    assert worker.pick_small_model([{"id": "ollama", "models": [{"id": "lfm2.5:1.2b"}]}]) == {"provider": "ollama", "model": "lfm2.5:1.2b"}
    assert worker.pick_small_model([{"id": "ollama", "models": [{"id": "qwen3.5:0.8b"}]}]) is None
    assert worker.pick_small_model([{"id": "lmstudio", "models": [{"id": "lfm3"}]}]) is None  # LM Studio: one model at a time


async def test_ensure_small_model_asks_ollama_once_and_keeps_the_users_pick(world, monkeypatch):
    store, _, _ = world
    import odie.models as models_mod
    asked = []

    async def ollama_has_lfm3(transport=None):
        asked.append(1)
        return [{"id": "ollama", "models": [{"id": "lfm3:latest"}]}]
    monkeypatch.setattr(models_mod, "ask_local_providers", ollama_has_lfm3)
    monkeypatch.setattr(worker, "_auto_checked", False)
    await worker.ensure_small_model(store)
    await worker.ensure_small_model(store)
    assert asked == [1]  # once per process
    assert store.get_setting("model.workers.auto") == {"provider": "ollama", "model": "lfm3:latest"}
    assert worker.small_model_chosen(store) == {"provider": "ollama", "model": "lfm3:latest", "auto": True}
    store.set_setting("model.workers", {"provider": "ollama", "model": "qwen3.5:0.8b"})
    monkeypatch.setattr(worker, "_auto_checked", False)
    await worker.ensure_small_model(store)
    assert asked == [1]  # the user chose: nothing to ask
    assert worker.small_model_chosen(store) == {"provider": "ollama", "model": "qwen3.5:0.8b", "auto": False}


async def test_the_brain_routes_offer_the_workers_slot_only_with_workers_on(isolated_settings, tmp_path, monkeypatch):
    import httpx

    import odie.app.routes as routes_mod
    from odie.app.main import create_app

    async def nobody(providers, transport=None):
        return [{"id": p.id, "name": p.name, "local": p.local, "models": [], "error": None} for p in providers]
    monkeypatch.setattr(routes_mod, "list_models", nobody)
    from tests.test_models import FakeRunner
    store = Store(tmp_path / "assistant.db")
    store.init_schema()
    app = create_app(runner=FakeRunner(), store=store)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            monkeypatch.delenv("ODIE_WORKERS", raising=False)
            assert set((await c.get("/api/models")).json()["selection"]) == {"chat"}
            r = await c.put("/api/models/selection", json={"slot": "workers", "provider": "ollama", "model": "lfm3:latest"})
            assert r.status_code == 422
            monkeypatch.setenv("ODIE_WORKERS", "1")
            got = (await c.get("/api/models")).json()["selection"]["workers"]
            assert got == {"provider": None, "model": None, "chosen": False, "auto": False}
            r = await c.put("/api/models/selection", json={"slot": "workers", "provider": "ollama", "model": "lfm3:latest"})
            assert r.status_code == 200 and r.json()["slot"] == "workers"
            got = (await c.get("/api/models")).json()["selection"]["workers"]
            assert got == {"provider": "ollama", "model": "lfm3:latest", "chosen": True, "auto": False}
            assert store.get_setting("model.workers") == {"provider": "ollama", "model": "lfm3:latest"}


# ── notify rules, done, and the cards on Today ───────────────────────────────

def test_should_tell_follows_the_rule():
    from odie.workers.store import Job
    rep = lambda notify: Job("job-1", "reporter", "t", "b", None, Path("/x"), 60, every_minutes=5, notify=notify)  # noqa: E731
    said = lambda **k: worker.Report(outcome="ready", text="…", **k)  # noqa: E731
    plain = Job("job-2", "task", "t", "b", None, Path("/x"), 60)
    assert worker.should_tell(plain, said(), None) is True
    assert worker.should_tell(rep("always"), said(state="same"), "same") is True
    assert worker.should_tell(rep("change"), said(state="Shipped"), None) is True          # the first run
    assert worker.should_tell(rep("change"), said(state=" shipped "), "Shipped") is False  # the same facts
    assert worker.should_tell(rep("change"), said(state="Out for delivery"), "Shipped") is True
    assert worker.should_tell(rep("condition"), said(met=False), "x") is False
    assert worker.should_tell(rep("condition"), said(met=True), "x") is True
    assert worker.should_tell(rep("condition"), said(done=True), "x") is True
    assert worker.should_tell(rep("condition"), worker.Report(outcome="blocked", text="need a key"), "x") is True


async def test_a_change_reporter_stays_quiet_while_the_facts_hold_and_ends_when_done(world, monkeypatch):
    store, chat, _ = world

    async def no_wait(seconds):
        pass
    monkeypatch.setattr(router, "sleep", no_wait)
    Scripted.script = [("report", {"outcome": "ready", "text": "Shipped from Pune.", "state": "Shipped"}), "ok",
                       ("report", {"outcome": "ready", "text": "Still shipped.", "state": "shipped"}), "ok",
                       ("report", {"outcome": "ready", "text": "Delivered at 10:40.", "state": "Delivered", "done": True}), "ok",
                       ("report", {"outcome": "ready", "text": "would be run 4"}), "ok"]
    job = router.start("task", "Order", "Track order 123.", "chat-1", every_minutes=5, notify="change")
    for _ in range(300):
        if jobs.get(store, job.id)["status"] == "done":
            break
        await asyncio.sleep(0.01)
    row = jobs.get(store, job.id)
    assert (row["status"], row["runs"], row["last_state"]) == ("done", 3, "Delivered")
    texts = [p["text"] for p in chat.posts]
    assert texts == [f"🔁 Report 1: Order ({job.id})\n\nShipped from Pune.",            # the first run is told
                     f"🏁 Order ({job.id}): nothing left to watch\n\nDelivered at 10:40."]  # run 2 was quiet; run 3 ended it
    assert [a["tool"] for a in jobs.actions(store, job.id)].count("report") == 3  # every run is on the record


async def test_a_stuck_or_failed_job_waits_on_today_with_retry(world):
    from datetime import UTC, datetime

    from odie.watch import needs
    store, chat, _ = world
    Scripted.script = [("report", {"outcome": "blocked", "text": "Need the API key for Zerodha.\nThen I can go on."})]
    job = router.start("task", "Portfolio pull", "…", "chat-1")
    for _ in range(300):
        if jobs.get(store, job.id)["status"] == "done":
            break
        await asyncio.sleep(0.01)
    cards = needs.cards(store, datetime.now(UTC))
    card = next(c for c in cards if c["ref"] == f"job:{job.id}")
    assert card["title"] == "Portfolio pull" and card["why"] == "Need the API key for Zerodha."
    assert card["main"] == {"label": "Retry", "action": "chat", "value": f"retry {job.id}"}
    assert card["other"]["label"] == "Dismiss"
    assert card["pile"] == "alerts"
    from odie.workers.tools import make_worker_tools
    *_, forget_job = make_worker_tools(store)
    assert await forget_job.func(job.id) == {"forgotten": job.id}
    assert not [c for c in needs.cards(store, datetime.now(UTC)) if c["ref"] == f"job:{job.id}"]
    assert "error" in await forget_job.func(job.id)


async def test_the_watchdogs_verdict_makes_a_card_too(world):
    from datetime import UTC, datetime, timedelta

    from odie.watch import needs
    from odie.workers import watchdog
    store, _, _ = world
    Scripted.stall = True
    job = router.start("task", "Slow", "…", "chat-1")
    await asyncio.sleep(0.05)
    await watchdog.check(store, datetime.now(UTC) + timedelta(minutes=11))
    await asyncio.sleep(0.05)
    card = next(c for c in needs.cards(store, datetime.now(UTC)) if c["ref"] == f"job:{job.id}")
    assert card["why"] == "made no progress for 10 minutes"
