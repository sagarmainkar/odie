"""GET /api/morning: today's hello for the web card and the Mac app."""
import asyncio
import json
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
import pytest

from odie.app import routes
from odie.app.main import create_app
from odie.morning import round as round_mod
from odie.store.db import Store

IST = ZoneInfo("Asia/Kolkata")
CARD = {"greeting": "Morning, Asha", "accent": "launch", "emoji": "", "say": ["Two days to go."], "tiles": [],
        "nudge": None, "mail": [], "recent": [], "chips": ["Plan my day"], "summary": "The day: a launch.",
        "weather": None, "day": "2026-11-04", "made_at": "2026-11-04T07:30:00+05:30", "fallback": False}


class QuietRunner:
    async def close(self):
        pass


@pytest.fixture
async def morning(isolated_settings, tmp_path, monkeypatch):
    """(client, store, clock, app) on an isolated store with a chat model chosen; clock["now"] is what the route reads."""
    assert tmp_path in isolated_settings.data_dir.parents or isolated_settings.data_dir == tmp_path
    monkeypatch.setattr(round_mod, "user_tz", lambda: IST)  # the owner's zone, whatever the machine's is
    store = Store(tmp_path / "assistant.db")
    store.init_schema()
    store.set_setting("model.chat", {"provider": "lmstudio", "model": "test-model"})
    clock = {"now": datetime(2026, 11, 4, 9, 0, tzinfo=IST)}
    monkeypatch.setattr(routes, "morning_now", lambda: clock["now"])
    monkeypatch.setattr(routes, "_morning_tasks", set())
    monkeypatch.setattr(routes, "_round_failed_at", None)
    app = create_app(runner=QuietRunner(), store=store)
    async with (httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c,
                app.router.lifespan_context(app)):
        yield c, store, clock, app


def save_hello(store: Store, day: str = "2026-11-04") -> None:
    store.execute("insert into mornings(day, card_json, summary, made_at) values(?,?,?,?)",
                  (day, json.dumps(CARD), CARD["summary"], CARD["made_at"]))


async def test_morning_ready_returns_the_card_without_the_summary(morning):
    client, store, _, _ = morning
    save_hello(store)
    body = (await client.get("/api/morning")).json()
    assert body["state"] == "ready" and body["day"] == "2026-11-04"
    assert "summary" not in body["card"]
    assert body["card"]["greeting"] == "Morning, Asha"
    assert body["card"]["day"] == "2026-11-04" and body["card"]["made_at"] == CARD["made_at"]
    assert "weather" in body["card"]


async def test_morning_due_starts_one_round_and_says_making(morning, monkeypatch):
    client, _, _, _ = morning
    started = []
    release = asyncio.Event()

    async def fake_round(store, now, runner=None, push=True):
        started.append(now)
        await release.wait()

    monkeypatch.setattr(routes, "morning_round", fake_round)
    first = (await client.get("/api/morning")).json()
    await asyncio.sleep(0)  # let the task begin
    second = (await client.get("/api/morning")).json()
    assert first == {"state": "making", "day": "2026-11-04", "card": None}
    assert second["state"] == "making"
    assert len(started) == 1
    release.set()
    await asyncio.sleep(0.01)
    assert routes._morning_tasks == set()  # the finished task let go


async def test_morning_is_making_while_a_round_from_elsewhere_runs(morning, monkeypatch):
    client, _, _, _ = morning
    started = []

    async def fake_round(store, now, runner=None, push=True):
        started.append(now)

    monkeypatch.setattr(routes, "morning_round", fake_round)
    monkeypatch.setattr(routes, "round_running", lambda: True)  # the 07:30 cron holds the lock
    assert (await client.get("/api/morning")).json()["state"] == "making"
    assert started == []


async def test_morning_before_five_is_none(morning, monkeypatch):
    client, _, clock, _ = morning
    started = []

    async def fake_round(store, now, runner=None, push=True):
        started.append(now)

    monkeypatch.setattr(routes, "morning_round", fake_round)
    clock["now"] = datetime(2026, 11, 5, 4, 30, tzinfo=IST)
    body = (await client.get("/api/morning")).json()
    assert body == {"state": "none", "day": "2026-11-04", "card": None}
    assert started == []


async def test_morning_with_no_chat_model_is_none(morning, monkeypatch):
    client, store, _, _ = morning
    store.execute("delete from settings where key = 'model.chat'")
    assert (await client.get("/api/morning")).json()["state"] == "none"


async def settle() -> None:
    """Wait for the rounds the route started to finish."""
    await asyncio.gather(*routes._morning_tasks)


async def test_a_failing_round_is_logged_once_and_cools_off(morning, monkeypatch, caplog):
    client, _, clock, _ = morning
    started = []

    async def failing_round(store, now, runner=None, push=True):
        started.append(now)
        raise RuntimeError("model down")

    monkeypatch.setattr(routes, "morning_round", failing_round)
    with caplog.at_level(logging.WARNING, logger="odie.api"):
        assert (await client.get("/api/morning")).json()["state"] == "making"
        await settle()
        failures = [r for r in caplog.records if "failed" in r.getMessage() and r.exc_info]
        assert len(failures) == 1
        assert (await client.get("/api/morning")).json()["state"] == "none"  # inside the cool-off
        assert len(started) == 1

    clock["now"] = datetime(2026, 11, 4, 9, 11, tzinfo=IST)  # 11 minutes on: the cool-off is over
    assert (await client.get("/api/morning")).json()["state"] == "making"
    await settle()
    assert len(started) == 2


def test_retry_allowed_only_after_the_cool_off():
    failed = datetime(2026, 11, 4, 9, 0, tzinfo=IST)
    assert routes.retry_allowed(None, failed)
    assert not routes.retry_allowed(failed, datetime(2026, 11, 4, 9, 3, tzinfo=IST))
    assert routes.retry_allowed(failed, datetime(2026, 11, 4, 9, 11, tzinfo=IST))


async def test_the_web_round_runs_through_the_background_with_the_brief_limit(morning, monkeypatch):
    from odie.app.main import BRIEF_LIMIT
    client, _, _, app = morning
    ran = []
    seen = []

    class FakeBackground:
        async def exclusive(self, part):
            seen.append((part.name, part.limit))
            await part.run()
            return True

        async def stop(self):
            pass

    async def fake_round(store, now, runner=None, push=True):
        ran.append(now)
        save_hello(store)

    app.state.background = FakeBackground()
    monkeypatch.setattr(routes, "morning_round", fake_round)
    assert (await client.get("/api/morning")).json()["state"] == "making"
    await settle()
    assert seen == [("brief", BRIEF_LIMIT)]
    assert len(ran) == 1
    assert (await client.get("/api/morning")).json()["state"] == "ready"
