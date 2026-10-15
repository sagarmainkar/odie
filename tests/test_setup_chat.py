"""The setup conversation: one turn calls the chosen model with only the setup tools, runs the tool calls (at most 6
rounds), and returns the reply, the cards and the checklist. A key typed into it never reaches the model or the
thread."""
import json

import httpx
import pytest

from odie.setup import chat, state
from odie.store.db import Store

KEY = "sk-proj-AbCdEf0123456789AbCdEf0123456789"


@pytest.fixture
def store(isolated_settings, tmp_path, monkeypatch):
    monkeypatch.setenv("ODIE_SETUP_HOME", str(tmp_path / "home"))
    s = Store(tmp_path / "assistant.db")
    s.init_schema()
    s.set_setting("model.chat", {"provider": "ollama", "model": "glm-test"})
    return s


def _call(name, args, cid="c1"):
    return {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
        {"id": cid, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}}]}


def _say(text):
    return {"choices": [{"message": {"role": "assistant", "content": text}}]}


def model(script, seen):
    """script: a list of responses, one per request; the last one repeats."""
    def handler(request):
        body = json.loads(request.content)
        seen.append(body)
        return httpx.Response(200, json=script[min(len(seen) - 1, len(script) - 1)])
    return httpx.MockTransport(handler)


async def test_keys_never_reach_the_model_or_the_thread(store):
    seen = []
    out = await chat.turn(store, f"here is my key {KEY}", transport=model([_say("Thanks!")], seen))
    assert seen == [] and "key form" in out["reply"] and out["cards"][0]["provider"] == "openai"
    assert KEY not in json.dumps(state.get(store)) and "here is my key" not in json.dumps(state.get(store))
    await chat.turn(store, "Call me Asha", transport=model([_say("Hi Asha! What should I call myself?")], seen))
    assert seen and all(KEY not in json.dumps(b) for b in seen)
    assert [m["text"] for m in state.get(store)["thread"]] == [chat.KEY_REPLY, "Call me Asha", "Hi Asha! What should I call myself?"]


async def test_a_turn_runs_tools_and_returns_cards(store):
    seen = []
    out = await chat.turn(store, "Yes, Tavily please", transport=model(
        [_call("request_key", {"provider": "tavily"}), _say("The form is up: paste your Tavily key there.")], seen))
    assert out["reply"] == "The form is up: paste your Tavily key there."
    assert out["cards"] == [{"type": "key", "provider": "tavily", "kind": "search", "label": "Tavily", "note": out["cards"][0]["note"]}]
    first, second = seen
    assert {t["function"]["name"] for t in first["tools"]} >= {"set_names", "request_key", "finish_setup"}
    assert not {t["function"]["name"] for t in first["tools"]} & {"run_shell", "web_search", "update_memory"}
    assert first["messages"][0]["role"] == "system" and "Offer only the current step's choices" in first["messages"][0]["content"]
    assert second["messages"][-1]["role"] == "tool" and "key form is on the screen" in second["messages"][-1]["content"]


async def test_tool_rounds_are_capped(store):
    seen = []
    out = await chat.turn(store, "go on", transport=model([_call("vault_options", {})], seen))
    assert len(seen) == chat.ROUNDS and out["reply"]


async def test_a_step_that_keeps_failing_falls_back(store):
    seen = []
    bad = _call("set_vault", {"choice": "elsewhere", "path": "relative/path"})
    out = await chat.turn(store, "use my notes", transport=model([bad, bad, bad, _say("Let's do this one in Settings later.")], seen))
    assert state.get(store)["steps"]["vault"] == "skipped" and "Settings" in out["reply"]
    assert "skipped for now" in seen[3]["messages"][-1]["content"]


async def test_a_saved_key_carries_the_conversation_on(store):
    seen = []
    out = await chat.event(store, "key_saved", "tavily", transport=model([_say("Tavily is set. Next, voice?")], seen))
    assert out["reply"] == "Tavily is set. Next, voice?" and state.get(store)["steps"]["search"] == "done"
    assert seen[0]["messages"][-1]["content"] == "(The Tavily key was saved.)"


async def test_a_brain_that_fails_is_said_plainly(store):
    def down(request):
        raise httpx.ConnectError("refused")
    out = await chat.turn(store, "hi", transport=httpx.MockTransport(down))
    assert "couldn't reach" in out["reply"].lower() and out["cards"] == []


async def test_thinking_is_left_out_of_the_reply(store):
    seen = []
    out = await chat.turn(store, "hi", transport=model([_say("<think>they said hi</think>Hello! What should I call you?")], seen))
    assert out["reply"] == "Hello! What should I call you?"


async def test_setup_routes(isolated_settings, tmp_path, monkeypatch):
    from odie.app.main import create_app
    from tests.test_api import FakeRunner
    s = Store(tmp_path / "a.db")
    s.init_schema()

    async def fake_turn(store, text, transport=None, note=False, runner=None):
        state.add_to_thread(store, "user", text)
        return {"reply": "ok", "cards": [], "state": chat.public_state(store)}
    monkeypatch.setattr(chat, "turn", fake_turn)
    app = create_app(runner=FakeRunner(), store=s)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        async with app.router.lifespan_context(app):
            got = (await c.get("/api/setup")).json()
            assert got["done"] is False and got["current"] == "brain"
            assert (await c.post("/api/setup/brain")).json()["steps"]["brain"] == "done"
            assert (await c.post("/api/setup/chat", json={"text": "hello"})).json()["reply"] == "ok"
            assert (await c.post("/api/setup/skip", json={"step": "names"})).status_code == 422
            assert (await c.post("/api/setup/skip", json={"step": "voice"})).json()["steps"]["voice"] == "skipped"
            assert (await c.post("/api/setup/finish")).status_code == 422  # steps are left: never finished over them
            assert (await c.post("/api/setup/restart")).json()["done"] is False


async def test_setup_starts_with_the_assistant_speaking(store):
    seen = []
    out = await chat.event(store, "start", "", transport=model([_say("never asked")], seen))
    assert out["reply"].startswith("Hi! I'm Odie") and "That's everything" not in out["reply"] and out["panel"] is None  # the brain step
    state.restart(store)
    state.mark(store, "brain", "done")
    out = await chat.event(store, "start", "", transport=model([_say("never asked")], seen))
    assert "what should I call you?" in out["reply"] and out["panel"]["step"] == "names"
    assert seen == []  # written by code: the greeting never depends on the model
    again = await chat.event(store, "start", "", transport=model([_say("again")], seen))
    assert again["reply"] == "" and seen == []  # once: a thread that has begun isn't started twice


async def test_a_caught_key_leaves_its_reply_in_the_thread(store):
    out = await chat.turn(store, f"here is my key {KEY}", transport=model([_say("no")], []))
    thread = state.get(store)["thread"]
    assert thread == [{"role": "assistant", "text": chat.KEY_REPLY}] and out["reply"] == chat.KEY_REPLY


async def test_events_only_take_known_kinds_and_providers(store):
    seen = []
    with pytest.raises(ValueError):
        await chat.event(store, "key_saved", KEY, transport=model([_say("x")], seen))
    with pytest.raises(ValueError):
        await chat.event(store, "anything", "tavily", transport=model([_say("x")], seen))
    with pytest.raises(ValueError):
        await chat.event(store, "skipped", "names", transport=model([_say("x")], seen))
    assert seen == [] and KEY not in json.dumps(state.get(store))


async def test_a_skip_from_the_screen_carries_the_conversation_on(store):
    seen = []
    out = await chat.event(store, "skipped", "voice", transport=model([_say("No voice for now. Next: apps?")], seen))
    assert state.get(store)["steps"]["voice"] == "skipped" and out["reply"].startswith("No voice")
    assert seen[0]["messages"][-1]["content"] == "(The user skipped voice for now.)"
    assert state.get(store)["thread"][0] == {"role": "user", "text": "(The user skipped voice for now.)", "note": True}


async def test_a_vault_chosen_in_setup_is_live_at_once(store, tmp_path):
    (tmp_path / "Notes").mkdir()
    calls = []

    class Worker:
        def kick(self):
            calls.append("kick")

    class Runner:
        vault_worker = Worker()

        async def reload_vault(self):
            calls.append("reload")

        def invalidate_prompt(self):
            calls.append("prompt")
    seen = []
    await chat.turn(store, "use my Notes folder", runner=Runner(), transport=model(
        [_call("set_vault", {"choice": "elsewhere", "path": str(tmp_path / "Notes")}), _say("Done.")], seen))
    assert "reload" in calls and "kick" in calls


async def test_an_openrouter_key_is_known_for_what_it_is(store):
    out = await chat.turn(store, "sk-or-v1-0123456789abcdefABCDEF0123", transport=model([_say("x")], []))
    assert out["cards"][0]["provider"] == "openrouter"


async def test_a_pasted_app_link_is_caught(store):
    seen = []
    link = "https://mcp.zapier.com/api/mcp/s/ZjM4NzQ1YTMtOWQ2Yi00ZTEyLWE3ZjAtZDc5YTBk/mcp"
    out = await chat.turn(store, f"here it is {link}", transport=model([_say("x")], seen))
    assert seen == [] and out["cards"][0]["type"] == "app" and out["cards"][0]["app"] == "zapier"
    assert "ZjM4NzQ1YTMtOWQ2Yi00ZTEy" not in json.dumps(state.get(store)) and "here it is" not in json.dumps(state.get(store))
    out = await chat.turn(store, "my composio key ck_AbCdEf0123456789AbCd", transport=model([_say("x")], seen))
    assert seen == [] and out["cards"][0]["app"] == "composio"
    out = await chat.turn(store, "https://apps.example.net/mcp?token=ZjM4NzQ1YTMtOWQ2Yi00ZTEyLWE3", transport=model([_say("x")], seen))
    assert seen == [] and out["cards"] == [] and "Settings" in out["reply"]  # some other app: Settings takes it


async def test_app_saved_carries_setup_on(store):
    seen = []
    out = await chat.event(store, "app_saved", "zapier", transport=model([_say("Zapier is connected. Now your phone?")], seen))
    assert out["reply"] == "Zapier is connected. Now your phone?" and state.get(store)["steps"]["apps"] == "done"
    assert "(The Zapier connection was saved.)" in json.dumps(seen[0]["messages"])
    with pytest.raises(ValueError):
        await chat.event(store, "app_saved", "nope")
