"""The watch's card and a loop's card on Pulse, Done and the seen marker, the brief's part, and Up next."""
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
    report.save_card(s, DAY, "1 new email", events, {})
    from odie.loops import ledger
    ledger.open_loop(s, "", DAY, "Invoice due Friday", "bill", owner="you", refs=["mail:m1"], state="ready",
                     result="₹2,480", source="mail", ref="mail:m1", fact="Invoice")
    assert mails  # the check read it; stage 2 made it a loop
    return s


async def test_card_done_and_seen(isolated_settings, store):
    from odie.app.main import create_app
    from tests.test_api import FakeRunner
    app = create_app(runner=FakeRunner(), store=store)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        async with app.router.lifespan_context(app):
            got = (await c.get("/api/watch")).json()
            assert got["line"] == "1 new email" and got["unseen"] == 1 and got["needs_you"] == []
            assert (await c.post("/api/watch/seen")).status_code == 200
            assert (await c.get("/api/watch")).json()["unseen"] == 0
            await c.post("/api/watch/done", json={"ref": "mail:m1"})  # an older app's Done names the mail
            assert (await c.get("/api/needs_you")).json()["items"] == []
    from odie.loops import ledger
    assert ledger.get(store, 1)["closed_by"] == "you"


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



async def test_a_loops_done_and_sundays_drop_go_through_watch_done(isolated_settings, store):
    from odie.app.main import create_app
    from odie.loops import ledger
    from tests.test_api import FakeRunner
    app = create_app(runner=FakeRunner(), store=store)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        async with app.router.lifespan_context(app):
            assert (await c.post("/api/watch/done", json={"ref": "loop:1"})).json()["ok"] is True
            assert (await c.post("/api/watch/done", json={"ref": "batch:sunday"})).json()["dropped"] == 0
    assert ledger.get(store, 1)["state"] == "closed" and ledger.get(store, 1)["closed_by"] == "you"


async def test_needs_you_serves_the_cards_and_the_checks_footer(isolated_settings, store):
    from odie.app.main import create_app
    from tests.test_api import FakeRunner
    store.add_task("Renew passport", "reminder", due_at="2026-10-30T09:00:00+05:30")
    app = create_app(runner=FakeRunner(), store=store)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        async with app.router.lifespan_context(app):
            got = (await c.get("/api/needs_you")).json()
    assert [i["title"] for i in got["items"]] == ["Invoice due Friday", "Renew passport"]
    assert got["watch"]["line"] == "1 new email" and "checked_at" in got["watch"]
    assert set(got) == {"items", "counts", "watch", "notes", "on_it", "loops_done", "jobs_done", "others"}  # Pulse (18 Nov)
    assert sum(got["counts"].values()) == len(got["items"]) and set(got["counts"]) == set(report.PILES)


async def test_later_hides_a_card_till_the_next_morning_and_done_takes_it_off(isolated_settings, store):
    # The three buttons on every card: Later hides it (a watch item or a task) until 09:00 tomorrow; Done takes it off.
    from odie.app.main import create_app
    from tests.test_api import FakeRunner
    tid = store.add_task("Renew passport", "todo")
    app = create_app(runner=FakeRunner(), store=store)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        async with app.router.lifespan_context(app):
            [loop_card, task_card] = (await c.get("/api/needs_you")).json()["items"]
            assert loop_card["later"] == {"label": "Later", "action": "later", "value": "loop:1"}
            assert task_card["later"] == {"label": "Later", "action": "later", "value": f"task:{tid}"}
            for ref in ("loop:1", f"task:{tid}"):
                got = await c.post("/api/needs_you/later", json={"ref": ref})
                assert got.status_code == 200 and got.json()["until"].endswith("T09:00:00+05:30")
            assert (await c.get("/api/needs_you")).json()["items"] == []
            assert (await c.get("/api/watch")).json()["unseen"] == 0  # a hidden item isn't counted as new
            assert (await c.post("/api/needs_you/later", json={"ref": "mail:gone"})).status_code == 404
