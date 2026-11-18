"""Workers (odie.workers, Workers design 18 Nov 2026): a job the chat hands to a background Worker, through the real ADK
with a stand-in model. The Worker gets the shell, its own files, web reads and report (plus its personality's apps);
it never asks: what the Smart rules would card is refused and noted as "needed", and only the user's tap in the app
lets it run on a retry. Every call is a row in job_actions; the chat that started it gets one message at the end."""
from __future__ import annotations

import asyncio
from typing import ClassVar

import pytest
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from odie.store.db import Store
from odie.workers import allow, router, worker
from odie.workers import store as jobs


class Chat:
    """Stands in for the runner: keeps every post_message call; has no apps."""

    def __init__(self):
        self.posts = []
        self._plugin_toolsets = []

    async def post_message(self, text, session_id=None, media=None, kind="system"):
        self.posts.append({"text": text, "session_id": session_id, "media": media, "kind": kind})

    def _apps_stop(self, tool, args, tool_context):
        return None


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
    """A store, a chat to post to, no pushes (kept), a scripted model on every brain."""
    from odie import config
    assert str(config.settings.data_dir).startswith(str(tmp_path))  # never a real home
    store = Store(tmp_path / "assistant.db")
    store.init_schema()
    chat = Chat()
    pushes = []
    monkeypatch.setattr(worker, "send_to_all", lambda store, title, body, url="/", tag=None: pushes.append((title, body, tag)))
    monkeypatch.setattr(worker, "model_for_job", lambda store, job: Scripted(model="scripted"))
    Scripted.script = []
    Scripted.seen = []
    Scripted.stall = False
    router.setup(store, chat)
    yield store, chat, pushes
    for task in list(router._tasks.values()):
        task.cancel()


def a_job(store, tmp_path, title="Tides", budget=60, personality="", session="chat-2026-11-18"):
    folder = tmp_path / "jobs" / title.lower()
    folder.mkdir(parents=True)
    return jobs.create(store, "task", title, "Say hello from the shell, then report.", session, folder, budget,
                       personality=personality)


async def until(check, tries=300):
    for _ in range(tries):
        if check():
            return True
        await asyncio.sleep(0.01)
    return False


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
    assert (row["status"], row["outcome"], row["report"], row["started_by"]) == ("done", "ready", "hello", "you")
    assert [a["tool"] for a in jobs.actions(store, job.id)] == ["run_shell"]
    assert jobs.running(store) == []
    store.init_schema()  # again: nothing lost
    assert jobs.get(store, job.id)["report"] == "hello"


def test_a_jobs_needs_are_kept_once_each(world, tmp_path):
    store, _, _ = world
    job = a_job(store, tmp_path)
    need = {"tool": "run_shell", "command": "rm ~/Documents/old.txt", "why": "deletes or stops something"}
    jobs.note_needed(store, job.id, need)
    jobs.note_needed(store, job.id, need)
    assert jobs.needed(jobs.get(store, job.id)) == [need]


# ── what a tap allows ────────────────────────────────────────────────────────

def test_an_allow_covers_a_passable_kind_and_otherwise_only_the_exact_call():
    deletes = {"tool": "run_shell", "command": "rm ~/Documents/old.txt", "why": "deletes or stops something"}
    install = {"tool": "run_shell", "command": "npm install left-pad", "why": "installs software (runs its install scripts)"}
    send = {"tool": "GMAIL_SEND_EMAIL", "args": {"to": "asha@example.com"}, "why": allow.APP_WHY}
    assert allow.covers([deletes], "run_shell", {"command": "rm -f build.log"}, ["deletes or stops something"])
    assert not allow.covers([deletes], "run_shell", {"command": "cat ~/.env"}, ["reads secrets"])
    assert allow.covers([install], "run_shell", {"command": "npm install left-pad"}, [install["why"]])
    assert not allow.covers([install], "run_shell", {"command": "npm install evil"}, [install["why"]])
    assert allow.covers([send], "GMAIL_SEND_EMAIL", {"to": "asha@example.com"}, [allow.APP_WHY])
    assert not allow.covers([send], "GMAIL_SEND_EMAIL", {"to": "someone@example.com"}, [allow.APP_WHY])
    assert not allow.covers([], "run_shell", {"command": "rm a"}, ["deletes or stops something"])
    both = ["deletes or stops something", "installs software (runs its install scripts)"]
    assert not allow.covers([deletes], "run_shell", {"command": "rm a && npm install x"}, both)  # every reason needs cover


def test_what_was_needed_reads_as_a_line():
    assert allow.line({"tool": "run_shell", "command": "rm ~/Documents/old.txt", "why": "deletes or stops something"}) == \
        "`rm ~/Documents/old.txt` (deletes or stops something)"
    assert allow.line({"tool": "GMAIL_SEND_EMAIL", "args": {"to": "a"}, "why": allow.APP_WHY}) == \
        f"GMAIL_SEND_EMAIL ({allow.APP_WHY})"


# ── the guard ────────────────────────────────────────────────────────────────

class Tool:
    def __init__(self, name, server=None):
        self.name = name
        if server:
            self._odie_server = server


def test_the_guard_follows_smart_rules_and_refuses_what_would_ask(world, tmp_path):
    store, chat, _ = world
    job = a_job(store, tmp_path)
    guard = worker.guard_for(store, job, chat)
    args = {"command": "echo hi"}
    assert guard(Tool("run_shell"), args, None) is None
    assert args["cwd"] == str(job.folder)  # the Worker's commands start in its own folder
    assert guard(Tool("run_shell"), {"command": "echo x > notes.txt", "cwd": str(job.folder)}, None) is None
    bad = {"command": "rm ~/Documents/old.txt", "cwd": str(job.folder)}
    refused = guard(Tool("run_shell"), bad, None)
    assert refused["error"].startswith("Not run: it deletes or stops something.")
    assert "report" in refused["error"]
    assert guard(Tool("web_search"), {"query": "tides"}, None) is None
    assert guard(Tool("GMAIL_SEND_EMAIL", server="mail"), {"to": "a"}, None)["error"].startswith("Not run")
    assert guard(Tool("GMAIL_FETCH_EMAILS", server="mail"), {}, None) is None
    worker.after_for(store, job)(Tool("run_shell"), bad, None, refused)  # ADK calls after even for a refused call
    worker.after_for(store, job)(Tool("web_search"), {"query": "tides"}, None, {"results": []})
    recorded = jobs.actions(store, job.id)
    assert [(a["tool"], a["refused"]) for a in recorded] == [
        ("run_shell", "deletes or stops something"), ("GMAIL_SEND_EMAIL", allow.APP_WHY), ("web_search", None)]
    needed = jobs.needed(jobs.get(store, job.id))
    assert needed[0] == {"tool": "run_shell", "command": "rm ~/Documents/old.txt", "why": "deletes or stops something"}


def test_an_allowed_retry_lets_exactly_that_through(world, tmp_path):
    store, chat, _ = world
    job = a_job(store, tmp_path)
    jobs.set_allowed(store, job.id, [{"tool": "run_shell", "command": "rm ~/Documents/old.txt", "why": "deletes or stops something"}])
    job = jobs.from_row(jobs.get(store, job.id))
    guard = worker.guard_for(store, job, chat)
    assert guard(Tool("run_shell"), {"command": "rm ~/Documents/old.txt", "cwd": str(job.folder)}, None) is None
    assert guard(Tool("run_shell"), {"command": "cat ~/.env", "cwd": str(job.folder)}, None) is not None


# ── a run, end to end ────────────────────────────────────────────────────────
# Commands a test lets run are harmless in the job's folder under tmp (`chmod u+r notes.txt`): never a real path.

async def test_a_worker_runs_the_shell_in_its_folder_reports_and_the_chat_hears_once(world, tmp_path):
    store, chat, pushes = world
    job = a_job(store, tmp_path)
    Scripted.script = [("run_shell", {"command": "echo hello && pwd"}),
                       ("report", {"outcome": "ready", "text": "The shell says hello."})]
    status = await worker.run(job, store, chat)
    assert status == "done"
    row = jobs.get(store, job.id)
    assert (row["status"], row["outcome"], row["report"], row["runs"]) == ("done", "ready", "The shell says hello.", 1)
    acted = jobs.actions(store, job.id)
    assert [a["tool"] for a in acted] == ["run_shell", "report"]
    assert chat.posts == [{"text": f"✅ Done: Tides ({job.id})\n\nThe shell says hello.", "session_id": "chat-2026-11-18",
                           "media": None, "kind": "job"}]
    assert pushes[0][2] == job.id
    first = Scripted.seen[0]
    names = sorted(f.name for t in first.config.tools for f in t.function_declarations)
    assert names == ["read_file", "report", "run_shell", "web_fetch", "web_search", "write_file"]
    assert str(first.config.system_instruction).startswith("You are a Worker")
    assert str(job.folder) in str(first.config.system_instruction)
    second = Scripted.seen[1]
    results = [p.function_response.response for c in second.contents for p in c.parts or [] if p.function_response]
    assert str(job.folder) in str(results[0])  # the shell ran in the job's folder


async def test_a_refused_step_is_reported_as_needed_with_the_way_to_allow_it(world, tmp_path):
    store, chat, _ = world
    job = a_job(store, tmp_path)
    Scripted.script = [("run_shell", {"command": "chmod u+r notes.txt"}),
                       ("report", {"outcome": "blocked", "text": "I couldn't change notes.txt."})]
    await worker.run(job, store, chat)
    text = chat.posts[0]["text"]
    assert text.startswith(f"⛔ Tides is stuck ({job.id})\n\nI couldn't change notes.txt.")
    assert "I needed to: `chmod u+r notes.txt` (deletes or stops something)." in text
    assert "Allow it and run again" in text and "Pulse" in text


async def test_after_report_the_model_is_not_called_again(world, tmp_path):
    store, chat, _ = world
    job = a_job(store, tmp_path)
    Scripted.script = [("report", {"outcome": "ready", "text": "First."}), ("report", {"outcome": "ready", "text": "Again."}), "more"]
    await worker.run(job, store, chat)
    assert len(Scripted.seen) == 1
    assert jobs.get(store, job.id)["report"] == "First."


async def test_a_worker_that_stops_without_a_report_is_nudged_once_then_fails(world, tmp_path):
    store, chat, _ = world
    job = a_job(store, tmp_path)
    Scripted.script = ["I think that's it.", "Yes, done."]
    status = await worker.run(job, store, chat)
    assert status == "failed"
    assert len(Scripted.seen) == 2
    assert "Call report now" in Scripted.seen[1].contents[-1].parts[0].text
    assert jobs.get(store, job.id)["error"] == "stopped without a report"
    assert chat.posts[0]["text"].startswith(f"❌ Tides didn't finish ({job.id}): stopped without a report")


async def test_a_worker_past_its_budget_is_stopped_and_the_job_fails(world, tmp_path):
    store, chat, _ = world
    job = a_job(store, tmp_path, budget=1)
    Scripted.stall = True
    assert await worker.run(job, store, chat) == "failed"
    assert jobs.get(store, job.id)["error"] == "ran past its budget of 1 seconds"


async def test_files_in_the_folder_ride_along_others_do_not(world, tmp_path):
    store, chat, _ = world
    job = a_job(store, tmp_path)
    (job.folder / "notes.txt").write_text("the notes")
    Scripted.script = [("report", {"outcome": "ready", "text": "Here.", "files": ["notes.txt", "/etc/hosts"]})]
    await worker.run(job, store, chat)
    assert [m["filename"] for m in chat.posts[0]["media"]] == ["notes.txt"]


async def test_write_file_and_read_file_stay_inside_the_jobs_folder(world, tmp_path):
    store, _, _ = world
    job = a_job(store, tmp_path)
    from odie.workers.files import make_job_file_tools
    write_file, read_file = make_job_file_tools(job.folder)
    assert (await write_file.func("src/fib.py", "print(1)\n"))["bytes"] == 9
    assert (await read_file.func("src/fib.py"))["text"] == "print(1)\n"
    assert "error" in await write_file.func("../escape.txt", "x")
    assert "error" in await write_file.func("/etc/hosts", "x")
    assert "error" in await read_file.func("missing.txt")
    assert not (tmp_path / "jobs" / "escape.txt").exists()


def test_budget_words():
    assert worker.budget_words(2700) == "45 minutes"
    assert worker.budget_words(60) == "1 minute"
    assert worker.budget_words(90) == "90 seconds"


def test_the_workers_budget_is_45_minutes_and_80_calls():
    assert worker.BUDGET_SECONDS == 45 * 60 and worker.MAX_CALLS == 80


# ── per personality ──────────────────────────────────────────────────────────

async def test_a_personalitys_job_thinks_with_its_brain_and_reports_quietly_in_its_chat(world, tmp_path, monkeypatch):
    store, chat, pushes = world
    from odie import brains, personalities
    mira = personalities.create(store, "Mira")
    personalities.claim(store, "chat-2026-11-18-2", mira.id)
    asked = []
    monkeypatch.setattr(brains, "for_personality", lambda store, pid: asked.append(pid) or "her brain")
    monkeypatch.setattr(worker, "model_for_job", worker.__dict__["_model_for_job"])
    monkeypatch.setattr(worker, "model_for", lambda sel, effort: Scripted(model=f"scripted-{sel}"))
    job = a_job(store, tmp_path, personality=mira.id, session="chat-2026-11-18-2")
    Scripted.script = [("report", {"outcome": "ready", "text": "Done for Mira."})]
    await worker.run(job, store, chat)
    assert asked == [mira.id]
    assert chat.posts[0]["session_id"] == "chat-2026-11-18-2"
    assert pushes == [("Mira replied", "Open Odie to read it.", job.id)]  # never the words on the lock screen


async def test_a_workers_session_belongs_to_its_personality_while_it_runs(world, tmp_path):
    store, chat, _ = world
    from odie import personalities
    mira = personalities.create(store, "Mira")
    job = a_job(store, tmp_path, personality=mira.id)
    seen = []

    class Peek(Scripted):
        async def generate_content_async(self, llm_request, stream=False):
            seen.append(personalities.of_session(store, job.id))
            async for r in super().generate_content_async(llm_request, stream):
                yield r
    Scripted.script = [("report", {"outcome": "ready", "text": "ok"})]
    await worker.run(job, store, chat, model=Peek(model="peek"))
    assert seen == [mira.id]
    assert personalities.of_session(store, job.id) == ""  # only while it runs


# ── the router ───────────────────────────────────────────────────────────────

async def test_the_router_starts_a_job_in_its_own_folder_and_runs_it(world):
    store, chat, _ = world
    Scripted.script = [("report", {"outcome": "ready", "text": "ok"})]
    job = router.start("Tides report!", "Do it.", "chat-9")
    assert job.folder.is_dir() and job.folder.name.startswith("tides-report-")
    assert await until(lambda: jobs.get(store, job.id)["status"] == "done")
    assert chat.posts[0]["session_id"] == "chat-9"


async def test_three_run_at_once_and_the_fourth_waits(world):
    store, _, _ = world
    Scripted.stall = True
    started = [router.start(f"Job {n}", "Take long.", "chat-1") for n in range(4)]
    await asyncio.sleep(0.1)
    statuses = [jobs.get(store, j.id)["status"] for j in started]
    assert statuses.count("running") == 3 and statuses.count("queued") == 1


async def test_odies_own_jobs_take_two_slots_at_most_and_eight_a_day(world, monkeypatch):
    store, _, _ = world
    Scripted.stall = True
    own = [router.start(f"Own {n}", "x", None, started_by="odie") for n in range(3)]
    await asyncio.sleep(0.1)
    assert [jobs.get(store, j.id)["status"] for j in own].count("running") == 2  # one slot is always his
    his = router.start("His", "x", "chat-1")
    await asyncio.sleep(0.1)
    assert jobs.get(store, his.id)["status"] == "running"
    for n in range(5):
        assert router.start(f"More {n}", "x", None, started_by="odie") is not None
    assert router.start("Ninth", "x", None, started_by="odie") is None  # 8 a day
    assert router.odie_left_today(store) == 0


async def test_stop_cancels_a_running_job_and_marks_it_stopped(world):
    store, chat, _ = world
    Scripted.stall = True
    job = router.start("Long one", "Take forever.", "chat-9")
    await asyncio.sleep(0.05)
    assert router.stop(job.id) is True
    await asyncio.sleep(0.05)
    assert jobs.get(store, job.id)["status"] == "stopped"
    assert router.stop(job.id) is False
    assert chat.posts == []  # a stop says nothing in the chat: the user asked for it


async def test_retry_with_an_allow_carries_it_for_that_run_only(world, tmp_path):
    store, chat, _ = world
    Scripted.script = [("run_shell", {"command": "chmod u+r notes.txt"}), ("report", {"outcome": "blocked", "text": "Needed chmod."})]
    job = router.start("Tidy", "Make notes.txt readable.", "chat-1")
    assert await until(lambda: jobs.get(store, job.id)["status"] == "done")
    needed = jobs.needed(jobs.get(store, job.id))
    assert needed and router.retry(job.id, allowed=needed) is not None
    row = jobs.get(store, job.id)
    assert allow.loads(row["allowed_json"]) == needed and jobs.needed(row) == []  # fresh needs for the new run
    Scripted.script = [("run_shell", {"command": "chmod u+r notes.txt"}), ("report", {"outcome": "ready", "text": "Done."})]
    assert await until(lambda: jobs.get(store, job.id)["status"] == "done" and jobs.get(store, job.id)["runs"] == 2)
    acts = [a for a in jobs.actions(store, job.id) if a["tool"] == "run_shell"]
    assert acts[-1]["refused"] is None  # ran this time
    router.retry(job.id)  # the chat's retry: no allow
    assert allow.loads(jobs.get(store, job.id)["allowed_json"]) == []


async def test_a_running_job_cant_be_retried(world):
    store, _, _ = world
    Scripted.stall = True
    job = router.start("Busy", "x", "chat-1")
    await asyncio.sleep(0.05)
    assert router.retry(job.id) is None


async def test_recovery_tells_a_cut_off_job_in_its_chat(world, tmp_path):
    store, chat, _ = world
    job = a_job(store, tmp_path)
    jobs.started(store, job)
    lines = await router.recover()
    assert lines == [f"{job.id}: cut off by the restart"]
    assert jobs.get(store, job.id)["status"] == "failed"
    assert chat.posts[0]["text"].startswith(f"❌ Tides didn't finish ({job.id}): Odie restarted")


async def test_stopping_a_personalitys_jobs_leaves_the_others(world):
    store, _, _ = world
    from odie import personalities
    mira = personalities.create(store, "Mira")
    Scripted.stall = True
    hers = router.start("Hers", "x", None, personality=mira.id)
    his = router.start("His", "x", "chat-1")
    await asyncio.sleep(0.05)
    router.stop_for(mira.id)
    await asyncio.sleep(0.05)
    assert jobs.get(store, hers.id)["status"] == "stopped" and jobs.get(store, his.id)["status"] == "running"


# ── the watchdog ─────────────────────────────────────────────────────────────

def _row(**over):
    base = {"id": "job-1", "kind": "task", "status": "running", "budget_seconds": 2700,
            "started_at": "2026-11-04T10:00:00.000Z"}
    return {**base, **over}


def test_why_stuck_reads_budget_stall_and_repeated_refusals():
    from datetime import UTC, datetime

    from odie.workers import watchdog
    at = lambda h, m: datetime(2026, 11, 4, h, m, tzinfo=UTC)  # noqa: E731
    act = lambda h, m, **k: {"ts": f"2026-11-04T{h:02d}:{m:02d}:00.000Z", "refused": None, "error": None, **k}  # noqa: E731
    assert watchdog.why_stuck(_row(), [act(10, 1)], at(10, 2)) is None
    assert watchdog.why_stuck(_row(), [act(10, 1)], at(10, 12)) == "made no progress for 10 minutes"
    assert watchdog.why_stuck(_row(), [], at(10, 11)) == "made no progress for 10 minutes"
    assert watchdog.why_stuck(_row(), [act(10, 46)], at(10, 48)) == "ran past its budget and didn't stop"
    same = [act(10, 1, refused="deletes or stops something") for _ in range(3)]
    assert watchdog.why_stuck(_row(), same, at(10, 2)) == "hit the same refusal 3 times: deletes or stops something"
    # a PR test is code: silence is normal while a test suite runs; only its budget counts
    assert watchdog.why_stuck(_row(kind="pr_test"), [], at(10, 30)) is None


async def test_the_watchdog_fails_a_stalled_job_and_tells_the_chat(world):
    from datetime import UTC, datetime, timedelta

    from odie.workers import watchdog
    store, chat, _ = world
    Scripted.stall = True
    job = router.start("Slow one", "Take forever.", "chat-1")
    await asyncio.sleep(0.05)
    done = await watchdog.check(store, datetime.now(UTC) + timedelta(minutes=11))
    assert done == [f"{job.id}: failed, made no progress for 10 minutes"]
    assert jobs.get(store, job.id)["status"] == "failed"
    assert chat.posts[0]["text"].startswith(f"❌ Slow one didn't finish ({job.id}): made no progress for 10 minutes")
    assert router.retry(job.id) is not None  # the user retries


# ── the chat's tools ─────────────────────────────────────────────────────────

class Ctx:
    def __init__(self, sid):
        self.session = type("S", (), {"id": sid})()


async def test_start_job_from_the_chat_names_the_chat_and_its_owner(world):
    store, _, _ = world
    from odie import personalities
    from odie.workers.tools import make_worker_tools
    mira = personalities.create(store, "Mira")
    personalities.claim(store, "chat-2026-11-18-3", mira.id)
    Scripted.script = [("report", {"outcome": "ready", "text": "ok"})]
    start_job, jobs_status, stop_job, retry_job, forget_job = make_worker_tools(store)
    got = await start_job.func("Tides", "Do it.", tool_context=Ctx("chat-2026-11-18-3"))
    assert got["status"] == "started"
    row = jobs.get(store, got["job_id"])
    assert (row["session_id"], row["personality"]) == ("chat-2026-11-18-3", mira.id)
    assert await until(lambda: jobs.get(store, got["job_id"])["status"] == "done")
    mine = await jobs_status.func(tool_context=Ctx("chat-2026-11-18-3"))
    assert mine["recent"][0].startswith(got["job_id"])
    odies = await jobs_status.func(tool_context=Ctx("chat-2026-11-18"))
    assert odies == {"running": [], "recent": []}  # Mira's jobs are hers
    assert "error" in await retry_job.func(got["job_id"], tool_context=Ctx("chat-2026-11-18"))
    assert await stop_job.func(got["job_id"], tool_context=Ctx("chat-2026-11-18-3")) == {"error": f"{got['job_id']} isn't running."}


async def test_a_background_turn_cant_start_a_job(world):
    store, _, _ = world
    from odie.workers.tools import make_worker_tools
    start_job = make_worker_tools(store)[0]
    got = await start_job.func("Sneaky", "Run this.", tool_context=Ctx("8f1e2d3c-watch-session"))
    assert "error" in got and jobs.running(store) == []


def test_the_chat_always_has_the_worker_tools(world):
    store, _, _ = world
    from odie.agent.agent import build_agent
    names = {t.name for t in build_agent(store).tools if hasattr(t, "name")}
    assert {"start_job", "jobs_status", "stop_job", "retry_job", "forget_job"} <= names


# ── the nudge ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text, expected", [
    ("Write a Python script that prints the first 20 primes and run it", True),
    ("write a small script and run it", True),
    ("Can you test the new parser and fix what breaks?", True),
    ("Check this Mac's disk and memory and tell me", True),
    ("Do this in the background: tidy the downloads folder", True),
    ("How is the market today?", False),
    ("What does this script do?", False),
    ("Remind me to run the tests at 5", False),
    ("Make me a deck about tides", False),
    ("ls ~/Downloads", False),
    ("Track the HN front page and report every hour", False),  # a tracker's job now, not a Worker's
])
def test_looks_like_a_job(text, expected):
    from odie.workers.nudge import looks_like_a_job
    assert looks_like_a_job(text) is expected


def test_the_job_nudge_rides_on_a_job_like_turn(world):
    store, _, _ = world
    from odie.app.runner import OdieRunner
    from odie.workers.nudge import NUDGE
    r = OdieRunner.__new__(OdieRunner)
    r.store = store
    assert r._job_nudge("chat-1", "Write a script that sorts my photos and run it") == "\n" + NUDGE
    assert r._job_nudge("chat-1", "How is the market today?") == ""


async def test_deleting_a_personality_stops_and_forgets_its_jobs(world):
    store, _, _ = world
    from odie import personalities

    class Runner:
        async def forget_personality(self, pid):
            pass

        async def erase_thread(self, sid):
            return [], []

        def invalidate_prompt(self):
            pass
    mira = personalities.create(store, "Mira")
    Scripted.stall = True
    hers = router.start("Hers", "x", None, personality=mira.id)
    his = router.start("His", "x", "chat-1")
    await asyncio.sleep(0.05)
    await personalities.delete(store, Runner(), mira.id)
    await asyncio.sleep(0.05)
    assert jobs.get(store, hers.id) is None
    assert jobs.get(store, his.id)["status"] == "running"
