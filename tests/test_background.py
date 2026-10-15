"""The background agent's loop: every tick runs the parts that are due, in order, one at a time; a tick during a tick
does nothing; a part that fails or hangs never stops the next; the brief runs under the same lock; stop() cancels cleanly."""
import asyncio
from datetime import datetime

from odie.background import Background, Part


def recorder(log, name, delay=0.0, fail=False):
    async def run():
        log.append(f"start {name}")
        await asyncio.sleep(delay)
        if fail:
            raise RuntimeError(f"{name} broke")
        log.append(f"end {name}")
    return run


async def test_a_tick_runs_the_due_parts_in_order():
    log = []
    bg = Background([Part("a", recorder(log, "a")), Part("b", recorder(log, "b"), due=lambda now: False), Part("c", recorder(log, "c"))])
    assert await bg.tick() == ["a", "c"]
    assert log == ["start a", "end a", "start c", "end c"]
    st = bg.status()
    assert st["running"] is False and st["last_tick"] and st["parts"]["a"]["last_ok"] and st["parts"]["b"]["last_run"] is None


async def test_a_tick_during_a_tick_does_nothing():
    log = []
    bg = Background([Part("slow", recorder(log, "slow", delay=0.3))])
    first = asyncio.create_task(bg.tick())
    await asyncio.sleep(0.05)
    assert bg.status()["running"] is True
    assert await bg.tick() == []  # not queued behind the first
    assert await first == ["slow"] and log.count("start slow") == 1


async def test_a_failing_part_never_stops_the_next():
    log = []
    bg = Background([Part("bad", recorder(log, "bad", fail=True)), Part("good", recorder(log, "good"))])
    assert await bg.tick() == ["bad", "good"]
    assert "end good" in log and bg.status()["parts"]["bad"]["error"] == "RuntimeError: bad broke"
    assert bg.status()["parts"]["good"]["error"] == ""


async def test_a_part_that_hangs_is_cut_and_the_next_runs():
    log = []
    bg = Background([Part("hang", recorder(log, "hang", delay=5), limit=0.1), Part("next", recorder(log, "next"))])
    assert await bg.tick() == ["hang", "next"]
    assert "end next" in log and "took longer than" in bg.status()["parts"]["hang"]["error"]


async def test_exclusive_waits_for_a_running_tick():
    log = []
    bg = Background([Part("slow", recorder(log, "slow", delay=0.2))])
    tick = asyncio.create_task(bg.tick())
    await asyncio.sleep(0.05)
    assert await bg.exclusive(Part("brief", recorder(log, "brief"))) is True
    await tick
    assert log == ["start slow", "end slow", "start brief", "end brief"]  # never at the same time


async def test_stop_cancels_a_running_tick():
    log = []
    bg = Background([Part("slow", recorder(log, "slow", delay=5))])
    tick = asyncio.create_task(bg.tick())
    await asyncio.sleep(0.05)
    await bg.stop()
    assert await asyncio.wait_for(tick, 1) == ["slow"]  # the tick ends quietly, no exception out of the scheduler
    assert "end slow" not in log
    assert await bg.tick() == [] and await bg.exclusive(Part("x", recorder(log, "x"))) is False


async def test_due_gets_the_time():
    seen = []
    when = datetime(2026, 10, 7, 9, 0)
    bg = Background([Part("p", recorder([], "p"), due=lambda now: seen.append(now) or True)], now=lambda: when)
    await bg.tick()
    assert seen == [when]


async def test_the_scheduler_ticks_the_background_every_5_minutes(isolated_settings, tmp_path):
    from datetime import UTC, datetime as dt

    from odie.app.main import start_scheduler
    from odie.store.db import Store
    s = Store(tmp_path / "a.db")
    s.init_schema()
    s.set_setting("news", {"fetched_at": dt.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), "topics": [], "items": []})  # no network
    bg = Background()
    sched = start_scheduler(s, runner=None, background=bg)
    try:
        ids = {j.id for j in sched.get_jobs()}
        assert "background" in ids and "background_now" in ids and "trackers" not in ids
        assert sched.get_job("background").trigger.interval.total_seconds() == 300
    finally:
        sched.shutdown(wait=False)


async def test_trackers_run_as_a_part(isolated_settings, tmp_path):
    from odie.app.main import background_for
    from odie.store.db import Store
    s = Store(tmp_path / "a.db")
    s.init_schema()
    calls = []

    class Runner:
        async def run_trackers(self):
            calls.append("trackers")
            return 0
    bg = background_for(s, Runner())
    assert [p.name for p in bg.parts] == ["watch", "trackers"] and bg.parts[1].limit > 300  # the watch first; each due tracker gets its 5 minutes
    assert await bg.tick() == ["watch", "trackers"] and calls == ["trackers"]  # the watch is due at once (never checked)


async def test_the_background_route(isolated_settings, tmp_path):
    import httpx

    from odie.app.main import create_app
    from odie.store.db import Store
    from tests.test_api import FakeRunner
    s = Store(tmp_path / "a.db")
    s.init_schema()
    app = create_app(runner=FakeRunner(), store=s)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        async with app.router.lifespan_context(app):
            assert (await c.get("/api/background")).json() == {"running": False, "off": True}  # a test app has no scheduler
            app.state.background = Background([Part("trackers", recorder([], "t"))])
            await app.state.background.tick()
            got = (await c.get("/api/background")).json()
            assert got["running"] is False and got["parts"]["trackers"]["last_ok"] and "next_tick" in got


def test_each_due_tracker_gets_its_own_five_minutes(isolated_settings, tmp_path):
    from odie import trackers
    from odie.app.main import background_for
    from odie.store.db import Store
    s = Store(tmp_path / "a.db")
    s.init_schema()
    part = background_for(s, None).parts[1]
    assert part.name == "trackers" and part.limit >= trackers.PER_RUN * 300  # one run checks up to PER_RUN trackers


def test_the_brief_gets_ten_minutes():
    from odie.app.main import BRIEF_LIMIT
    assert BRIEF_LIMIT >= 600  # gathering plus a 3-minute completion on a slow local model
