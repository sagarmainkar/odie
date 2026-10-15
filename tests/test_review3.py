import asyncio
from zoneinfo import ZoneInfo

from odie.app.events import EventBus
from odie.app.runner import OdieRunner
from odie.store.db import Store

IST = ZoneInfo("Asia/Kolkata")


async def test_post_message_waits_for_in_flight_turn(isolated_settings, tmp_path):
    """C1: a reminder must not append to the session while a chat turn is running (StaleSessionError)."""
    s = Store(tmp_path / "assistant.db")
    s.init_schema()
    r = OdieRunner(s)
    gate = asyncio.Event()
    order = []

    async def fake_run(**kw):
        order.append("turn-start")
        await gate.wait()
        order.append("turn-end")
        if False:
            yield None
    r.runner.run_async = fake_run
    sid = r.current_session_id("2026-10-01")

    async def turn():
        return [e async for e in r.chat("hi", session_id=sid)]

    async def reminder():
        await asyncio.sleep(0.05)
        await r.post_message("Reminder: stretch", session_id=sid)
        order.append("posted")
    t1 = asyncio.create_task(turn())
    t2 = asyncio.create_task(reminder())
    await asyncio.sleep(0.2)
    assert order == ["turn-start"], order  # reminder is queued, not interleaved
    gate.set()
    await asyncio.gather(t1, t2)
    assert order == ["turn-start", "turn-end", "posted"]
    await r.close()


async def test_event_bus_queue_api_survives_idle_timeout():
    """I1: the /api/events pattern (wait_for on a queue) must not unsubscribe on timeout."""
    bus = EventBus()
    q = bus.queue()
    try:
        await asyncio.wait_for(q.get(), 0.01)
    except asyncio.TimeoutError:
        pass
    await bus.publish({"type": "task"})
    assert (await asyncio.wait_for(q.get(), 1))["type"] == "task"
    bus.release(q)
    assert q not in bus._subs


def test_times_are_local_and_comparable(tmp_path):
    """I3: everything compared as text must carry the user's offset."""
    from odie.agent.tools.local import parse_when
    from odie.store.db import local_now_iso
    assert parse_when("2026-10-02T09:00", IST) == "2026-10-02T09:00+05:30"
    assert parse_when("2026-10-02T03:30:00Z", IST) == "2026-10-02T09:00+05:30"
    assert parse_when("2026-10-02", IST) == "2026-10-02T09:00+05:30"  # bare date = 9 am
    assert local_now_iso().endswith("+05:30")
    s = Store(tmp_path / "a.db")
    s.init_schema()
    tid = s.add_task("x", "reminder", due_at="2026-10-02T09:00+05:30")
    s.snooze_task(tid, "2026-10-02T09:00+05:30")
    assert all(t["id"] != tid for t in s.open_tasks("2026-10-02T08:59+05:30"))
    assert any(t["id"] == tid for t in s.open_tasks("2026-10-02T09:01+05:30"))
