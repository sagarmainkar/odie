"""The fourth security review (19 Nov 2026): no channel between two jobs through shared memory or semaphores (a
mail job can't leave text for a later web job), and an apps job gets only the app his words asked for, whose tools run
without a tap only when they plainly read his own data. Every name here is made up."""
from __future__ import annotations

import subprocess
import uuid
from types import SimpleNamespace

import pytest

from odie.workers import sandbox, worker
from odie.workers import store as jobs
from tests.test_workers import Chat, Scripted, Tool, a_job, world  # noqa: F401 (fixtures)

needs_sandbox = pytest.mark.skipif(not sandbox.available(), reason="no sandbox-exec on this computer")


# ── H1: no shared memory or semaphores between jobs ──────────────────────────

def run_in(job, code):
    argv = sandbox.command(["/usr/bin/python3", "-c", code], job)  # a job's python, not this project's venv
    done = subprocess.run(argv, cwd=job, env=sandbox.env(job), capture_output=True, text=True, timeout=60)
    return (done.stdout + done.stderr).strip()


@needs_sandbox
def test_one_jobs_shared_memory_and_semaphores_are_not_anothers(tmp_path):
    job_a, job_b = tmp_path / "jobs" / "a", tmp_path / "jobs" / "b"
    job_a.mkdir(parents=True)
    job_b.mkdir(parents=True)
    name = f"/r4{uuid.uuid4().hex[:6]}"
    made = run_in(job_a, "from multiprocessing import shared_memory as s\n"
                         f"m = s.SharedMemory(name='{name}', create=True, size=16); m.buf[:4] = b'MAIL'; print('made')")
    assert "made" not in made  # no POSIX shared memory at all
    sem = run_in(job_a, f"import _multiprocessing as m\ns = m.SemLock(1, 1, 1, '/mp-shared', False); print('sem made')")
    assert "sem made" not in sem  # a semaphore only under the job's own name prefix
    assert "[1, 2]" in run_in(job_b, "import multiprocessing as m\nprint(m.Pool(2).map(abs, [1, -2]))")  # Pool still works


def test_each_job_has_its_own_semaphore_prefix(tmp_path):
    a = sandbox.semaphore_prefix(tmp_path / "jobs" / "a")
    b = sandbox.semaphore_prefix(tmp_path / "jobs" / "b")
    assert a != b and a.startswith("/mp-") and len(a) + 1 + 8 <= 31  # macOS's semaphore names end at 31 characters
    profile = sandbox.profile(tmp_path / "jobs" / "a")
    assert f'(ipc-posix-name-prefix "{a}-")' in profile
    assert "(allow ipc-posix-shm" not in profile and "notification_center" not in profile


# ── H2: only the app he asked for, and only its plain reads ──────────────────

@pytest.mark.parametrize("name, args, runs", [
    ("gmail_search", {"query": "from:asha@example.com invoice"}, True),
    ("GMAIL_FETCH_EMAILS", {"max_results": 10}, True),
    ("calendar_list_events", {"start": "2026-11-19"}, True),
    ("gmail_create_draft", {"to": "asha@example.com", "body": "hi"}, False),
    ("calendar_update_event", {"id": "e1", "title": "x"}, False),
    ("move_email", {"id": "m1", "folder": "Archive"}, False),
    ("create_draft", {"body": "x"}, False),
    ("create_issue", {"title": "x"}, False),
    ("GITHUB_CREATE_ISSUE", {"title": "x"}, False),
    ("notion_create_page", {"title": "x"}, False),
    ("NOTION_ADD_PAGE_CONTENT", {"text": "x"}, False),
    ("gdrive_create_file", {"name": "x"}, False),
    ("fetch", {"url": "https://example.com/?d=mail"}, False),
    ("fetch_url", {"url": "https://example.com"}, False),
    ("browser_navigate", {"url": "https://example.com"}, False),
    ("puppeteer_navigate", {"url": "https://example.com"}, False),
    ("firecrawl_scrape", {"url": "https://example.com"}, False),
    ("tavily_search", {"query": "x"}, False),
    ("search_notes", {"query": "see example.com/x?d=secret"}, False),  # a bare address in an argument
    ("frobnicate_things", {}, False),  # an unknown verb
])
def test_an_app_tool_runs_without_a_tap_only_when_it_plainly_reads(name, args, runs):
    assert worker.app_may_run(Tool(name, server="app"), args) is runs


def test_a_refused_app_call_goes_to_the_card_as_an_exact_call(world, tmp_path):
    store, chat, _ = world
    job = a_job(store, tmp_path)
    guard = worker.guard_for(store, job, chat)
    refused = guard(Tool("gmail_create_draft", server="mail"), {"to": "asha@example.com", "body": "hi"}, None)
    assert refused["error"].startswith("Not run")
    need = jobs.needed(jobs.get(store, job.id))[0]
    assert need == {"tool": "gmail_create_draft", "args": {"to": "asha@example.com", "body": "hi"},
                    "why": "sends, pays, publishes or removes something in an app"}
    assert guard(Tool("gmail_search", server="mail"), {"query": "invoice"}, None) is None


class FakeToolset:
    def __init__(self, server):
        self.server = server

    async def get_tools(self, readonly_context=None):
        return []


def test_an_apps_job_gets_only_the_server_his_words_asked_for(world, tmp_path):
    store, _, _ = world
    from odie.watch import sources
    store.set_setting(sources.key_of(""), {"sources": [
        {"kind": "mail", "server": "work-mail", "app": "Mail", "style": "x", "tool": "search", "fixed": {}},
        {"kind": "calendar", "server": "work-cal", "app": "Calendar", "style": "x", "tool": "list", "fixed": {}}]})
    runner = SimpleNamespace(_plugin_toolsets=[FakeToolset("work-mail"), FakeToolset("work-cal"),
                                               FakeToolset("notion"), FakeToolset("github")])
    for uses, wanted in (("apps:mail", ["work-mail"]), ("apps:calendar", ["work-cal"]), ("app:notion", ["notion"])):
        job = a_job(store, tmp_path, title=f"J {uses}")
        job.uses = uses
        servers = [t.inner.server for t in worker.tools_for(store, job, runner) if hasattr(t, "inner")]
        assert servers == wanted, uses


def test_a_named_app_is_its_own_use():
    from odie.workers.tools import uses_for, uses_words
    assert uses_for("Use notion to list my open pages", ["notion"]) == "app:notion"
    assert uses_words("app:notion") == "the web and notion"  # the web too since 19 Nov (simpler Workers)
