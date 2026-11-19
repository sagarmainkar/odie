"""Found live (19 Nov 2026): on a real install a job's folder is ~/.odie/data/workspace/jobs/<name>, inside a hidden
folder of the home and inside Odie's own. Its own Worker must be able to name its folder (`cd <folder> && python3
x.py`) without the Worker rules calling that "hidden files in your home"; everything else of Odie's stays refused.
And a job that finished cleanly doesn't end with "I needed to" lines for steps it then did another way. The home and
Odie's home here are stand-ins under tmp_path."""
from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from odie.store.db import Store
from odie.workers import router, worker
from odie.workers import store as jobs
from tests.test_workers import Chat, Scripted, Tool


@pytest.fixture
def real_layout(tmp_path, monkeypatch):
    """A stand-in home with Odie's home as a hidden folder in it, as on a real install: <tmp>/home/.odie."""
    home = tmp_path / "home"
    odie_home = home / ".odie"
    (odie_home / "data").mkdir(parents=True)
    (odie_home / ".env").write_text("STAND_IN=1\n")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setenv("ODIE_HOME", str(odie_home))
    monkeypatch.setenv("ODIE_DATA_DIR", str(odie_home / "data"))
    monkeypatch.setenv("ODIE_CONFIG_DIR", str(odie_home / "config"))
    monkeypatch.setenv("ODIE_MEMORY_FILE", str(odie_home / "memories.md"))
    monkeypatch.setenv("ODIE_PREFETCH", "0")
    import odie.config as c
    importlib.reload(c)
    assert str(c.settings.data_dir).startswith(str(tmp_path))
    store = Store(odie_home / "data" / "assistant.db")
    store.init_schema()
    chat = Chat()
    router.setup(store, chat)
    jobs_root = odie_home / "data" / "workspace" / "jobs"
    mine, other = jobs_root / "first-primes-7180b6", jobs_root / "other-job-1a2b3c"
    mine.mkdir(parents=True)
    other.mkdir(parents=True)
    job = jobs.create(store, "task", "First primes", "x", "chat-2026-11-19", mine, 60)
    yield store, chat, job, odie_home, other
    monkeypatch.undo()
    importlib.reload(c)


def refused(store, chat, job, command):
    return worker.guard_for(store, job, chat)(Tool("run_shell"), {"command": command, "cwd": str(job.folder)}, None)


def test_a_worker_may_name_its_own_folder_on_a_real_install(real_layout):
    store, chat, job, _, _ = real_layout
    folder = job.folder
    assert refused(store, chat, job, f"cd {folder} && python3 first_primes.py; echo \"EXIT=$?\"") is None
    assert refused(store, chat, job, f"cat {folder}/out.txt") is None
    assert refused(store, chat, job, "cd ~/.odie/data/workspace/jobs/first-primes-7180b6 && ls") is None
    assert jobs.needed(jobs.get(store, job.id)) == []


@pytest.mark.parametrize("command", [
    "cat {odie_home}/.env", "ls {other}", "cd {odie_home}/data && ls", "ls {folder}/../other-job-1a2b3c",
    "ls {folder}/..", "cat ~/.odie/.env",
])
def test_everything_else_of_odies_stays_refused(real_layout, command):
    store, chat, job, odie_home, other = real_layout
    text = command.format(odie_home=odie_home, other=other, folder=job.folder)
    assert refused(store, chat, job, text) is not None, text


async def test_a_clean_finish_doesnt_end_with_steps_it_did_another_way(real_layout):
    store, chat, job, _, _ = real_layout
    worker.model_for_job = lambda store, job: Scripted(model="scripted")
    try:
        Scripted.script, Scripted.seen, Scripted.stall = [
            ("run_shell", {"command": "cat ~/.odie/.env"}),  # refused; it then finishes another way
            ("report", {"outcome": "ready", "text": "Primes: 2 3 5 7 11 13 17 19 23 29"})], [], False
        await worker.run(job, store, chat)
    finally:
        worker.model_for_job = worker._model_for_job
    assert "I needed to" not in chat.posts[0]["shown"]
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    from odie.workers import cards as job_cards
    soon = datetime.now(ZoneInfo("Asia/Kolkata")) + timedelta(minutes=1)
    assert job_cards.cards(store, "", soon) == []  # done: no card; the refusal stays in its log


async def test_a_blocked_job_still_says_what_it_needed(real_layout):
    store, chat, job, _, _ = real_layout
    worker.model_for_job = lambda store, job: Scripted(model="scripted")
    try:
        Scripted.script, Scripted.seen, Scripted.stall = [
            ("run_shell", {"command": "chmod u+r ~/notes.txt"}),
            ("report", {"outcome": "blocked", "text": "Couldn't change notes.txt."})], [], False
        await worker.run(job, store, chat)
    finally:
        worker.model_for_job = worker._model_for_job
    assert "I needed to:" in chat.posts[0]["shown"]
