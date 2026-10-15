import asyncio

import httpx
import pytest

from odie.app.events import EventBus
from odie.app.main import create_app
from odie.app.runner import OdieRunner
from odie.jobs.reminders import run_due
from odie.store.db import Store


async def test_event_bus_fan_out():
    bus = EventBus()
    got = []

    async def listen():
        async for e in bus.subscribe():
            got.append(e)
            if len(got) == 2:
                break
    t = asyncio.create_task(listen())
    await asyncio.sleep(0)
    await bus.publish({"type": "message", "text": "a"})
    await bus.publish({"type": "task", "id": 1})
    await asyncio.wait_for(t, 2)
    assert [e["type"] for e in got] == ["message", "task"]


async def test_post_message_lands_in_history_and_bus(isolated_settings, tmp_path):
    s = Store(tmp_path / "assistant.db")
    s.init_schema()
    r = OdieRunner(s)
    seen = []

    async def listen():
        async for e in r.bus.subscribe():
            seen.append(e)
            break
    t = asyncio.create_task(listen())
    await asyncio.sleep(0)
    ev = await r.post_message("Reminder: call the dentist.", session_id="chat-2026-10-01")
    await asyncio.wait_for(t, 2)
    assert ev.author == "odie"
    h = (await r.history("2026-10-01"))["items"]
    assert h[-1]["role"] == "odie" and h[-1]["text"] == "Reminder: call the dentist." and h[-1]["ts"] > 0
    assert seen[0]["type"] == "message" and seen[0]["text"].startswith("Reminder")
    await r.close()


async def test_run_due_posts_once_and_pushes(tmp_path, monkeypatch):
    import odie.jobs.reminders as rem
    s = Store(tmp_path / "a.db")
    s.init_schema()
    tid = s.add_task("Call dentist", "reminder", due_at="2026-10-01T11:00:00+05:30")
    noticed, pushed = [], []

    class FakeRunner:
        async def notify(self, text, task_id, media=None):
            noticed.append((text, task_id))
    monkeypatch.setattr(rem, "send_to_all", lambda store, title, body, url="/", tag=None: pushed.append(body) or 1)
    assert await run_due(s, FakeRunner(), "2026-10-01T11:00:30+05:30") == 1
    assert await run_due(s, FakeRunner(), "2026-10-01T11:05:00+05:30") == 0
    assert len(noticed) == 1 and "Call dentist" in noticed[0][0] and noticed[0][1] == tid and pushed == [noticed[0][0]]
    assert s.one("select delivered_at from tasks where id=?", (tid,))["delivered_at"]
    assert [r["id"] for r in s.pending_notices()] == [tid]  # the curtain shows it until it's answered


class FakeRunner:
    async def chat(self, text, thinking=False, session_id=None):
        if False:
            yield None

    async def history(self, date, limit=None, before=None):
        return {"items": [], "total": 0, "start": 0}

    async def post_message(self, text, session_id=None, media=None):
        FakeRunner.posted = (text, media)

    async def close(self):
        pass


@pytest.fixture
async def client(isolated_settings, tmp_path):
    s = Store(tmp_path / "assistant.db")
    s.init_schema()
    app = create_app(runner=FakeRunner(), store=s)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        async with app.router.lifespan_context(app):
            yield c, s


async def test_task_routes_done_and_snooze(client):
    c, s = client
    tid = s.add_task("Pay Electricity", "reminder", due_at="2026-10-12")
    rows = (await c.get("/api/tasks")).json()
    assert rows[0]["id"] == tid and rows[0]["status"] == "open"
    r = await c.post(f"/api/tasks/{tid}/snooze", json={"until": "2099-01-01T09:00"})
    assert r.status_code == 200 and (await c.get("/api/tasks")).json() == []
    r = await c.post(f"/api/tasks/{tid}/done")
    assert r.status_code == 200 and s.one("select status from tasks where id=?", (tid,))["status"] == "done"
    assert (await c.post("/api/tasks/999/done")).status_code == 404


async def test_delivered_reminders_close_themselves(tmp_path, monkeypatch):
    import odie.jobs.reminders as rem
    s = Store(tmp_path / "a.db")
    s.init_schema()
    ping = s.add_task("Stretch", "reminder", due_at="2026-10-01T07:13:00+05:30")
    follow = s.add_task("Chase Rahul", "followup", next_check_at="2026-10-01T07:13:00+05:30")

    class R:
        async def notify(self, text, task_id, media=None):
            pass
    monkeypatch.setattr(rem, "send_to_all", lambda *a, **k: 0)
    await run_due(s, R(), "2026-10-01T07:14:00+05:30")
    # Both wait on the curtain now: a ping closes when the user acts on it (routes: /reminders/{id}/act), not on delivery.
    assert s.one("select status from tasks where id=?", (ping,))["status"] == "open"
    assert s.one("select status, delivered_at from tasks where id=?", (follow,))["status"] == "open"  # a follow-up waits for you
    assert {r["id"] for r in s.pending_notices()} == {ping, follow}
    s.mark_seen(ping)
    assert [r["id"] for r in s.pending_notices()] == [follow]  # dismissed: off the curtain, still open on Today


async def test_reminder_routes_act_and_dismiss(client):
    """Act posts the reminder into the chat and closes a timed ping; Dismiss only takes it off the curtain."""
    c, store = client
    ping = store.add_task("Pay the fees", "reminder", due_at="2026-10-01T18:00:00+05:30")
    follow = store.add_task("Chase Rahul", "followup", next_check_at="2026-10-01T18:00:00+05:30")
    store.mark_delivered(ping); store.mark_delivered(follow)
    pending = (await c.get("/api/reminders/pending")).json()
    assert [p["id"] for p in pending] == [ping, follow] and pending[0]["text"] == "Reminder: Pay the fees"
    assert (await c.post(f"/api/reminders/{ping}/act")).json()["text"] == "Reminder: Pay the fees"
    assert FakeRunner.posted == ("Reminder: Pay the fees", None)  # Act is what puts it in the chat
    assert store.one("select status, seen_at from tasks where id=?", (ping,))["status"] == "done"
    assert (await c.post(f"/api/reminders/{follow}/dismiss")).json() == {"ok": True}
    row = store.one("select status, seen_at from tasks where id=?", (follow,))
    assert row["status"] == "open" and row["seen_at"]
    assert (await c.get("/api/reminders/pending")).json() == []
    assert (await c.post("/api/reminders/999/act")).status_code == 404
