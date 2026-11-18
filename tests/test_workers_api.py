"""Workers on Pulse (Workers design: "running and recent jobs on that personality's Pulse with Stop / Retry"): a running
job is under "on it" with Stop; a failed or stuck one is a card with Retry; one that needed a step the rules refuse is
a card with "Allow it and run again", a tap in the app (never the terminal's key) that covers that job's next run only;
a finished one is under Done today. Each personality sees only its own."""
from __future__ import annotations

import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
import pytest

from odie import config, devices, personalities
from odie.store.db import Store
from odie.watch import needs
from odie.workers import cards as job_cards
from odie.workers import router
from odie.workers import store as jobs
from tests.test_workers import Chat, Scripted


@pytest.fixture
def store(isolated_settings, tmp_path, monkeypatch):
    from odie.workers import worker
    s = Store(tmp_path / "a.db")
    s.init_schema()
    router.setup(s, Chat())
    monkeypatch.setattr(worker, "send_to_all", lambda *a, **k: None)
    monkeypatch.setattr(worker, "model_for_job", lambda store, job: Scripted(model="scripted"))
    Scripted.script, Scripted.seen, Scripted.stall = [], [], False
    yield s
    for task in list(router._tasks.values()):
        task.cancel()


@pytest.fixture
async def api(store, monkeypatch):
    from odie.app.main import create_app
    from tests.test_api import FakeRunner
    monkeypatch.setenv("ODIE_SCHEDULER", "0")
    app = create_app(runner=FakeRunner(), store=store)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c, \
            app.router.lifespan_context(app):
        router.setup(store, Chat())
        yield c


def now():
    return datetime.now(ZoneInfo(config.settings.timezone))


def ended_job(store, tmp_path, title="Tides", status="done", outcome="ready", needed=None, pid=""):
    folder = tmp_path / title
    folder.mkdir()
    job = jobs.create(store, "task", title, "Do it.", "chat-2026-11-18", folder, 60, personality=pid)
    jobs.started(store, job)
    for need in needed or []:
        jobs.note_needed(store, job.id, need)
    error = None
    if status == "failed":
        error = "made no progress for 10 minutes"
    jobs.ended(store, job.id, status, outcome=outcome, report="Wrote fib.py; it prints 55.", error=error)
    return job.id


CHMOD = {"tool": "run_shell", "command": "chmod u+r notes.txt", "why": "deletes or stops something"}


def test_a_failed_job_is_a_card_with_retry_and_done(store, tmp_path):
    jid = ended_job(store, tmp_path, status="failed", outcome=None)
    card = next(c for c in needs.cards(store, now()) if c["ref"] == f"job:{jid}")
    assert card["title"] == "Tides" and card["why"] == "Didn't finish: made no progress for 10 minutes"
    assert card["main"] == {"label": "Retry", "action": "job_retry", "value": jid}
    assert card["other"] == {"label": "Done", "action": "job_clear", "value": jid}


def test_a_job_that_needed_a_step_offers_allow_it_and_run_again(store, tmp_path):
    jid = ended_job(store, tmp_path, outcome="blocked", needed=[CHMOD])
    card = next(c for c in needs.cards(store, now()) if c["ref"] == f"job:{jid}")
    assert card["why"] == "I needed to: `chmod u+r notes.txt` (deletes or stops something)"
    assert card["main"] == {"label": "Allow it and run again", "action": "job_allow", "value": jid}


def test_a_finished_job_is_done_today_not_a_card(store, tmp_path):
    jid = ended_job(store, tmp_path)
    assert [c for c in needs.cards(store, now()) if c["ref"] == f"job:{jid}"] == []
    done = job_cards.done_today(store, "", now())
    assert done[0]["id"] == jid and done[0]["title"] == "Tides" and done[0]["why"].startswith("done ")


def test_cleared_cards_and_another_personalitys_jobs_stay_off(store, tmp_path):
    mira = personalities.create(store, "Mira")
    hers = ended_job(store, tmp_path, title="Hers", status="failed", outcome=None, pid=mira.id)
    mine = ended_job(store, tmp_path, title="Mine", status="failed", outcome=None)
    assert [c["ref"] for c in needs.cards(store, now()) if c["ref"].startswith("job:")] == [f"job:{mine}"]
    assert [c["ref"] for c in needs.cards(store, now(), mira.id) if c["ref"].startswith("job:")] == [f"job:{hers}"]
    jobs.clear(store, mine)
    assert [c for c in needs.cards(store, now()) if c["ref"].startswith("job:")] == []


async def test_a_running_job_is_on_it_with_stop(api, store):
    Scripted.stall = True
    job = router.start("Long one", "x", "chat-2026-11-18")
    await asyncio.sleep(0.05)
    got = (await api.get("/api/needs_you")).json()
    line = next(i for i in got["on_it"] if i["id"] == job.id)
    assert line["title"] == "Long one" and line["state"] == "working" and line["stop"] == job.id
    assert (await api.post(f"/api/jobs/{job.id}/stop")).status_code == 200
    assert jobs.get(store, job.id)["status"] == "stopped"


async def test_allow_it_and_run_again_carries_exactly_what_was_needed(api, store, tmp_path):
    jid = ended_job(store, tmp_path, outcome="blocked", needed=[CHMOD])
    Scripted.stall = True
    r = await api.post(f"/api/jobs/{jid}/allow")
    assert r.status_code == 200
    row = jobs.get(store, jid)
    assert row["status"] in ("queued", "running") and jobs.loads(row["allowed_json"]) == [CHMOD]
    assert (await api.post(f"/api/jobs/{jid}/allow")).status_code == 409  # still going


async def test_retry_and_clear_from_pulse(api, store, tmp_path):
    jid = ended_job(store, tmp_path, status="failed", outcome=None)
    Scripted.script = [("report", {"outcome": "ready", "text": "ok"})]
    assert (await api.post(f"/api/jobs/{jid}/retry")).status_code == 200
    assert jobs.loads(jobs.get(store, jid)["allowed_json"]) == []
    other = ended_job(store, tmp_path, title="Other", status="failed", outcome=None)
    assert (await api.post(f"/api/jobs/{other}/clear")).status_code == 200
    assert jobs.get(store, other)["cleared"] == 1


async def test_a_personalitys_job_is_not_reachable_with_another_pick(api, store, tmp_path):
    mira = personalities.create(store, "Mira")
    hers = ended_job(store, tmp_path, title="Hers", status="failed", outcome=None, pid=mira.id)
    assert (await api.post(f"/api/jobs/{hers}/retry")).status_code == 404
    assert (await api.get(f"/api/jobs/{hers}")).status_code == 404
    got = (await api.get(f"/api/jobs/{hers}?personality={mira.id}")).json()
    assert got["id"] == hers and got["report"].startswith("Wrote fib.py")
    listed = (await api.get(f"/api/jobs?personality={mira.id}")).json()
    assert [j["id"] for j in listed["recent"]] == [hers]


def test_the_terminals_key_can_never_allow_retry_stop_or_clear():
    for what in ("allow", "retry", "stop", "clear"):
        assert devices.terminal_may("POST", f"/api/jobs/job-abc123/{what}") is False
    assert devices.terminal_may("GET", "/api/jobs") is False
