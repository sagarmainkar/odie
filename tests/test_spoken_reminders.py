"""Spoken reminders: with Settings → Voice → Speak reminders on, a reminder arrives as a voice memo in the chosen
voice (and its text); the memo stays with the message in history, and the model never sees it. Off by default; a
reminder still goes out as text if speaking fails."""
import asyncio
import json

import httpx
import pytest

from odie import media, voice
from odie.app.runner import OdieRunner
from odie.jobs import reminders as rem
from odie.store.db import Store
from tests.test_media import make_wav

DUE, NOW = "2026-10-07T11:00:00+05:30", "2026-10-07T11:00:30+05:30"


@pytest.fixture
def store(isolated_settings, tmp_path, monkeypatch):
    s = Store(tmp_path / "assistant.db")
    s.init_schema()
    monkeypatch.setattr(rem, "send_to_all", lambda *a, **k: 1)
    return s


class Posts:
    """The runner as the reminder job sees it: a notice per fired reminder (text, media), kept in `posted`."""
    def __init__(self):
        self.posted = []

    async def notify(self, text, task_id, media=None):
        self.posted.append((text, media))


def kokoro(seen):
    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, content=make_wav(1.0))
    return httpx.MockTransport(handler)


def down():
    def handler(request):
        raise httpx.ConnectError("refused")
    return httpx.MockTransport(handler)


async def test_reminders_are_text_unless_spoken(store):
    store.add_task("Stretch", "reminder", due_at=DUE)
    r = Posts()
    assert await rem.run_due(store, r, NOW, transport=down()) == 1  # the voice is never asked
    assert r.posted == [("Reminder: Stretch", None)]


async def test_spoken_reminders(store):
    voice.set_reminders_spoken(store, True)
    store.add_task("Stretch", "reminder", due_at=DUE)
    seen, r = [], Posts()
    await rem.run_due(store, r, NOW, transport=kokoro(seen))
    [(text, made)] = r.posted
    assert text == "Reminder: Stretch" and seen[0]["text"] == "Reminder: Stretch" and seen[0]["voice"] == "af_heart"
    assert made[0]["kind"] == "memo" and made[0]["transcript"] == "Reminder: Stretch" and media.get(made[0]["id"])


async def test_a_reminder_still_goes_out_when_speaking_fails(store):
    voice.set_reminders_spoken(store, True)
    store.add_task("Stretch", "reminder", due_at=DUE)
    r = Posts()
    assert await rem.run_due(store, r, NOW, transport=down()) == 1
    assert r.posted == [("Reminder: Stretch", None)]


async def test_post_message_keeps_its_media(store):
    m = media.save(make_wav(1.0), "memo", "wav", "audio/wav", "Reminder: Stretch", {"duration": 1.0, "transcript": "Reminder: Stretch"})
    r = OdieRunner(store)
    seen = []

    async def listen():
        async for e in r.bus.subscribe():
            seen.append(e)
            break
    t = asyncio.create_task(listen())
    await asyncio.sleep(0)
    ev = await r.post_message("Reminder: Stretch", session_id="chat-2026-10-07", media=[m])
    await asyncio.wait_for(t, 2)
    assert seen[0]["media"] == [m] and seen[0]["text"] == "Reminder: Stretch"
    assert [p.text for p in ev.content.parts] == ["Reminder: Stretch"]  # the model sees the words, not the memo
    [item] = (await r.history("2026-10-07"))["items"]
    assert item["text"] == "Reminder: Stretch" and item["media"] == [m]
    await r.close()
    again = OdieRunner(store)  # a restart: read back from SQLite
    [item] = (await again.history("2026-10-07"))["items"]
    assert item["media"][0]["id"] == m["id"]
    await again.close()


async def test_the_voice_route_has_the_setting(store, monkeypatch):
    from odie.app.main import create_app
    from tests.test_api import FakeRunner

    async def offline(transport=None):
        return False
    monkeypatch.setattr(voice, "local_available", offline)
    app = create_app(runner=FakeRunner(), store=store)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c, app.router.lifespan_context(app):
        assert (await c.get("/api/voice")).json()["reminders_spoken"] is False
        assert (await c.put("/api/voice", json={"reminders_spoken": True})).status_code == 200
        assert (await c.get("/api/voice")).json()["reminders_spoken"] is True
        assert voice.get_tts(store)[0] == "kokoro"  # the engine is untouched


async def test_a_slow_voice_doesnt_hold_reminders_up(store, monkeypatch):
    import time
    voice.set_reminders_spoken(store, True)
    monkeypatch.setattr(rem, "SPEAK_WITHIN", 0.3)
    pushed = []
    monkeypatch.setattr(rem, "send_to_all", lambda store, title, body, url="/", tag=None: pushed.append(body) or 1)

    async def stalled(request):
        await asyncio.sleep(3)
        return httpx.Response(200, content=make_wav(1.0))
    store.add_task("Stretch", "reminder", due_at=DUE)
    store.add_task("Drink water", "reminder", due_at=DUE)
    r = Posts()
    start = time.monotonic()
    assert await rem.run_due(store, r, NOW, transport=httpx.MockTransport(stalled)) == 2
    assert time.monotonic() - start < 1.5  # each waited at most the bound, then went out as text
    assert sorted(t for t, m in r.posted) == ["Reminder: Drink water", "Reminder: Stretch"] and all(m is None for _, m in r.posted)
    assert sorted(pushed) == ["Reminder: Drink water", "Reminder: Stretch"]


async def test_an_unexpected_error_speaking_still_sends_the_reminder(store, monkeypatch):
    voice.set_reminders_spoken(store, True)

    async def broken(*a, **k):
        raise RuntimeError("something odd")
    monkeypatch.setattr(voice, "speak_wav", broken)
    store.add_task("Stretch", "reminder", due_at=DUE)
    r = Posts()
    assert await rem.run_due(store, r, NOW) == 1 and r.posted == [("Reminder: Stretch", None)]
