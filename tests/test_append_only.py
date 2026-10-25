"""Every request in a chat starts with the whole request before it (2026-10-12), so every provider's prompt cache is
reused: the system prompt, the tools and the earlier messages exactly as sent, with new messages only at the end. The
one exception is a cut, when a long chat passes its limit and everything before its last five turns goes as words
only (odie.agent.compaction).

Run through the real OdieRunner and ADK, with a scripted model that records each request as ADK hands it over: a
reminder (a tool call), a skill loaded mid-turn and its tool, a memory saved mid-chat and read back, a short reply.
Claude goes the same way through the real anthropic library and a fake server that signs thoughts as Claude does."""
from __future__ import annotations

import json
from typing import ClassVar

import pytest
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from odie.prefix_check import compare
from odie.store.db import Store

SESSION = "chat-2099-01-01"  # not today's

# Each turn: the user's words, then what the model does at each step (a tool call, or the final text).
TURNS = [
    ("Remind me tomorrow at 9 to call the bank",
     [("task_add", {"title": "Call the bank", "kind": "reminder", "due": "2099-01-02T09:00"}), "Done, 9 tomorrow."]),
    ("What trackers do I have?",
     [("load_skill", {"skill_name": "trackers"}), ("list_trackers", {}), "No trackers yet."]),
    ("Remember that I like aisle seats",
     [("update_memory", {"title": "Seat", "content": "Aisle seats, always.", "topic": "Travel"}), "Saved."]),
    ("Thanks!", ["Any time."]),
    ("Which seat do I like?", [("fetch_memory", {"title": "Seat"}), "Aisle."]),
]


class Scripted(BaseLlm):
    """Plays TURNS: the step is how many tool results came back since the user's last message."""
    seen: ClassVar[list[dict]] = []
    script: ClassVar[dict] = {}

    async def generate_content_async(self, llm_request, stream: bool = False):
        from odie.agent.callbacks import turn_start
        contents = llm_request.contents or []
        Scripted.seen.append(snapshot(llm_request))
        start = turn_start(contents)
        words = contents[start].parts[0].text
        steps = next(s for q, s in Scripted.script.items() if words.startswith(q))
        step = steps[sum(1 for c in contents[start:] if any(p.function_response for p in c.parts or []))]
        if isinstance(step, str):
            part = types.Part(text=step)
        else:
            part = types.Part(function_call=types.FunctionCall(id=f"call-{len(Scripted.seen)}", name=step[0], args=step[1]))
        yield LlmResponse(content=types.Content(role="model", parts=[part]))


def snapshot(llm_request) -> dict:
    """The request as a provider would see it, in the pieces odie.prefix_check compares: tools, system, messages."""
    cfg = llm_request.config
    tools = [t.model_dump(mode="json", exclude_none=True) for t in (cfg.tools or [])]
    return {"tools": tools, "system": str(cfg.system_instruction),
            "messages": [c.model_dump(mode="json", exclude_none=True) for c in llm_request.contents or []]}


def pieces_of(snap: dict) -> list[tuple[str, str]]:
    out = [("tools", json.dumps(snap["tools"], sort_keys=True)), ("system", snap["system"])]
    return out + [(f"message {i}", json.dumps(m, sort_keys=True)) for i, m in enumerate(snap["messages"])]


async def _chat(tmp_path, monkeypatch, limit: int | None = None, turns=TURNS) -> list[dict]:
    from odie.app import runner as runner_mod
    Scripted.seen = []
    Scripted.script = dict(turns)
    monkeypatch.setattr(runner_mod, "model_for", lambda selection, thinking: Scripted(model="scripted"))
    store = Store(tmp_path / "assistant.db")
    store.init_schema()
    r = runner_mod.OdieRunner(store)
    await r.load_plugins()
    if limit is not None:
        r._history_limits[SESSION] = limit
    for words, _ in turns:
        events = [e async for e in r.chat(words, session_id=SESSION)]
        assert not [e for e in events if e["type"] == "error"], events
    await r.close()
    return Scripted.seen


async def test_every_request_starts_with_the_one_before(isolated_settings, tmp_path, monkeypatch):
    seen = await _chat(tmp_path, monkeypatch)
    assert len(seen) == 10  # every step of every turn reached the model
    for i, (before, now) in enumerate(zip(seen, seen[1:]), 2):
        step = compare(f"request {i}", pieces_of(before), pieces_of(now))
        assert step.appended, f"request {i} changed {step.where}: was {step.was!r}, now {step.now!r}"
    assert len({json.dumps(s["tools"]) for s in seen}) == 1   # a skill loading mid-turn changes no tool
    assert len({s["system"] for s in seen}) == 1              # nor does a memory saved mid-chat change the system prompt
    names = {f["name"] for t in seen[0]["tools"] for f in t.get("function_declarations", [])}
    assert {"list_trackers", "track", "market_history"} <= names  # every skill's tools, from the first request
    assert "[context: now " in seen[-1]["messages"][0]["parts"][0]["text"]  # the first message keeps its note


async def test_a_long_chat_is_cut_in_rare_batches(isolated_settings, tmp_path, monkeypatch):
    """Past the chat's limit, everything before the last five turns goes as words only, at the start of a turn;
    between cuts every request starts with the one before. Each cut shrinks the request."""
    long = "Aisle seats, window on night flights, extra legroom when it's cheap. " * 40  # a ~2,800 character memory
    turns = [("Remember my seat", [("update_memory", {"title": "Seat", "content": long, "topic": "Travel"}), "Saved."])]
    turns += [(f"Which seat do I like, {n}?", [("fetch_memory", {"title": "Seat"}), "Aisle."]) for n in range(14)]
    seen = await _chat(tmp_path, monkeypatch, limit=23_500, turns=turns)  # 30k characters: ~3k per turn
    changed = []
    for i, (before, now) in enumerate(zip(seen, seen[1:]), 1):
        if not compare("", pieces_of(before), pieces_of(now)).appended:
            changed.append(i)
    assert 1 <= len(changed) <= 3, changed  # a few cuts in 30 requests, not one per turn
    for i in changed:
        last = seen[i]["messages"][-1]["parts"][0]
        assert "text" in last and last["text"].startswith("Which seat")  # a cut happens only as a turn starts
        assert len(json.dumps(seen[i])) < len(json.dumps(seen[i - 1]))


@pytest.mark.parametrize("thinking", [True, False], ids=["think-longer", "thinking-off"])
async def test_claude_requests_only_grow_and_keep_their_thoughts(thinking, isolated_settings, tmp_path, monkeypatch):
    """The same chat with Claude, through litellm's real HTTP and a fake server that signs thoughts as Claude does:
    every request starts with the one before (cache marks aside), no thought is refused or dropped, and the earlier
    turns' thoughts go back whatever the effort (Claude thinks a little at "low" too)."""
    from odie.app import runner as runner_mod
    from odie.models import Provider, Selection
    from odie.prefix_check import pieces
    from tests.model_fakes import Reply, Script
    from tests.test_model_contract import _served, _thoughts_in
    replies = []
    for _, steps in TURNS:
        for step in steps:
            if isinstance(step, str):
                replies.append(Reply(text=step, thinking=True))
            else:
                replies.append(Reply(tool=step[0], args=step[1], thinking=True))
    script = Script(replies)
    _served(monkeypatch, "anthropic", script)
    claude = Selection(Provider("anthropic", "Anthropic", "https://api.anthropic.com/v1", "sk-test", False),
                       "claude-sonnet-5-5", "chat")
    monkeypatch.setattr(runner_mod, "resolve_selection", lambda st, slot="chat": claude)
    store = Store(tmp_path / "assistant.db")
    store.init_schema()
    r = runner_mod.OdieRunner(store)
    await r.load_plugins()
    for words, _ in TURNS:
        events = [e async for e in r.chat(words, thinking=thinking, session_id=SESSION)]
        assert not [e for e in events if e["type"] == "error"], events
    await r.close()
    assert len(script.bodies) == 10 and script.refused == [] and script.dropped == []
    for before, now in zip(script.bodies, script.bodies[1:]):
        assert compare("", pieces(before), pieces(now)).appended
    assert len(_thoughts_in(script.bodies[-1])) == 9  # every earlier step's thought
    assert all(b["output_config"] == {"effort": "medium" if thinking else "low"} for b in script.bodies)


async def test_claude_accepts_a_cut_that_drops_older_thoughts(isolated_settings, tmp_path, monkeypatch):
    """A long Claude chat past its limit: older turns go as words only, so their signed thoughts and tool calls are left
    out. The real anthropic library and the fake server that checks thoughts as Claude does answer every request: none
    is refused. The kept turns' thoughts were signed to the longer conversation, so Claude drops those itself (the
    block_binding setting, odie.agent.model), as it does when the system prompt changes; this turn's thoughts stay."""
    from odie.app import runner as runner_mod
    from odie.models import Provider, Selection
    from tests.model_fakes import Reply, Script
    from tests.test_model_contract import _served, _thoughts_in
    long = "Aisle seats, window on night flights, extra legroom when it's cheap. " * 40
    turns = [("Remember my seat", [("update_memory", {"title": "Seat", "content": long, "topic": "Travel"}), "Saved."])]
    turns += [(f"Which seat do I like, {n}?", [("fetch_memory", {"title": "Seat"}), "Aisle."]) for n in range(14)]
    replies = []
    for _, steps in turns:
        for step in steps:
            if isinstance(step, str):
                replies.append(Reply(text=step, thinking=True))
            else:
                replies.append(Reply(tool=step[0], args=step[1], thinking=True))
    script = Script(replies)
    _served(monkeypatch, "anthropic", script)
    claude = Selection(Provider("anthropic", "Anthropic", "https://api.anthropic.com/v1", "sk-test", False),
                       "claude-sonnet-5-5", "chat")
    monkeypatch.setattr(runner_mod, "resolve_selection", lambda st, slot="chat": claude)
    store = Store(tmp_path / "assistant.db")
    store.init_schema()
    r = runner_mod.OdieRunner(store)
    await r.load_plugins()
    r._history_limits[SESSION] = 23_500  # 30k characters, ~3k per turn: the cut moves a few times in 15 turns
    for words, _ in turns:
        events = [e async for e in r.chat(words, thinking=True, session_id=SESSION)]
        assert not [e for e in events if e["type"] == "error"], events
    await r.close()
    assert len(script.bodies) == 30 and script.refused == []
    assert script.dropped  # the kept turns' stale thoughts, dropped by Claude rather than refused
    kept = len(_thoughts_in(script.bodies[-1]))
    assert 0 < kept < 29  # the kept turns' thoughts only, not every earlier step's


async def test_a_background_checks_system_prompt_is_the_same_every_time(isolated_settings, tmp_path, monkeypatch):
    """A background check (the watch, a tracker) gets the time in its message, not its system prompt, so one check's
    system prompt and tools are the next one's too and come from the provider's cache (they changed every run)."""
    from google.adk.runners import Runner

    from odie.app import runner as runner_mod
    store = Store(tmp_path / "assistant.db")
    store.init_schema()
    r = runner_mod.OdieRunner(store)
    seen = []

    async def capture(self, **kw):
        instruction = self.app.root_agent.instruction  # a function handing the text over as written
        seen.append((instruction(None), kw["new_message"].parts[0].text))
        return
        yield
    monkeypatch.setattr(Runner, "run_async", capture)
    class Clock:
        """09:00 for the first check, 09:30 for the second."""
        @staticmethod
        def now(tz=None):
            from datetime import datetime
            return datetime(2026, 10, 12, 9, 0 if not seen else 30, tzinfo=tz)
    monkeypatch.setattr(runner_mod, "datetime", Clock)
    await r.background_turn("Run the watch check.", instruction="Watch skill.")
    await r.background_turn("Run the watch check.", instruction="Watch skill.")
    await r.close()
    (first_system, first_message), (second_system, second_message) = seen
    assert first_system == second_system and "09:" not in first_system
    assert first_message.startswith("It is Monday 12 October 2026, 09:00") and first_message.endswith("Run the watch check.")
    assert second_message.startswith("It is Monday 12 October 2026, 09:30")


async def test_a_loaded_skill_says_its_instructions_stay(tmp_path):
    """load_skill's result is kept in the conversation as sent: the model is told it needn't load the skill again."""
    from types import SimpleNamespace

    from odie.agent.callbacks import SKILL_STAYS, OdiePlugin
    store = Store(tmp_path / "a.db")
    store.init_schema()
    plugin = OdiePlugin(store)
    ctx = SimpleNamespace(invocation_id="i1", session=SimpleNamespace(id="chat-1"))
    loaded = {"skill_name": "trackers", "instructions": "Use track…", "frontmatter": {}}
    out = await plugin.after_tool_callback(tool=SimpleNamespace(name="load_skill"), tool_args={"skill_name": "trackers"},
                                           tool_context=ctx, result=loaded)
    assert out == {**loaded, "note": SKILL_STAYS}
    missing = {"error": "Skill 'nope' not found.", "error_code": "SKILL_NOT_FOUND"}
    assert await plugin.after_tool_callback(tool=SimpleNamespace(name="load_skill"), tool_args={"skill_name": "nope"},
                                            tool_context=ctx, result=missing) is None
