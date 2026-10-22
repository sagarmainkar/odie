"""The card on Today, Done and the seen marker, the brief's part, and Up next."""
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
import pytest

from odie.store.db import Store
from odie.watch import report
from odie.watch.fetch import Event, Mail

DAY = datetime(2026, 10, 8, 10, 0, tzinfo=ZoneInfo("Asia/Kolkata"))


@pytest.fixture
def store(isolated_settings, tmp_path):
    s = Store(tmp_path / "a.db")
    s.init_schema()
    mails = [Mail("m1", "a@b.c", "Invoice", "t", "s", [], "mail:z")]
    events = [Event("e1", "Standup", "2026-10-08T15:00:00+05:30", "", "", [], "calendar:z", "new")]
    report.apply(s, DAY, [{"ref": "mail:m1", "title": "Invoice due Friday", "why": "₹2,480", "push": False}], "1 new email", mails, events, {}, first=True)
    return s


async def test_card_done_and_seen(isolated_settings, store):
    from odie.app.main import create_app
    from tests.test_api import FakeRunner
    app = create_app(runner=FakeRunner(), store=store)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        async with app.router.lifespan_context(app):
            got = (await c.get("/api/watch")).json()
            assert got["line"] == "1 new email" and got["unseen"] == 1 and got["needs_you"][0]["title"] == "Invoice due Friday"
            assert (await c.post("/api/watch/seen")).status_code == 200
            assert (await c.get("/api/watch")).json()["unseen"] == 0
            await c.post("/api/watch/done", json={"ref": "mail:m1"})
            assert (await c.get("/api/watch")).json()["needs_you"] == []


async def test_the_brief_reads_the_last_check(store):
    from odie.jobs.brief import gather_inputs, render_prompt
    store.set_setting(report.HELD, [{"ref": "mail:m9", "title": "Passport email came", "why": "at 23:10"}])
    inp = await gather_inputs(store, DAY)
    text = render_prompt(DAY, inp)
    assert "Invoice due Friday" in text and "Passport email came" in text and "Standup" in text
    assert store.get_setting(report.HELD) == []  # said once


async def test_up_next_has_the_watchs_events(store):
    from odie import upcoming
    got = await upcoming.build(store, DAY)
    assert any(i.get("title") == "Standup" for i in got["items"])



async def test_dismissing_on_today_closes_the_watchs_thread(isolated_settings, store):
    from odie.app.main import create_app
    from odie.watch import threads
    from tests.test_api import FakeRunner
    threads.track(store, "mail:m1", "reply", "Reply: invoice", "owed")
    app = create_app(runner=FakeRunner(), store=store)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        async with app.router.lifespan_context(app):
            await c.post("/api/watch/done", json={"ref": "mail:m1"})
    assert threads.open_refs(store) == set()
