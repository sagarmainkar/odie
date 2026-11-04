import asyncio
from datetime import UTC, datetime

from odie.app.main import start_scheduler
from odie.store.db import Store


async def test_brief_job_is_a_coroutine_function(tmp_path):
    s = Store(tmp_path / "a.db")
    s.init_schema()
    # A fresh news batch, so the "fetch now if stale" job doesn't reach the network from a test.
    s.set_setting("news", {"fetched_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), "topics": [], "items": []})
    from odie.background import Background
    sched = start_scheduler(s, background=Background())
    try:
        for jid in ("brief", "reminders", "expiry", "news", "background", "background_now"):
            job = sched.get_job(jid)
            assert job is not None and asyncio.iscoroutinefunction(job.func), f"{jid}: APScheduler only awaits coroutine functions"
        class R:
            async def post_message(self, text, session_id=None):
                pass
        sched2 = start_scheduler(s, R(), Background())
        # "brief_missed" is set aside: it is added only when Odie starts owing a round (between 07:30 and noon with no
        # brief yet today, or from 05:00 with no hello yet today).
        assert {j.id for j in sched2.get_jobs()} - {"brief_missed"} == {"brief", "reminders", "expiry", "news", "background", "background_now"}
        sched2.shutdown(wait=False)
    finally:
        sched.shutdown(wait=False)


async def test_stale_news_is_fetched_at_startup_even_if_startup_is_slow(tmp_path, monkeypatch):
    import odie.news.fetch as nf

    async def no_network(store, transport=None, now=None):
        return nf.news_batch(store)
    monkeypatch.setattr(nf, "refresh_news", no_network)
    s = Store(tmp_path / "a.db")
    s.init_schema()  # no news yet: stale
    sched = start_scheduler(s)
    try:
        job = sched.get_job("news_now")
        assert job is not None and (job.misfire_grace_time is None or job.misfire_grace_time >= 300)
    finally:
        sched.shutdown(wait=False)


def a_store_with_fresh_news(tmp_path) -> Store:
    db_path = tmp_path / "a.db"
    assert db_path.parent == tmp_path
    s = Store(db_path)
    s.init_schema()
    s.set_setting("news", {"fetched_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), "topics": [], "items": []})
    return s


async def test_an_owed_hello_is_made_soon_after_startup(tmp_path, monkeypatch):
    """No brief owed (an afternoon start) but no hello yet today: the catch-up job is set for two minutes on."""
    import odie.jobs.brief as b
    import odie.morning.round as r
    s = a_store_with_fresh_news(tmp_path)
    monkeypatch.setattr(b, "missed_today", lambda store, now: False)
    monkeypatch.setattr(r, "hello_due", lambda store, now: True)
    sched = start_scheduler(s)
    try:
        assert sched.get_job("brief_missed") is not None
    finally:
        sched.shutdown(wait=False)
    monkeypatch.setattr(r, "hello_due", lambda store, now: False)
    sched = start_scheduler(s)
    try:
        assert sched.get_job("brief_missed") is None
    finally:
        sched.shutdown(wait=False)


async def test_the_seven_thirty_job_runs_the_morning_round(tmp_path, monkeypatch):
    import odie.morning.round as r
    s = a_store_with_fresh_news(tmp_path)
    rounds = []

    async def fake_round(store, now, runner=None, push=True):
        rounds.append((store, runner))
    monkeypatch.setattr(r, "morning_round", fake_round)
    from odie.background import Background
    runner = object()
    sched = start_scheduler(s, runner, Background())
    try:
        await sched.get_job("brief").func()
    finally:
        sched.shutdown(wait=False)
    assert rounds == [(s, runner)]
