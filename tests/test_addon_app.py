"""The app's add-on seams: routes, scheduled jobs, About, health, the brief, Up next, open-thread hints and the start
hook."""
import json
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import httpx
import pytest
from fastapi import APIRouter

from odie import about, addons
from odie.addons import Addon, BriefPart, Job
from odie.store.db import Store

NOW = datetime(2026, 10, 1, 7, 30, tzinfo=ZoneInfo("Asia/Kolkata"))


@pytest.fixture(autouse=True)
def no_addons_after():
    yield
    addons.use(None)


@pytest.fixture
def store(isolated_settings, tmp_path):
    s = Store(tmp_path / "assistant.db")
    s.init_schema()
    s.set_setting("news", {"fetched_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), "topics": [], "items": []})
    return s


async def _get(store, path):
    from odie.app.main import create_app
    from tests.test_api import FakeRunner
    app = create_app(runner=FakeRunner(), store=store)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        async with app.router.lifespan_context(app):
            return await c.get(path)


def _bell_router():
    r = APIRouter()

    @r.get("/bell/status")
    async def status():
        return {"rings": 3}

    @r.get("/health")
    async def fake_health():
        return {"status": "hijacked"}
    return r


async def test_addon_routes_are_mounted(store):
    addons.use([Addon("bell", router=_bell_router())])
    assert (await _get(store, "/api/bell/status")).json() == {"rings": 3}


async def test_route_clash_is_refused(store):
    from fastapi.routing import APIRoute

    from odie.app.main import create_app
    from tests.test_api import FakeRunner
    addons.use([Addon("bell", router=_bell_router())])
    from odie.app.main import mount_addon_routes
    app = create_app(runner=FakeRunner(), store=store)
    mounted = []
    monkey = type(app)
    real = monkey.include_router

    def spy(self, router, **kw):
        mounted.extend((sorted(r.methods), kw.get("prefix", "") + r.path) for r in router.routes if isinstance(r, APIRoute))
        return real(self, router, **kw)
    monkey.include_router = spy
    try:
        mount_addon_routes(app)
    finally:
        monkey.include_router = real
    assert mounted == [(["GET"], "/api/bell/status")]  # the add-on's /health is refused, its other route kept
    assert (await _get(store, "/api/health")).json()["status"] == "ok"


async def _ding(store, runner):
    return None


async def test_addon_jobs_are_scheduled_and_listed(store, no_missed_brief):
    from odie.app.main import start_scheduler
    from odie.background import Background
    addons.use([Addon("bell", jobs=[Job("bell_check", _ding, {"minute": "5"}, "Doorbell battery checked hourly at :05")])])
    sched = start_scheduler(store, background=Background())
    try:
        job = sched.get_job("bell_check")
        import asyncio
        assert job is not None and asyncio.iscoroutinefunction(job.func)
        assert about.schedule()["bell_check"] == "Doorbell battery checked hourly at :05"
        assert {j.id for j in sched.get_jobs()} - {"news_now", "background_now"} == set(about.schedule())
    finally:
        sched.shutdown(wait=False)


async def test_a_failing_job_is_contained(store):
    from odie.app.main import addon_job

    async def boom(s, r):
        raise RuntimeError("bell offline")
    await addon_job(Job("bell_check", boom, {"minute": "5"}, "x"), store, None)()


async def test_job_id_clash_is_refused(store):
    from odie.app.main import start_scheduler
    addons.use([Addon("bell", jobs=[Job("brief", _ding, {"minute": "5"}, "Not the brief")])])
    sched = start_scheduler(store)
    try:
        assert sched.get_job("brief").func is not _ding and about.schedule()["brief"].startswith("Morning brief")
    finally:
        sched.shutdown(wait=False)


def test_addon_abilities_in_about():
    addons.use([Addon("bell", abilities=[("Doorbell", ("ring_doorbell",), "ring it and see who's there")])])
    assert ("Doorbell", ("ring_doorbell",), "ring it and see who's there") in about.abilities()
    assert about.abilities()[: len(about.ABILITIES)] == about.ABILITIES


async def test_health_merges_connections(store):
    async def conns():
        return {"doorbell": True}
    addons.use([Addon("bell", connections=conns)])
    assert (await _get(store, "/api/health")).json()["connections"]["doorbell"] is True


async def test_brief_parts_and_guidance(store, monkeypatch):
    from odie.jobs import brief as b

    async def parts(s, now, post):
        return [BriefPart("bell", "Doorbell log", "Rang twice overnight"), BriefPart("garden", "Garden sensor", None)]

    async def bad(s, now, post):
        raise RuntimeError("sensor down")
    addons.use([Addon("bell", brief=parts, brief_guidance=["Mention the doorbell only if it rang."]), Addon("bad", brief=bad)])
    inp = await b.gather_inputs(store, NOW)
    assert [p.key for p in inp.parts] == ["bell", "garden"]
    text = b.render_prompt(NOW, inp)
    assert "Doorbell log:\nRang twice overnight" in text and "Garden sensor:\n(not connected yet)" in text
    assert text.index("Doorbell log") > text.index("Needs the user")
    assert "Mention the doorbell only if it rang." in b.brief_system("Asha", b.guidance())
    assert "doorbell" not in b.brief_system("Asha").lower()


async def test_brief_route_reads_calendar_from_parts_and_old_rows(store):
    store.execute("insert into briefs(date, text, items_json) values(?,?,?)",
                  ("2026-10-01", "Old.", json.dumps({"calendar": "Team offsite", "unread": "", "tasks": ""})))
    assert (await _get(store, "/api/brief")).json()["calendar"] == "Team offsite"
    store.execute("insert into briefs(date, text, items_json) values(?,?,?)",
                  ("2026-10-02", "New.", json.dumps({"tasks": "", "ledger": "", "parts": {"calendar": "Dentist 10:00"}})))
    assert (await _get(store, "/api/brief")).json()["calendar"] == "Dentist 10:00"


async def test_brief_stores_its_parts(store, monkeypatch):
    from odie.jobs import brief as b

    async def parts(s, now, post):
        return [BriefPart("bell", "Doorbell log", "Rang twice")]

    async def writer(prompt, s=None):
        return "All quiet."
    addons.use([Addon("bell", brief=parts)])
    monkeypatch.setattr(b, "write_with_model", writer)
    real = b.gather_inputs

    async def gather(s, now, post_message=None):
        return await real(s, now, post_message=post_message)
    monkeypatch.setattr(b, "gather_inputs", gather)
    await b.run_brief(store, NOW, push=False)
    row = store.one("select items_json from briefs order by id desc limit 1")
    assert json.loads(row["items_json"])["parts"] == {"bell": "Rang twice"}


async def test_upcoming_merges_addon_sources(store):
    from odie import upcoming

    async def bell(s, now, days):
        return ([upcoming._item("task", "b1", "Doorbell service", "2026-10-03", now.date())], {"doorbell": True})

    async def bad(s, now, days):
        raise RuntimeError("down")

    addons.use([Addon("bell", upcoming=bell), Addon("bad", upcoming=bad)])
    out = await upcoming.build(store, NOW)
    assert any(i["title"] == "Doorbell service" for i in out["items"])
    assert out["sources"]["doorbell"] is True and "bad" not in out["sources"]


def test_thread_hint_from_addon():
    from odie.agent.prompt import format_open_threads
    addons.use([Addon("bell", thread_hints={"doorbell": lambda r: f" · source: doorbell log (details: bell_log {r['source_ref']})"})])
    row = {"id": 4, "kind": "todo", "title": "Fix the bell", "due_at": None, "source_kind": "doorbell", "source_ref": "77", "detail": None}
    assert format_open_threads([row]).endswith(" · source: doorbell log (details: bell_log 77)")


def test_a_raising_thread_hint_falls_back():
    from odie.agent.prompt import format_open_threads

    def bad(r):
        raise KeyError("x")
    addons.use([Addon("bell", thread_hints={"doorbell": bad})])
    row = {"id": 4, "kind": "todo", "title": "Fix the bell", "due_at": None, "source_kind": "doorbell", "source_ref": "77", "detail": None}
    assert format_open_threads([row]).startswith("#4 [todo] Fix the bell")


async def test_start_hook_runs_once(store):
    calls = []
    addons.use([Addon("bell", start=lambda: calls.append(1))])
    await _get(store, "/api/health")
    assert calls == [1]


async def test_two_addons_with_the_same_route_mount_it_once(store):
    from fastapi.routing import APIRoute

    from odie.app.main import create_app, mount_addon_routes
    from tests.test_api import FakeRunner
    addons.use([Addon("bell", router=_bell_router()), Addon("chime", router=_bell_router())])
    app = create_app(runner=FakeRunner(), store=store)
    mounted = []
    cls = type(app)
    real = cls.include_router

    def spy(self, router, **kw):
        mounted.extend(kw.get("prefix", "") + r.path for r in router.routes if isinstance(r, APIRoute))
        return real(self, router, **kw)
    cls.include_router = spy
    try:
        mount_addon_routes(app)
    finally:
        cls.include_router = real
    assert mounted == ["/api/bell/status"]


async def test_an_addon_job_with_a_bad_trigger_doesnt_stop_the_scheduler(store):
    from odie.app.main import start_scheduler
    addons.use([Addon("bell", jobs=[Job("bell_check", _ding, {"minute": "every so often"}, "x")]),
                Addon("chime", jobs=[Job("chime_check", _ding, {"minute": "5"}, "Chime checked at :05")])])
    sched = start_scheduler(store)
    try:
        assert sched.get_job("brief") is not None and sched.get_job("chime_check") is not None
        assert sched.get_job("bell_check") is None
    finally:
        sched.shutdown(wait=False)


async def test_an_addon_router_that_isnt_one_doesnt_stop_the_app(store):
    addons.use([Addon("bell", router="nope")])
    assert (await _get(store, "/api/health")).json()["status"] == "ok"


async def test_upcoming_item_with_a_new_source(store):
    from odie import upcoming

    async def bell(s, now, days):
        return ([upcoming._item("doorbell", "b1", "Doorbell service", "2026-10-03", now.date())], {"doorbell": True})
    addons.use([Addon("bell", upcoming=bell)])
    out = await upcoming.build(store, NOW)
    assert [i["title"] for i in out["items"] if i["source"] == "doorbell"] == ["Doorbell service"]
