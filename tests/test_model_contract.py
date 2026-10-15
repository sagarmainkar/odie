"""The same conversation through every model path Odie has (2026-10-08, on litellm since 2026-10-14): LM Studio and
Ollama (OpenAI-style) and Claude, streaming as chat does and not as background checks do. Each runs through ADK's real
Runner with Odie's plugin (which shortens old tool results) and the cache setting, against a fake server that speaks the
provider's real wire format (tests/model_fakes.py), reached through litellm's own HTTP. A change that breaks one path
fails here, not on the phone. The live version of these checks is scripts/model_check.sh."""
import json

import httpx
import pytest
from google.adk.agents import LlmAgent
from google.adk.agents.run_config import RunConfig, StreamingMode
from google.adk.apps import App
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools import FunctionTool
from google.genai import types

from odie.agent.callbacks import OdiePlugin
from odie.agent.model import CLAUDE_BETA_HEADER, CLAUDE_THINKING, model_for
from odie.agent.usage import CACHE, last_usage
from odie.models import Provider, Selection
from tests.model_fakes import Reply, Script, anthropic_handler, openai_handler

PATHS = {
    "ollama": ("http://localhost:11434/v1", "glm-5.3-flash:cloud"),
    "lmstudio": ("http://localhost:1234/v1", "gemma-4-26b-a4b-it-qat"),
    "anthropic": ("https://api.anthropic.com/v1", "claude-sonnet-5-5"),
}
STEPS_NOTE = "\n\n[You have 4 steps left in this turn: answer now with what you found.]"


@pytest.fixture
def store(tmp_path):
    from odie.store.db import Store
    s = Store(tmp_path / "a.db")
    s.init_schema()
    return s


def now() -> str:
    """The current time in Pune."""
    return "18:52"


def _served(monkeypatch, provider: str, script: Script) -> list[httpx.Request]:
    """Every request litellm sends, whichever HTTP client it uses (the OpenAI library's, or its own for Claude), lands on
    the fake server for this provider. Returns the list the requests themselves are kept in (for headers and URLs)."""
    handler = anthropic_handler(script, httpx) if provider == "anthropic" else openai_handler(script, httpx)
    requests: list[httpx.Request] = []

    async def send(self, request, **kw):
        requests.append(request)
        response = handler(request)
        response.request = request
        return response
    monkeypatch.setattr(httpx.AsyncClient, "send", send)
    return requests


def _selection(provider: str, model: str | None = None) -> Selection:
    base, default_model = PATHS[provider]
    return Selection(Provider(provider, provider, base, "sk-test", provider != "anthropic"), model or default_model, "chat")


async def _converse(store, provider: str, streaming: bool, monkeypatch, model: str | None = None, thinking: bool = False,
                    script: Script | None = None, questions=("What time is it?", "And in two hours?"), note_after_call: bool = False):
    """Two turns: "What time is it?" (a tool call, then the answer from its result), then "And in two hours?".
    note_after_call: the system prompt grows after a tool call (Odie's late-turn note), as a before-model callback."""
    script = script or Script([Reply(tool="now", thinking=True), Reply(text="It's 18:52."), Reply(text="At 20:52.")])
    requests = _served(monkeypatch, provider, script)
    llm = model_for(_selection(provider, model), thinking)
    called = {"n": 0}

    def before_model(callback_context, llm_request):
        if note_after_call and called["n"] >= 1 and llm_request.config is not None:
            llm_request.config.system_instruction = "You are Odie." + STEPS_NOTE
        called["n"] += 1
        return None
    agent = LlmAgent(name="odie", model=llm, tools=[FunctionTool(now)], instruction="You are Odie.", before_model_callback=before_model,
                     generate_content_config=types.GenerateContentConfig(temperature=0.7, top_p=0.95))
    sessions = InMemorySessionService()
    runner = Runner(app=App(name="odie_contract", root_agent=agent, plugins=[OdiePlugin(store)], context_cache_config=CACHE),
                    session_service=sessions)
    sess = await sessions.create_session(app_name="odie_contract", user_id="u")
    cfg = RunConfig(streaming_mode=StreamingMode.SSE if streaming else StreamingMode.NONE)
    said = []
    for q in questions:
        async for ev in runner.run_async(user_id="u", session_id=sess.id, run_config=cfg,
                                         new_message=types.Content(role="user", parts=[types.Part(text=q)])):
            if ev.partial or not ev.content:
                continue
            said += [p.text for p in ev.content.parts or [] if p.text and not p.thought]
    await runner.close()
    script.requests = requests
    return said, script


def _thoughts_in(body: dict) -> list[dict]:
    """The thinking blocks a request sends back to Claude."""
    blocks = [c for m in body["messages"] for c in (m["content"] if isinstance(m["content"], list) else [])]
    return [c for c in blocks if c.get("type") in ("thinking", "redacted_thinking")]


def _append_only(bodies: list[dict]) -> bool:
    """Every request starts with the whole request before it, unchanged (cache marks aside: odie.prefix_check)."""
    from odie.prefix_check import compare, pieces
    return all(compare("", pieces(a), pieces(b)).appended for a, b in zip(bodies, bodies[1:]))


@pytest.mark.parametrize("streaming", [True, False], ids=["chat-streaming", "background"])
@pytest.mark.parametrize("provider", list(PATHS))
async def test_the_same_conversation_works_on_every_path(provider, streaming, store, isolated_settings, monkeypatch):
    said, script = await _converse(store, provider, streaming, monkeypatch)
    assert "It's 18:52." in said and "At 20:52." in said  # the tool's answer used, then a second turn
    assert len(script.bodies) == 3
    assert "18:52" in json.dumps(script.bodies[1])                      # the tool result reached the model
    assert "18:52" in json.dumps(script.bodies[2])                      # next turn: the result still there, as it was
    assert _append_only(script.bodies)                                   # so the provider's prompt cache holds
    assert last_usage(store)["cached"] == 90                             # the provider's cached share is read
    assert script.refused == [] and script.dropped == []
    if provider == "anthropic":
        for b in script.bodies:
            assert not {"temperature", "top_p", "top_k"} & set(b)          # litellm drops what Claude refuses while thinking
            assert b["thinking"] == CLAUDE_THINKING and b["output_config"] == {"effort": "low"}
        assert all(r.headers["anthropic-beta"] == CLAUDE_BETA_HEADER["anthropic-beta"] for r in script.requests)
        assert b["system"][0]["cache_control"]["type"] == "ephemeral"       # caching marks
        assert len(_thoughts_in(script.bodies[1])) == 1                    # the thought from the tool call goes back with its result
    else:
        for b in script.bodies:
            assert b["temperature"] == 0.7 and b["reasoning_effort"] == "low"  # other providers keep sampling; the same word
        assert script.bodies[1]["messages"][-1]["role"] == "tool"            # Gemma 4 on LM Studio too (adk-python #6482, fixed in 2.12)
    key_header = "x-api-key" if provider == "anthropic" else "authorization"   # each API's own way of carrying the key
    assert all(r.headers[key_header].endswith("sk-test") for r in script.requests)


@pytest.mark.parametrize("model", ["claude-sonnet-5-5", "claude-opus-5-5"])
@pytest.mark.parametrize("thinking", [False, True], ids=["off", "think-harder"])
async def test_claude_gets_the_same_word_as_everyone_and_keeps_its_thoughts(model, thinking, store, isolated_settings, monkeypatch):
    """Every Claude: adaptive thinking at the turn's effort (low, or medium with Think harder), its thoughts back after a
    tool call and in the next turn (the conversation is sent as it was, so they still fit), nothing refused or dropped."""
    script = Script([Reply(tool="now", thinking=True), Reply(text="It's 18:52.", thinking=True), Reply(text="At 20:52.", thinking=True)])
    said, script = await _converse(store, "anthropic", True, monkeypatch, model=model, thinking=thinking, script=script)
    assert "It's 18:52." in said and "At 20:52." in said
    assert script.refused == [] and script.dropped == []
    for b in script.bodies:
        assert b["thinking"] == CLAUDE_THINKING
        assert b["output_config"] == {"effort": "medium" if thinking else "low"}
        assert b["model"] == model
    first, after_tool, next_turn = script.bodies
    assert _thoughts_in(first) == []
    assert len(_thoughts_in(after_tool)) == 1        # this turn's thought, back with the tool's result
    assert len(_thoughts_in(next_turn)) == 2         # the first turn's thoughts, kept
    assert _append_only(script.bodies)


async def test_a_thought_that_no_longer_fits_is_dropped_by_claude_not_refused(store, isolated_settings, monkeypatch):
    """Odie's late-turn note changes the system prompt after a tool call. Claude's signed thought from before the note no
    longer fits; with the binding setting Claude drops it and answers (live: without it, the turn died with "The block
    is bound to a different conversation", 2026-10-14)."""
    script = Script([Reply(tool="now", thinking=True), Reply(text="It's 18:52.", thinking=True)])
    said, script = await _converse(store, "anthropic", True, monkeypatch, script=script, questions=("What time is it?",), note_after_call=True)
    assert said == ["It's 18:52."]
    assert script.refused == [] and len(script.dropped) == 1
    assert "different conversation" in script.dropped[0]
    assert STEPS_NOTE.strip() in script.bodies[1]["system"][0]["text"]


async def test_the_live_check_reports_each_step(store, isolated_settings, monkeypatch):
    """scripts/model_check.sh, against the fake server: every step reported, nothing left failing."""
    from odie import model_check
    script = Script([Reply(tool="now"), Reply(text="It's 18:52."), Reply(text="At 20:52."),
                     Reply(tool="load_skill", args={"skill_name": "world-clock"}), Reply(tool="utc_now"), Reply(text="38 minutes."),
                     Reply(tool="now"), Reply(text="It is 18:52 now.")])
    _served(monkeypatch, "ollama", script)
    monkeypatch.setattr("odie.models.all_providers", lambda st: [Provider("ollama", "Ollama", "http://localhost:11434/v1", None, True)])
    results = await model_check.run("ollama", "glm-5.3-flash:cloud")
    assert [n for n, ok, _ in results if not ok] == []
    assert [n for n, _, _ in results] == ["tool call (chat, streaming)", "answer from the tool's result", "second turn, the first sent as before",
                                         "prompt cache", "a skill loaded mid-turn, then its tool", "one turn as background checks run it",
                                         "the effort word on every request"]
    tools_seen = [[t["function"]["name"] for t in b.get("tools", [])] for b in script.bodies[3:5]]
    assert "utc_now" in tools_seen[0] and tools_seen[0] == tools_seen[1]  # declared from the start: the list never changes


async def test_the_live_check_on_claude_reports_the_binding(store, isolated_settings, monkeypatch):
    from odie import model_check
    script = Script([Reply(tool="now", thinking=True), Reply(text="It's 18:52."), Reply(text="At 20:52."),
                     Reply(tool="load_skill", args={"skill_name": "world-clock"}), Reply(tool="utc_now"), Reply(text="38 minutes."),
                     Reply(tool="now"), Reply(text="It is 18:52 now.")])
    _served(monkeypatch, "anthropic", script)
    monkeypatch.setattr("odie.models.all_providers", lambda st: [Provider("anthropic", "Claude", "https://api.anthropic.com/v1", "sk-test", False)])
    results = await model_check.run("anthropic", "claude-sonnet-5-5", thinking=True)
    assert [n for n, ok, _ in results if not ok] == []
    assert [n for n, _, _ in results][-2:] == ["the effort word on every request", "Claude drops a stale thought itself"]
    assert "medium" in dict((n, d) for n, _, d in results)["the effort word on every request"]


async def test_the_chat_rebuilds_the_model_when_the_toggle_changes(isolated_settings, tmp_path, monkeypatch):
    """OdieRunner builds a new model whenever "Think harder" changes; the same value keeps it."""
    from odie.app import runner as runner_mod
    from odie.store.db import Store
    claude = _selection("anthropic", "claude-opus-5-5")
    monkeypatch.setattr(runner_mod, "resolve_selection", lambda st, slot="chat": claude)
    s = Store(tmp_path / "assistant.db")
    s.init_schema()
    r = runner_mod.OdieRunner(s)

    async def no_model(**kw):
        if False:
            yield None
    r.runner.run_async = no_model
    seen = []
    for thinking in (True, True, False):
        [e async for e in r.chat("hi", thinking=thinking, session_id="t-1")]
        seen.append(r.agent.model)
    assert [m._additional_args["reasoning_effort"] for m in seen] == ["medium", "medium", "low"]
    assert seen[0] is seen[1] and seen[2] is not seen[1]
    await r.close()
