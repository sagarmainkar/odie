"""Prompt caching (2026-10-08, on litellm since 2026-10-14): one switch for all of Odie (ADK's context_cache_config).
Providers that cache a repeated prompt start by themselves (OpenAI-style ones) need nothing more; for Claude, ADK has
litellm mark the system prompt and the latest message so Claude bills the repeated start at the cache rate. Each
reply's cached share is kept, whichever provider it came from, so Settings can show whether caching works."""
from types import SimpleNamespace

import pytest
from google.adk.agents.context_cache_config import ContextCacheConfig
from google.adk.models.lite_llm import LiteLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from odie.agent.model import model_for
from odie.models import Provider, Selection
from tests.test_api import client  # noqa: F401  (fixture)


@pytest.fixture
def store(tmp_path):
    from odie.store.db import Store
    s = Store(tmp_path / "a.db")
    s.init_schema()
    return s


def _sel(pid, model, key="sk-test", base="https://api.example/v1"):
    return Selection(Provider(pid, pid.title(), base, key, False), model, "chat")


async def _one_step(llm, monkeypatch, provider: str, cfg: types.GenerateContentConfig, contents=None, cached: bool = True) -> dict:
    """One request through the real adapter over the provider's fake server, as ADK makes it; the body sent."""
    from tests.model_fakes import Reply, Script
    from tests.test_model_contract import _served
    script = Script([Reply(text="Hi")])
    _served(monkeypatch, provider, script)
    contents = contents or [types.Content(role="user", parts=[types.Part(text="What's on today?")])]
    req = LlmRequest(model=llm.model, contents=contents, config=cfg)
    if cached:
        req.cache_config = ContextCacheConfig()
    async for _ in llm.generate_content_async(req, stream=False):
        pass
    return script.bodies[0]


def test_every_provider_goes_through_litellm():
    m = model_for(_sel("anthropic", "claude-sonnet-5-5", base="https://api.anthropic.com/v1"), False)
    assert isinstance(m, LiteLlm) and m.model == "anthropic/claude-sonnet-5-5"
    assert m._additional_args["api_key"] == "sk-test" and m._additional_args["max_tokens"] >= 16000
    other = model_for(_sel("openai", "gpt-5.5"), False)
    assert isinstance(other, LiteLlm) and other.model == "openai/gpt-5.5"  # OpenAI-style providers cache a repeated start by themselves


async def test_claude_requests_mark_the_system_prompt_and_the_latest_message(monkeypatch):
    """ADK hands litellm two cache points, the system prompt and the latest message; litellm marks them for Claude and
    drops the marks for a provider that caches by itself."""
    llm = model_for(_sel("anthropic", "claude-sonnet-5-5", base="https://api.anthropic.com/v1"), False)
    cfg = types.GenerateContentConfig(system_instruction="You are Odie.", tools=[types.Tool(function_declarations=[
        types.FunctionDeclaration(name="now", description="The time", parameters_json_schema={"type": "object", "properties": {}})])])
    sent = await _one_step(llm, monkeypatch, "anthropic", cfg)
    assert sent["system"][0]["cache_control"]["type"] == "ephemeral"
    assert sent["messages"][-1]["content"][-1]["cache_control"]["type"] == "ephemeral"
    assert [t["name"] for t in sent["tools"]] == ["now"]


async def test_caching_is_on_for_chat_and_background_turns(store, isolated_settings, monkeypatch):
    """With ADK's real Runner (a fake that took any keyword hid a crash: every background turn failed with "Runner.__init__()
    got an unexpected keyword argument 'context_cache_config'", 2026-10-08)."""
    from google.adk.runners import Runner

    from odie.app import runner as R
    r = R.OdieRunner(store)
    assert isinstance(r.runner.context_cache_config, ContextCacheConfig)
    made = []

    async def nothing(self, **kw):
        made.append(self)
        return
        yield
    monkeypatch.setattr(Runner, "run_async", nothing)
    await r.background_turn("check")
    assert made and isinstance(made[0].context_cache_config, ContextCacheConfig)
    await r.close()


async def test_each_replys_cached_share_is_kept(store):
    from odie.agent.callbacks import OdiePlugin
    from odie.agent.usage import last_usage
    p = OdiePlugin(store)
    resp = LlmResponse(usage_metadata=types.GenerateContentResponseUsageMetadata(prompt_token_count=10_000, cached_content_token_count=9_000,
                                                                                 candidates_token_count=300))
    await p.after_model_callback(callback_context=SimpleNamespace(invocation_id="i1"), llm_response=resp)
    u = last_usage(store)
    assert (u["input"], u["cached"], u["output"]) == (10_000, 9_000, 300) and u["at"]
    await p.after_model_callback(callback_context=SimpleNamespace(invocation_id="i1"), llm_response=LlmResponse())  # no usage: kept as was
    assert last_usage(store)["cached"] == 9_000


async def test_settings_can_read_the_latest_cached_share(client):
    from odie.agent import usage
    c, s = client if isinstance(client, tuple) else (client, None)
    st = s or c._transport.app.state.store
    assert (await c.get("/api/models/usage")).json() == {"usage": None}
    usage.record(st, types.GenerateContentResponseUsageMetadata(prompt_token_count=9_800, cached_content_token_count=8_900, candidates_token_count=250),
                 "claude-sonnet-5-5")
    u = (await c.get("/api/models/usage")).json()["usage"]
    assert (u["input"], u["cached"], u["model"]) == (9_800, 8_900, "claude-sonnet-5-5")


async def test_every_odie_tool_converts_for_claude(store, isolated_settings, tmp_path, monkeypatch):
    """Claude takes tools in its own format: all of Odie's own tools, the browser's and every skill's convert through
    litellm, so switching to Claude can't fail on the first turn."""
    from google.adk.tools import FunctionTool

    from odie.agent.agent import build_agent
    from odie.agent.tools.browser import make_browser_tools, make_signin_tools
    from odie.skills import build_skill_toolset
    tools = [t for t in build_agent(store).tools if isinstance(t, FunctionTool)]
    tools += [*make_browser_tools(store, browser_for=lambda: None), *make_signin_tools(store)]
    ts = build_skill_toolset()
    ctx = SimpleNamespace(state={"_adk_activated_skill_odie": [s.name for s in ts._skills.values()] if hasattr(ts, "_skills") else []},
                          agent_name="odie", invocation_id="i1")
    tools += [t for t in await ts.get_tools(ctx) if isinstance(t, FunctionTool) or hasattr(t, "_get_declaration")]
    decls = [d for t in tools if (d := t._get_declaration()) is not None]
    assert len(decls) > 30
    llm = model_for(_sel("anthropic", "claude-sonnet-5-5", base="https://api.anthropic.com/v1"), False)
    cfg = types.GenerateContentConfig(system_instruction="You are Odie.", tools=[types.Tool(function_declarations=decls)])
    sent = await _one_step(llm, monkeypatch, "anthropic", cfg, contents=[types.Content(role="user", parts=[types.Part(text="hi")])])
    assert {d.name for d in decls} == {t["name"] for t in sent["tools"]}
    assert all(t["input_schema"].get("type") == "object" for t in sent["tools"])


async def test_claude_gets_no_sampling_settings_but_other_models_keep_them(monkeypatch):
    """Claude takes no temperature, top_p or top_k while it thinks, and litellm drops them (drop_params); Ollama and LM
    Studio keep Odie's (0.7 chat, 0.3 background)."""
    cfg = types.GenerateContentConfig(system_instruction="You are Odie.", temperature=0.7, top_p=0.95, top_k=40)
    claude = model_for(_sel("anthropic", "claude-sonnet-5-5", base="https://api.anthropic.com/v1"), False)
    sent = await _one_step(claude, monkeypatch, "anthropic", cfg)
    assert not ({"temperature", "top_p", "top_k"} & set(sent)) and sent["thinking"]["type"] == "adaptive"
    ollama = model_for(_sel("ollama", "glm-5.3-flash:cloud", base="http://localhost:11434/v1"), False)
    sent = await _one_step(ollama, monkeypatch, "ollama", cfg)
    assert sent["temperature"] == 0.7 and sent["top_p"] == 0.95


async def test_one_shot_jobs_send_claude_no_sampling_settings(store, monkeypatch):
    """The brief, the memory review and the day summary call the model through the same litellm call: the same rule holds."""
    from tests.model_fakes import Reply, Script
    from tests.test_model_contract import _served

    from odie import models
    script = Script([Reply(text="ok")])
    _served(monkeypatch, "anthropic", script)
    monkeypatch.setattr(models, "resolve_selection", lambda st, slot: _sel("anthropic", "claude-sonnet-5-5", base="https://api.anthropic.com/v1"))
    assert await models.chat_completion(store, "chat", [{"role": "user", "content": "hi"}], temperature=0.3, max_tokens=100) == "ok"
    assert "temperature" not in script.bodies[-1] and script.bodies[-1]["max_tokens"] == 100
    script = Script([Reply(text="ok")])
    _served(monkeypatch, "ollama", script)
    monkeypatch.setattr(models, "resolve_selection", lambda st, slot: _sel("ollama", "glm-5.3-flash:cloud", base="http://localhost:11434/v1"))
    await models.chat_completion(store, "chat", [{"role": "user", "content": "hi"}], temperature=0.3)
    assert script.bodies[-1]["temperature"] == 0.3 and script.bodies[-1]["reasoning_effort"] == "low"  # every other provider: as before
