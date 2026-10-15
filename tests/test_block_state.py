"""Saved block state (a checklist's ticks): the store table, the two routes, and the reply key the app saves them under."""
from pathlib import Path

import pytest

from odie.store.db import Store
from tests.test_api import client  # noqa: F401  (fixture)

REPLY = "3f2b9c1e-5d4a-4c8e-9a51-0b7d2e6f1a90"


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "assistant.db")
    s.init_schema()
    # Never the owner's database: the test's own folder, nowhere under ~/.odie.
    assert str(s.path).startswith(str(tmp_path))
    assert not str(s.path.resolve()).startswith(str((Path.home() / ".odie").resolve()))
    return s


def test_a_reply_has_nothing_saved_until_a_tick(store):
    assert store.block_state("chat-2026-10-11", REPLY) == {}


def test_ticks_are_saved_per_reply_and_block_and_replaced_on_each_save(store):
    store.save_block_state("chat-2026-10-11", REPLY, "0/2", [0, 3])
    store.save_block_state("chat-2026-10-11", REPLY, "0/2", [0, 3, 4])
    store.save_block_state("chat-2026-10-11", REPLY, "1/0.children.1", [1])
    store.save_block_state("chat-2026-10-11", "another-reply", "0/2", [5])
    store.save_block_state("chat-2026-10-11-2", REPLY, "0/2", [6])
    assert store.block_state("chat-2026-10-11", REPLY) == {"0/2": [0, 3, 4], "1/0.children.1": [1]}
    assert store.block_state("chat-2026-10-11", "another-reply") == {"0/2": [5]}
    assert store.block_state("chat-2026-10-11-2", REPLY) == {"0/2": [6]}
    row = store.one("select updated_at from block_state where session_id='chat-2026-10-11' and block_path='0/2' and message_key=?", (REPLY,))
    assert row["updated_at"].endswith("Z")


def test_a_value_too_big_is_refused(store):
    with pytest.raises(ValueError, match="over"):
        store.save_block_state("chat-2026-10-11", REPLY, "0/0", list(range(2000)))
    assert store.block_state("chat-2026-10-11", REPLY) == {}


def test_a_reply_holds_a_limited_number_of_saved_blocks(store):
    for i in range(Store.BLOCK_PATHS_PER_REPLY):
        store.save_block_state("chat-2026-10-11", REPLY, f"0/{i}", [0])
    with pytest.raises(ValueError, match="at most"):
        store.save_block_state("chat-2026-10-11", REPLY, "1/0", [0])
    store.save_block_state("chat-2026-10-11", REPLY, "0/0", [0, 1])  # one already there can still change
    assert store.block_state("chat-2026-10-11", REPLY)["0/0"] == [0, 1]


# --- routes ---------------------------------------------------------------------------------------------------------

async def test_put_then_get(client):
    r = await client.put("/api/block-state", json={"session_id": "chat-2026-10-11", "message_key": REPLY,
                                                    "block_path": "0/1", "value": [0, 2]})
    assert r.status_code == 200 and r.json() == {"ok": True}
    r = await client.get("/api/block-state", params={"session_id": "chat-2026-10-11", "message_key": REPLY})
    assert r.json() == {"values": {"0/1": [0, 2]}}


async def test_get_for_a_reply_with_nothing_saved(client):
    r = await client.get("/api/block-state", params={"session_id": "chat-2026-10-11-2", "message_key": REPLY})
    assert r.status_code == 200 and r.json() == {"values": {}}


@pytest.mark.parametrize("change", [
    {"session_id": "eval-abc"},                 # not a chat session
    {"session_id": "../../etc"},
    {"message_key": "has spaces"},
    {"message_key": "x" * 65},
    {"block_path": "0"},                        # no fence number
    {"block_path": "0/1.rows.2"},               # only container children are places
    {"block_path": "0/1; drop table block_state"},
])
async def test_put_refuses_bad_names(client, change):
    body = {"session_id": "chat-2026-10-11", "message_key": REPLY, "block_path": "0/1", "value": [0], **change}
    r = await client.put("/api/block-state", json=body)
    assert r.status_code == 422


async def test_get_refuses_bad_names(client):
    assert (await client.get("/api/block-state", params={"session_id": "eval-abc", "message_key": REPLY})).status_code == 422
    assert (await client.get("/api/block-state", params={"session_id": "chat-2026-10-11", "message_key": "a b"})).status_code == 422


async def test_put_refuses_a_value_too_big(client):
    body = {"session_id": "chat-2026-10-11", "message_key": REPLY, "block_path": "0/1", "value": list(range(2000))}
    r = await client.put("/api/block-state", json=body)
    assert r.status_code == 413


# --- the reply key ----------------------------------------------------------------------------------------------------

async def test_the_reply_key_is_the_same_while_streaming_and_after_a_reload():
    """Through real ADK: a streamed reply's pieces, its finished text and the event the session keeps share one id."""
    from google.adk.agents import LlmAgent
    from google.adk.agents.run_config import RunConfig, StreamingMode
    from google.adk.models.base_llm import BaseLlm
    from google.adk.models.llm_response import LlmResponse
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai import types

    from odie.app.runner import event_to_sse, events_to_history, with_session

    class Streams(BaseLlm):
        async def generate_content_async(self, llm_request, stream=False):
            for piece in ("Pack ", "these:"):
                yield LlmResponse(content=types.Content(role="model", parts=[types.Part(text=piece)]), partial=True)
            yield LlmResponse(content=types.Content(role="model", parts=[types.Part(text="Pack these:")]), partial=False)

    sessions = InMemorySessionService()
    runner = Runner(app_name="t", agent=LlmAgent(name="odie", model=Streams(model="fake")), session_service=sessions)
    await sessions.create_session(app_name="t", user_id="u", session_id="chat-2026-10-11")
    items = []
    async for ev in runner.run_async(user_id="u", session_id="chat-2026-10-11", new_message=types.Content(role="user", parts=[types.Part(text="hi")]),
                                     run_config=RunConfig(streaming_mode=StreamingMode.SSE)):
        items += event_to_sse(ev)
    assert [i["type"] for i in items] == ["token", "token", "text"]
    keys = {i["key"] for i in items}
    assert len(keys) == 1

    saved = await sessions.get_session(app_name="t", user_id="u", session_id="chat-2026-10-11")
    history = with_session("chat-2026-10-11", events_to_history(saved.events))
    reply = history[-1]
    assert reply["text"] == "Pack these:" and reply["key"] in keys and reply["sid"] == "chat-2026-10-11"
    assert "key" not in history[0] and "sid" not in history[0]  # the user's own message isn't a reply


async def test_a_streamed_reply_says_which_session_it_is_in(isolated_settings, tmp_path):
    """The app needs (session, key) for a reply it is still streaming; today's chat may be a later segment."""
    from types import SimpleNamespace as NS

    from google.genai import types

    from odie.app.runner import OdieRunner
    s = Store(tmp_path / "assistant.db")
    s.init_schema()
    r = OdieRunner(s)

    async def fake_run(**kw):
        for partial, text in ((True, "Pack "), (False, "Pack these.")):
            yield NS(author="odie", partial=partial, id="ev-1", content=types.Content(role="model", parts=[types.Part(text=text)]))
    r.runner.run_async = fake_run
    events = [e async for e in r.chat("hi", session_id="chat-2099-01-01-2")]
    texts = [e for e in events if e["type"] in ("token", "text")]
    assert texts == [{"type": "token", "text": "Pack ", "key": "ev-1", "session_id": "chat-2099-01-01-2"},
                     {"type": "text", "text": "Pack these.", "key": "ev-1", "session_id": "chat-2099-01-01-2"}]
    await r.close()
