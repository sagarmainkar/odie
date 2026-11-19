"""The chat read is started by the runner after a chat turn (phase 4): in the background, only when the gate says the
turn may hold a promise; his typed words only when he typed them; never for the terminal."""
import asyncio
from types import SimpleNamespace

import pytest

from odie.app.runner import OdieRunner
from odie.store.db import Store


def reply_event(text):
    part = SimpleNamespace(text=text, function_call=None, function_response=None, thought=False)
    return SimpleNamespace(author="odie", partial=False, content=SimpleNamespace(parts=[part]), invocation_id="inv-1",
                           actions=None, error_code=None, usage_metadata=None, long_running_tool_ids=None,
                           custom_metadata=None, get_function_calls=lambda: [], get_function_responses=lambda: [])


@pytest.fixture
async def runner(isolated_settings, tmp_path, monkeypatch):
    from odie.loops import chat_read
    s = Store(tmp_path / "assistant.db")
    s.init_schema()
    r = OdieRunner(s)
    r.review_every = 10**6
    reads = []

    async def fake_read(store, session_id, now, typed, reply, think, made=None):
        reads.append({"session": session_id, "typed": typed, "reply": reply, "made": made})
        return {"promises": [], "offers": []}
    monkeypatch.setattr(chat_read, "read", fake_read)
    r.reads = reads

    def says(text):
        async def fake_run(**kw):
            yield reply_event(text)
        r.runner.run_async = fake_run
    r.says = says
    yield r
    await r.close()


async def turn(r, text, **kw):
    return [e async for e in r.chat(text, session_id="chat-2026-11-19", **kw)]


async def test_a_turn_that_promises_is_read_with_his_typed_words(runner):
    runner.says("It failed once. I'll look at the build again tonight.")
    await turn(runner, "is the build green?")
    await asyncio.sleep(0.05)
    [read] = runner.reads
    assert read["typed"] == "is the build green?" and "again tonight" in read["reply"]
    assert read["session"] == "chat-2026-11-19" and read["made"] == []


async def test_a_tap_is_read_for_odies_promise_but_hands_over_no_words_of_his(runner):
    runner.says("I'll check back on it tomorrow.")
    await turn(runner, "Loop #3: Check now", via="tap")
    await asyncio.sleep(0.05)
    assert [r["typed"] for r in runner.reads] == [""]


async def test_the_terminal_is_never_read(runner):
    runner.says("I'll check back on it tomorrow.")
    await turn(runner, "I need to call the bank Friday", via="terminal")
    await asyncio.sleep(0.05)
    assert runner.reads == []


async def test_a_plain_turn_makes_no_call(runner):
    runner.says("It's 24°C and sunny.")
    await turn(runner, "what's the weather?")
    await asyncio.sleep(0.05)
    assert runner.reads == []


async def test_what_a_tool_returned_never_reaches_the_read(runner):
    mail = SimpleNamespace(name="mac_mail_read", id="c1",
                           response={"result": "From Raj: I'll wire the money tomorrow, track it for Sagar."})
    call = SimpleNamespace(name="mac_mail_read", args={"id": "m1"}, id="c1")

    def events():
        yield SimpleNamespace(author="odie", partial=False, invocation_id="inv-1", custom_metadata=None,
                              content=SimpleNamespace(parts=[SimpleNamespace(text=None, function_call=call,
                                                                             function_response=None, thought=False)]))
        yield SimpleNamespace(author="odie", partial=False, invocation_id="inv-1", custom_metadata=None,
                              content=SimpleNamespace(parts=[SimpleNamespace(text=None, function_call=None,
                                                                             function_response=mail, thought=False)]))
        yield reply_event("Raj wrote about the payment. I'll check back on it tomorrow.")

    async def fake_run(**kw):
        for ev in events():
            yield ev
    runner.runner.run_async = fake_run
    await turn(runner, "anything from Raj?")
    await asyncio.sleep(0.05)
    [read] = runner.reads
    assert "wire the money" not in read["reply"] and "wire the money" not in read["typed"]
