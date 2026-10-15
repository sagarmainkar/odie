from google.adk.events import Event
from google.genai import types

from odie.app.runner import OdieRunner
from odie.store.db import Store
from tests.test_api import client  # noqa: F401  (fixture)


def _call(name, args=None):
    return Event(author="odie", invocation_id="i", content=types.Content(role="model", parts=[
        types.Part(function_call=types.FunctionCall(name=name, args=args or {}))]))


def _result(name, response):
    return Event(author="odie", invocation_id="i", content=types.Content(role="user", parts=[
        types.Part(function_response=types.FunctionResponse(name=name, response=response))]))


def _text(t):
    return Event(author="odie", invocation_id="i", content=types.Content(role="model", parts=[types.Part(text=t)]))


FAIL = {"content": [{"type": "text", "text": '{"ok":false,"error":"gmail_failed","message":"subject is required for a new email"}'}], "isError": True}


async def _runner(isolated_settings, tmp_path, events):
    s = Store(tmp_path / "assistant.db")
    s.init_schema()
    r = OdieRunner(s)
    seen = {"n": 0}
    posted = []

    async def post(text, session_id=None):
        posted.append(text)
    r.post_message = post

    async def fake_run(**kw):
        for ev in events(r):
            seen["n"] += 1
            yield ev
    r.runner.run_async = fake_run
    return r, seen, posted


async def test_the_same_failure_three_times_stops_the_turn(isolated_settings, tmp_path):
    def events(r):
        for _ in range(10):
            yield _call("gmail_create_draft", {"body": "hi"})
            yield _result("gmail_create_draft", FAIL)
    r, seen, posted = await _runner(isolated_settings, tmp_path, events)
    out = [e async for e in r.chat("reply to Ravi", session_id="chat-2026-10-06")]
    assert seen["n"] == 6                          # three call/result pairs, then stopped
    assert out[-1]["type"] == "done"
    assert posted and "subject is required" in posted[0] and "3 times" in posted[0]
    await r.close()


async def test_stop_ends_the_turn_at_the_next_safe_point(isolated_settings, tmp_path):
    def events(r):
        yield _call("web_search", {"query": "x"})
        r.request_stop("chat-2026-10-06")          # The user taps Stop while the tool runs
        yield _result("web_search", {"result": "ok"})
        yield _call("web_search", {"query": "y"})
        yield _result("web_search", {"result": "ok"})
        yield _text("never reached")
    r, seen, posted = await _runner(isolated_settings, tmp_path, events)
    out = [e async for e in r.chat("search", session_id="chat-2026-10-06")]
    assert seen["n"] == 2                          # the call got its result, then the turn ended
    assert out[-1]["type"] == "done" and posted == ["Stopped."]
    assert not any("never reached" in str(e) for e in out)
    await r.close()


async def test_a_stop_for_one_chat_leaves_others_alone(isolated_settings, tmp_path):
    def events(r):
        r.request_stop("chat-2026-10-05")
        yield _text("answer")
    r, seen, posted = await _runner(isolated_settings, tmp_path, events)
    out = [e async for e in r.chat("hi", session_id="chat-2026-10-06")]
    assert seen["n"] == 1 and posted == [] and out[-1]["text"] == "answer"
    await r.close()


async def test_stop_route(client):
    c = client[0] if isinstance(client, tuple) else client
    r = (await c.post("/api/chat/stop", json={})).json()
    assert r["ok"] and r["session_id"].startswith("chat-")
    assert (await c.post("/api/chat/stop", json={"session_id": "chat-2026-10-02"})).json()["session_id"] == "chat-2026-10-02"
    assert (await c.post("/api/chat/stop", json={"session_id": "voice-1"})).status_code == 422
