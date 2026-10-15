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
        assert {j.id for j in sched2.get_jobs()} == {"brief", "reminders", "expiry", "news", "background", "background_now"}
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
