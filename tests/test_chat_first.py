"""Chat first: a reply that only announces its content ("Here's the full plan") gets one nudge to send it, drawn; and
the runner hands tools the user's own words for the turn (so files are made only when asked)."""
import pytest
from google.adk.events import Event
from google.genai import types

from odie.app.runner import CHECK_PREFIX, OdieRunner, promised_but_empty
from odie.store.db import Store


@pytest.mark.parametrize("reply, called, expected", [
    ("Route and food locked in.Here's the full plan — timings, food and three stay options with live prices.", {"web_search"}, True),
    ("Here it is.", {"load_skill"}, True),
    ("Here's the full plan:", {"web_search"}, True),
    ("Here's the answer: 42.", {"web_search"}, False),                      # the answer is in it
    ("Here's the plan.\n```odie-blocks\n[]\n```", {"load_skill"}, False),   # drawn
    ("Here's the plan:\n- Day 1: Madikeri\n- Day 2: Dubare", {"web_search"}, False),  # a list
    ("Here's to a great trip!", set(), False),                              # no tools: just chat
    ("Done — the deck is under your reply.", {"make_slides"}, False),
])
def test_promised_but_empty(reply, called, expected):
    assert promised_but_empty(reply, called) is expected


def _ev(text=None, call=None):
    parts = [types.Part(text=text)] if text else [types.Part(function_call=types.FunctionCall(name=call, args={}))]
    return Event(author="odie", invocation_id="i", content=types.Content(role="model", parts=parts))


async def test_an_announced_plan_without_the_plan_gets_one_nudge(isolated_settings, tmp_path):
    s = Store(tmp_path / "assistant.db")
    s.init_schema()
    r = OdieRunner(s)
    sent, words = [], []

    async def fake_run(**kw):
        from odie.agent import turn
        words.append(turn.USER_TEXT.get())
        sent.append(kw["new_message"].parts[0].text)
        if len(sent) == 1:
            yield _ev(call="web_search")
            yield _ev("Here's the full plan — timings, food and three stays.")
        else:
            yield _ev("Here it is.\n```odie-blocks\n[{\"type\": \"timeline\"}]\n```")
    r.runner.run_async = fake_run
    events = [e async for e in r.chat("Make an itinerary for Coorg", session_id="t-1")]
    assert len(sent) == 2 and sent[1].startswith(CHECK_PREFIX) and "odie-blocks" in sent[1]
    assert words[0] == "Make an itinerary for Coorg"  # tools see the user's own words, not the appended context
    assert "odie-blocks" in events[-1]["text"]
    from odie.agent import turn
    assert turn.USER_TEXT.get() is None  # and only during the turn
    await r.close()
