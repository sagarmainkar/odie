"""A connected app's tools join when its skill loads and then stay, and a message that reads better drawn carries a
one-line nudge to draw (2026-10-12: local Gemma got 53 tools, 19 of them two apps', and stopped drawing blocks).

The chat runs through the real OdieRunner, ADK, the real session store and a real MCP server (tests/fixtures/
mcp_tester.py), with a scripted model that records each request (tests.test_append_only)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from odie.agent.visual_nudge import NUDGE, looks_visual
from odie.prefix_check import compare
from odie.store.db import Store
from tests.test_append_only import SESSION, Scripted, pieces_of

TESTER = {"command": sys.executable, "args": [str(Path(__file__).parent / "fixtures" / "mcp_tester.py")],
          "description": "Test tools"}
APP_TOOLS = {"echo", "write_note"}


def _tool_names(request: dict) -> set[str]:
    return {f["name"] for t in request["tools"] for f in t.get("function_declarations", [])}


async def _turns(tmp_path, monkeypatch, turns) -> list[dict]:
    """The turns through one runner (one server run); returns the requests the model got."""
    from odie.app import runner as runner_mod
    start = len(Scripted.seen)
    Scripted.script = dict(turns)
    monkeypatch.setattr(runner_mod, "model_for", lambda selection, thinking: Scripted(model="scripted"))
    store = Store(tmp_path / "assistant.db")
    store.init_schema()
    r = runner_mod.OdieRunner(store)
    await r.load_plugins()
    try:
        for words, _ in turns:
            events = [e async for e in r.chat(words, session_id=SESSION)]
            assert not [e for e in events if e["type"] == "error"], events
    finally:
        await r.close()
    return Scripted.seen[start:]


async def test_an_apps_tools_join_when_its_skill_loads_and_stay_after_a_restart(isolated_settings, tmp_path, monkeypatch):
    """A fresh chat has none of the app's tools. load_skill("mcp-tester") adds them, once, at the end of the tool
    list; they stay in later turns, and after the server restarts (the loaded skill is in the session's state)."""
    from odie.plugins import mcp
    mcp.write_config({"tester": TESTER})
    Scripted.seen = []
    first_run = [
        ("Hi there", ["Hello."]),
        ("Echo hello", [("load_skill", {"skill_name": "mcp-tester"}), ("echo", {"text": "hello"}), "hello"]),
        ("Thanks", ["Any time."]),
    ]
    seen = await _turns(tmp_path, monkeypatch, first_run)
    assert len(seen) == 5
    assert not APP_TOOLS & _tool_names(seen[0])  # a fresh chat: none of the app's tools
    assert not APP_TOOLS & _tool_names(seen[1])  # the turn's first request, before load_skill
    assert APP_TOOLS <= _tool_names(seen[2]) and APP_TOOLS <= _tool_names(seen[-1])
    changed = [i for i, (a, b) in enumerate(zip(seen, seen[1:]), 1)
               if not compare("", pieces_of(a), pieces_of(b)).appended]
    assert changed == [2]  # only the request right after the skill loaded changed anything earlier: its tools
    names_before = [f["name"] for t in seen[1]["tools"] for f in t.get("function_declarations", [])]
    names_after = [f["name"] for t in seen[2]["tools"] for f in t.get("function_declarations", [])]
    assert names_after[:len(names_before)] == names_before  # the app's tools were added at the end

    after_restart = await _turns(tmp_path, monkeypatch, [("Echo again", [("echo", {"text": "again"}), "again"])])
    assert all(APP_TOOLS <= _tool_names(r) for r in after_restart)
    assert compare("", pieces_of(seen[-1]), pieces_of(after_restart[0])).appended


async def test_a_background_turn_loads_an_app_like_a_chat_does(isolated_settings, tmp_path, monkeypatch):
    """A background check starts without the app's tools and gets them by loading its skill, as a chat does (the mail
    watch reads mail through its own tools, odie.watch.fetch, and starts with its calendar app already loaded:
    tests/test_watch_calendar_tools.py)."""
    from odie.app import runner as runner_mod
    from odie.plugins import mcp
    mcp.write_config({"tester": TESTER})
    Scripted.seen = []
    # A background check's message starts with the time: "It is Monday 12 October 2026, 09:00 (…).\n\nCheck the thing"
    Scripted.script = {"It is ": [("load_skill", {"skill_name": "mcp-tester"}), ("echo", {"text": "x"}), "Done."]}
    monkeypatch.setattr(runner_mod, "model_for", lambda selection, thinking: Scripted(model="scripted"))
    store = Store(tmp_path / "assistant.db")
    store.init_schema()
    r = runner_mod.OdieRunner(store)
    await r.load_plugins()
    try:
        said = await r.background_turn("Check the thing")
    finally:
        await r.close()
    assert said.endswith("Done.")
    assert not APP_TOOLS & _tool_names(Scripted.seen[0])
    assert APP_TOOLS <= _tool_names(Scripted.seen[-1])
    echoed = [m for m in Scripted.seen[-1]["messages"] for p in m["parts"] if p.get("function_response", {}).get("name") == "echo"]
    assert echoed  # the app's tool ran


@pytest.mark.parametrize("text, previous, expected", [
    ("Compare Pixel 10a, Galaxy A76 and Nothing Phone 4 for someone who cares about camera and battery, under ₹50k", "", True),
    ("Packing list for 3 days in Ooty in December with my parents", "", True),
    ("Home loan of 40 lakh at 8.5%. What's my EMI?", "", True),
    ("Top 3 filter coffee places in Bangalore", "", True),
    ("How do I renew my passport?", "", True),
    ("Will it rain in Coorg this weekend?", "", True),
    ("Split my 1.2 lakh salary into a monthly budget", "", True),
    ("History of the Mysore palace", "", True),
    ("Flash cards, let's play", "", True),
    ("Quiz me on the medal table", "", True),
    ("Which finance stocks are up, by quarter?", "", True),
    ("Show me a heat map of my sleep", "", True),
    ("yes", "Here it is:\n```odie-blocks\n[{\"type\": \"checklist\"}]\n```", True),
    ("ok", "```odie-checklist\n{\"items\": []}\n```", True),
    ("yes", "Sure, which city?", False),
    ("thanks!", "```odie-blocks\n[]\n```", False),
    ("What else can you do?", "```odie-blocks\n[]\n```", False),
    ("Make me a one-page PDF of the Mysore plan", "", False),
    ("What's the capital of France?", "", False),
    ("Remind me tomorrow at 9 to call the bank", "", False),
])
def test_which_messages_look_visual(text, previous, expected):
    assert looks_visual(text, previous) is expected


async def test_the_nudge_rides_at_the_end_of_the_message_stays_as_sent_and_is_hidden(isolated_settings, tmp_path, monkeypatch):
    """A packing list gets the nudge after its [context: …] note; the next request carries the message as sent; a short
    "yes" after a reply that drew blocks gets it too, a plain question doesn't; the chat's history shows only the
    user's words."""
    Scripted.seen = []
    turns = [
        ("Packing list for Ooty", ['Here:\n```odie-blocks\n[{"type": "checklist", "items": ["Jacket"]}]\n```']),
        ("yes", ["Added socks."]),
        ("What's the capital of France?", ["Paris."]),
    ]
    seen = await _turns(tmp_path, monkeypatch, turns)
    first = seen[0]["messages"][-1]["parts"][0]["text"]
    assert first.startswith("Packing list for Ooty\n\n[context: now ") and first.endswith("\n" + NUDGE)
    assert seen[1]["messages"][0]["parts"][0]["text"] == first  # stays in history as it was sent
    assert seen[1]["messages"][-1]["parts"][0]["text"].endswith(NUDGE)  # "yes" after blocks
    assert not seen[2]["messages"][-1]["parts"][0]["text"].endswith(NUDGE)
    for before, now in zip(seen, seen[1:]):
        assert compare("", pieces_of(before), pieces_of(now)).appended

    from odie.app import runner as runner_mod
    store = Store(tmp_path / "assistant.db")
    r = runner_mod.OdieRunner(store)
    try:
        items = (await r.session_history(SESSION))["items"]
    finally:
        await r.close()
    said = [i["text"] for i in items if i["role"] == "user"]
    assert said == ["Packing list for Ooty", "yes", "What's the capital of France?"]
