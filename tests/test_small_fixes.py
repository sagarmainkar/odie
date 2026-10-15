from types import SimpleNamespace

from google.adk.agents.invocation_context import LlmCallsLimitExceededError

from odie.agent.callbacks import OdiePlugin
from odie.app.runner import MAX_LLM_CALLS, chat_error, chat_run_config
from odie.store.db import Store


def test_turns_have_a_model_call_cap():
    rc = chat_run_config()
    assert rc.max_llm_calls == MAX_LLM_CALLS and 20 <= MAX_LLM_CALLS <= 60


def test_hitting_the_cap_reads_as_a_sentence():
    msg = chat_error(LlmCallsLimitExceededError("Max number of llm calls limit of `40` exceeded"))
    assert "steps" in msg and "Error" not in msg
    assert chat_error(ValueError("boom")).startswith("ValueError: boom")


def _ctx():
    return SimpleNamespace(session=SimpleNamespace(id="s1"), invocation_id="i1")


async def test_a_paused_gated_tool_writes_no_tool_call_row(tmp_path):
    s = Store(tmp_path / "a.db")
    s.init_schema()
    p = OdiePlugin(s)
    tool = SimpleNamespace(name="gmail_send_draft")
    await p.after_tool_callback(tool=tool, tool_args={"draft_id": "d1"}, tool_context=_ctx(),
                                result={"error": "This tool call requires confirmation, please approve or reject."})
    assert s.one("select count(*) n from audit_log where event='tool_call'")["n"] == 0
    await p.after_tool_callback(tool=tool, tool_args={"draft_id": "d1"}, tool_context=_ctx(), result={"content": [{"type": "text", "text": "sent"}]})
    assert s.one("select count(*) n from audit_log where event='tool_call'")["n"] == 1


async def test_app_tool_results_are_not_sent_twice(tmp_path):
    s = Store(tmp_path / "a.db")
    s.init_schema()
    p = OdiePlugin(s)
    result = {"content": [{"type": "text", "text": '{"hits": [1, 2]}'}], "structuredContent": {"hits": [1, 2]}, "isError": False}
    out = await p.after_tool_callback(tool=SimpleNamespace(name="search_notes"), tool_args={}, tool_context=_ctx(), result=result)
    assert out is not None and "structuredContent" not in out and out["content"][0]["text"] == '{"hits": [1, 2]}'
    only_structured = {"content": [], "structuredContent": {"hits": [3]}}
    out2 = await p.after_tool_callback(tool=SimpleNamespace(name="search_notes"), tool_args={}, tool_context=_ctx(), result=only_structured)
    assert (out2 or only_structured).get("structuredContent") == {"hits": [3]}  # the only copy: kept


import pytest
from google.adk.events import Event
from google.genai import types

from odie.app.runner import CHECK_PREFIX, OdieRunner, claimed_but_not_done, events_to_history


@pytest.mark.parametrize("text, called, expected", [
    ("I have scheduled a reminder for you to call your mother at 6:00 PM tomorrow.", set(), "task_add"),
    ("Done. I've set a reminder for 9 am.", set(), "task_add"),
    ("Reminder set for 6 pm.", set(), "task_add"),
    ("I'll remind you at 6.", set(), "task_add"),
    ("I've set a reminder for 9 am.", {"task_add"}, None),          # it did call the tool
    ("Want me to set a reminder?", set(), None),                    # an offer, not a claim
    ("I'm tracking it now and will tell you when it changes.", set(), "track"),
    ("I've started a tracker for the match.", {"track"}, None),
    ("Here's the weather.", set(), None),
])
def test_claimed_but_not_done(text, called, expected):
    assert claimed_but_not_done(text, called) == expected


def _ev(text=None, call=None):
    parts = [types.Part(text=text)] if text else [types.Part(function_call=types.FunctionCall(name=call, args={}))]
    return Event(author="odie", invocation_id="i", content=types.Content(role="model", parts=parts))


async def test_a_claimed_reminder_without_the_tool_gets_one_nudge(isolated_settings, tmp_path):
    s = Store(tmp_path / "assistant.db")
    s.init_schema()
    r = OdieRunner(s)
    sent = []

    async def fake_run(**kw):
        sent.append(kw["new_message"].parts[0].text)
        if len(sent) == 1:
            yield _ev("I have scheduled a reminder for you at 6 pm.")
        else:
            yield _ev(call="task_add")
            yield _ev("Reminder saved for 6 pm tomorrow.")
    r.runner.run_async = fake_run
    events = [e async for e in r.chat("Remind me at 6 pm to call mom", session_id="t-1")]
    assert len(sent) == 2 and sent[1].startswith(CHECK_PREFIX) and "task_add" in sent[1]
    assert "Reminder saved" in events[-1]["text"]
    await r.close()


async def test_if_it_still_doesnt_the_reply_says_so(isolated_settings, tmp_path):
    s = Store(tmp_path / "assistant.db")
    s.init_schema()
    r = OdieRunner(s)

    async def fake_run(**kw):
        yield _ev("I have scheduled a reminder for you at 6 pm.")
    r.runner.run_async = fake_run
    events = [e async for e in r.chat("Remind me at 6 pm to call mom", session_id="t-2")]
    assert events[-1]["type"] == "done"
    h = await r.session_history("t-2")
    assert "wasn't saved" in h["items"][-1]["text"]  # a stored message of its own, shown live and in history
    await r.close()


def test_history_hides_the_check_message():
    user = Event(author="user", invocation_id="i", content=types.Content(role="user", parts=[types.Part(text=CHECK_PREFIX + "call task_add")]))
    assert events_to_history([user]) == []
