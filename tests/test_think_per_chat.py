"""Think harder, one per chat (odie.thinking): kept by Odie and shared by every app, the default following the last
choice; and on a local server the effort never changes (the words go at the end of the turn instead), so the server's
prompt cache survives a flip."""
import asyncio

import httpx
import pytest
from google.adk.events import Event
from google.genai import types

from odie.agent.model import (THINK_HARDER_WORDS, chat_effort_think_harder, completion_args, runs_on_local_server,
                              think_harder_words)
from odie.models import Provider, Selection
from odie.store.db import Store


@pytest.fixture
def store(isolated_settings, tmp_path):
    s = Store(tmp_path / "assistant.db")
    s.init_schema()
    return s


def _sel(provider_id: str, model: str, base: str = "http://127.0.0.1:1234/v1", local: bool = False) -> Selection:
    return Selection(Provider(provider_id, provider_id.title(), base, "sk-test", local), model, "chat")


LMSTUDIO = _sel("lmstudio", "gemma-4-26b-a4b-it-qat", local=True)
CUSTOM = _sel("my-local-server", "qwen3.8-27b", base="http://127.0.0.1:8001/v1")  # added by the user: not marked local
OLLAMA_HERE = _sel("ollama", "gemma3:12b", base="http://localhost:11434/v1", local=True)
OLLAMA_CLOUD = _sel("ollama", "deepseek-v4.1-flash:cloud", base="http://localhost:11434/v1", local=True)
OLLAMA_CLOUD_DASH = _sel("ollama", "glm-5.3-flash-cloud", base="http://localhost:11434/v1", local=True)
OPENAI = _sel("openai", "gpt-5.5", base="https://api.openai.com/v1")


# ── which selections keep one effort ──
@pytest.mark.parametrize("selection, expected", [
    (LMSTUDIO, True),
    (CUSTOM, True),
    (OLLAMA_HERE, True),
    (OLLAMA_CLOUD, False),
    (OLLAMA_CLOUD_DASH, False),
    (OPENAI, False),
    (_sel("anthropic", "claude-sonnet-5-5", base="https://api.anthropic.com/v1"), False),
    (_sel("gemini", "gemini-3-pro", base="https://generativelanguage.googleapis.com/v1beta/openai"), False),
    (_sel("openrouter", "some/model", base="https://openrouter.ai/api/v1"), False),
])
def test_runs_on_local_server(selection, expected):
    assert runs_on_local_server(selection) is expected


def test_a_local_selection_gets_one_effort_and_the_words_only_when_on():
    for sel in (LMSTUDIO, CUSTOM, OLLAMA_HERE):
        on = completion_args(sel, chat_effort_think_harder(sel, True))
        off = completion_args(sel, chat_effort_think_harder(sel, False))
        assert on["reasoning_effort"] == off["reasoning_effort"] == "low"
        assert on == off  # the whole request setup is the same: nothing near the start changes
        assert think_harder_words(sel, True) == "\n" + THINK_HARDER_WORDS
        assert think_harder_words(sel, False) == ""


def test_a_cloud_selection_is_unchanged():
    for sel in (OPENAI, OLLAMA_CLOUD):
        assert completion_args(sel, chat_effort_think_harder(sel, True))["reasoning_effort"] == "medium"
        assert completion_args(sel, chat_effort_think_harder(sel, False))["reasoning_effort"] == "low"
        assert think_harder_words(sel, True) == "" and think_harder_words(sel, False) == ""


# ── the turn itself ──
def _reply(text):
    return Event(author="odie", invocation_id="i", content=types.Content(role="model", parts=[types.Part(text=text)]))


async def _turns(store, monkeypatch, selection, turns):
    """Run each (text, thinking) turn through a real OdieRunner; what each sent and the effort its model had."""
    from odie.app import runner as R
    monkeypatch.setattr(R, "resolve_selection", lambda st, slot: selection)
    r = R.OdieRunner(store)
    seen = []

    async def fake_run(**kw):
        seen.append({"text": kw["new_message"].parts[0].text, "effort": r.agent.model._additional_args["reasoning_effort"],
                     "model": r.agent.model})
        yield _reply("Done.")
    r.runner.run_async = fake_run
    for text, thinking in turns:
        [e async for e in r.chat(text, thinking=thinking, session_id="chat-2026-10-28")]
    await r.close()
    return seen


async def test_a_local_model_keeps_its_effort_and_model_and_gets_the_words_at_the_end(store, monkeypatch):
    from odie.app.runner import strip_trailer
    seen = await _turns(store, monkeypatch, CUSTOM, [("What can you do?", True), ("Make an audio drama", False),
                                                     ("Make it longer", True)])
    assert [s["effort"] for s in seen] == ["low", "low", "low"]
    assert seen[0]["model"] is seen[1]["model"] is seen[2]["model"]  # no swap: the flip doesn't rebuild the model
    first, second, third = (s["text"] for s in seen)
    assert first.endswith(THINK_HARDER_WORDS) and first.count(THINK_HARDER_WORDS) == 1
    assert first.index("[context: ") < first.index(THINK_HARDER_WORDS)  # after everything the cache holds
    assert THINK_HARDER_WORDS not in second
    assert third.endswith(THINK_HARDER_WORDS) and third.startswith("Make it longer")
    assert strip_trailer(first) == "What can you do?"  # the chat's history shows only the user's words


async def test_a_cloud_model_gets_its_effort_and_no_words(store, monkeypatch):
    seen = await _turns(store, monkeypatch, OPENAI, [("What can you do?", True), ("Make an audio drama", False)])
    assert [s["effort"] for s in seen] == ["medium", "low"]
    assert all(THINK_HARDER_WORDS not in s["text"] for s in seen)


async def test_a_turn_without_thinking_uses_the_chats_own(store, monkeypatch):
    from odie import thinking
    thinking.put(store, "chat-2026-10-28", True)
    seen = await _turns(store, monkeypatch, OPENAI, [("What can you do?", None)])
    assert seen[0]["effort"] == "medium"
    thinking.put(store, "chat-2026-10-28", False)
    seen = await _turns(store, monkeypatch, LMSTUDIO, [("And now?", None)])
    assert THINK_HARDER_WORDS not in seen[0]["text"]


# ── the setting ──
def test_each_chat_has_its_own_and_the_default_follows_the_last_change(store):
    from odie import thinking
    assert thinking.get(store, "chat-2026-10-28") is False  # nothing chosen yet: off
    thinking.put(store, "chat-2026-10-28", True)
    assert thinking.get(store, "chat-2026-10-28") is True
    assert thinking.get(store, "chat-2026-10-28-2") is True  # a new chat starts with the last choice
    thinking.put(store, "chat-2026-10-27", False)  # an older chat turned off: that's the default now
    assert thinking.get(store, "chat-2026-10-28") is True  # set chats keep their own
    assert thinking.get(store, "chat-2026-10-29") is False


def test_a_chat_keeps_the_default_it_started_with(store):
    from odie import thinking
    thinking.put(store, "chat-2026-10-27", True)
    assert thinking.settle(store, "chat-2026-10-28") is True  # its first turn: the default, now its own
    thinking.put(store, "chat-2026-10-26", False)
    assert thinking.get(store, "chat-2026-10-28") is True  # another chat's change doesn't flip it halfway
    assert thinking.default(store) is False


def test_only_the_latest_chats_are_kept(store, monkeypatch):
    from odie import thinking
    monkeypatch.setattr(thinking, "KEEP", 3)
    for day in range(1, 6):
        thinking.put(store, f"chat-2026-10-0{day}", day % 2 == 1)
    kept = store.get_setting(thinking.KEY)["chats"]
    assert list(kept) == ["chat-2026-10-03", "chat-2026-10-04", "chat-2026-10-05"]
    thinking.put(store, "chat-2026-10-03", False)  # changed again: now the newest
    assert list(store.get_setting(thinking.KEY)["chats"])[-1] == "chat-2026-10-03"


# ── the routes and the live event ──
class TurnRecorder:
    """A runner for the routes: what each turn was asked with, and today's chat as the current session."""

    def __init__(self):
        self.asked = []

    def current_session_id(self, date):
        return f"chat-{date}"

    async def chat(self, text, thinking=None, session_id=None, images=None):
        self.asked.append({"text": text, "thinking": thinking, "session_id": session_id})
        yield {"type": "done", "text": "ok"}

    async def history(self, date, limit=None, before=None):
        return {"items": [], "total": 0, "start": 0}

    async def post_message(self, text, session_id=None, media=None, kind="system"):
        pass

    async def close(self):
        pass

    plugins = {"skills": [], "servers": []}

    async def load_plugins(self):
        return self.plugins


async def _app(store):
    from odie.app.main import create_app
    runner = TurnRecorder()
    app = create_app(runner=runner, store=store)
    return app, runner, httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


async def test_get_and_put_and_every_open_app_hears_of_it(store):
    app, _, c = await _app(store)
    async with c, app.router.lifespan_context(app):
        got = (await c.get("/api/chat/thinking")).json()
        assert got["on"] is False and got["session_id"].startswith("chat-")  # today's current chat
        live = app.state.bus.queue()
        try:
            r = await c.put("/api/chat/thinking", json={"session_id": "chat-2026-10-28", "on": True})
            assert r.json() == {"session_id": "chat-2026-10-28", "on": True}
            event = await asyncio.wait_for(live.get(), 2)
            assert event == {"type": "thinking", "session_id": "chat-2026-10-28", "on": True}
        finally:
            app.state.bus.release(live)
        assert (await c.get("/api/chat/thinking", params={"session_id": "chat-2026-10-28"})).json()["on"] is True
        assert (await c.get("/api/chat/thinking", params={"session_id": "chat-2026-10-29"})).json()["on"] is True  # the default
        r = await c.put("/api/chat/thinking", json={"on": False})  # no session: today's
        assert r.json()["session_id"] == got["session_id"] and r.json()["on"] is False
        assert (await c.get("/api/chat/thinking", params={"session_id": "not a chat"})).status_code == 422
        assert (await c.put("/api/chat/thinking", json={"session_id": "../x", "on": True})).status_code == 422
        assert (await c.put("/api/chat/thinking", json={"session_id": "chat-2026-10-28"})).status_code == 422  # on is needed


async def test_a_chat_turn_without_thinking_leaves_it_to_the_chat_and_with_it_saves_it(store):
    from odie import thinking
    app, runner, c = await _app(store)
    async with c, app.router.lifespan_context(app):
        await c.post("/api/chat", json={"text": "hi", "session_id": "chat-2026-10-28"})
        assert runner.asked[-1]["thinking"] is None  # the runner uses the chat's own (the Mac app sends none)
        assert thinking.get(store, "chat-2026-10-28") is False
        live = app.state.bus.queue()
        try:
            await c.post("/api/chat", json={"text": "hi again", "session_id": "chat-2026-10-28", "thinking": True})  # an older web app
            assert runner.asked[-1]["thinking"] is True
            assert thinking.get(store, "chat-2026-10-28") is True and thinking.default(store) is True
            event = await asyncio.wait_for(live.get(), 2)
            assert event == {"type": "thinking", "session_id": "chat-2026-10-28", "on": True}
        finally:
            app.state.bus.release(live)
