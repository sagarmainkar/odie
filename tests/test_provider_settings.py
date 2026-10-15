"""Item 4 (2026-10-11): each built-in provider's address from <ID>_BASE_URL, the fallback model when nothing is chosen,
and chat's temperature as the Creativity setting."""
import json
from pathlib import Path

import httpx
import pytest
from google.adk.agents import LlmAgent
from google.adk.agents.run_config import RunConfig, StreamingMode
from google.adk.apps import App
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from odie import models
from odie.models import (BASE_URL_ENV, FALLBACK_SETTING, PRESET_BY_ID, PRESETS, Provider, Selection, default_providers,
                         pick_fallback, provider_base_url, refresh_fallback, refresh_fallback_at_startup, resolve_selection)
from odie.secrets import env_file, save_secret
from odie.store.db import Store
from tests.model_fakes import Reply, Script

REAL_ASK_LOCAL_PROVIDERS = models.ask_local_providers  # before conftest's no_fallback_probe replaces it
REAL_ENV = Path("~/.odie/.env").expanduser()


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in BASE_URL_ENV.values():
        monkeypatch.delenv(name, raising=False)
    for p in PRESETS:
        monkeypatch.delenv(p.env, raising=False)
    assert env_file() != REAL_ENV  # conftest's no_real_secrets: these tests write to a throwaway .env


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "a.db")
    s.init_schema()
    return s


def _answers(*entries):
    """A fake ask_local_providers: LM Studio and Ollama as listed here; any not listed doesn't answer."""
    given = {e["id"]: e for e in entries}

    async def ask(transport=None):
        out = []
        for pid in ("lmstudio", "ollama"):
            out.append(given.get(pid, {"id": pid, "name": pid, "local": True, "models": [], "error": "ConnectError"}))
        return out
    return ask


def _listed(pid, *model_ids):
    return {"id": pid, "name": pid, "local": True, "models": [{"id": m, "local": True} for m in model_ids], "error": None}


# ── 1. Provider addresses ──

def test_base_url_is_the_default_until_the_env_names_another(monkeypatch):
    assert provider_base_url("ollama", "http://localhost:11434/v1") == "http://localhost:11434/v1"
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://studio.local:11434/v1/")
    assert provider_base_url("ollama", "http://localhost:11434/v1") == "http://studio.local:11434/v1"  # trailing / dropped


def test_base_url_is_read_from_the_env_file_on_every_call():
    assert provider_base_url("openai", "https://api.openai.com/v1") == "https://api.openai.com/v1"
    save_secret("OPENAI_BASE_URL", "https://gateway.example/openai/v1")  # edited while Odie runs: no reload, no restart
    assert provider_base_url("openai", "https://api.openai.com/v1") == "https://gateway.example/openai/v1"


def test_every_built_in_provider_takes_its_address_from_the_env(monkeypatch):
    for p in PRESETS:
        save_secret(p.env, "k-1")
    monkeypatch.setenv("LM_STUDIO_BASE_URL", "http://mini.local:1234/v1")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://mini.local:11434/v1")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://oa.proxy/v1")
    monkeypatch.setenv("OPENROUTER_BASE_URL", "https://or.proxy/api/v1")
    monkeypatch.setenv("GEMINI_BASE_URL", "https://gm.proxy/openai")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://claude.proxy")  # the root, as the anthropic library takes it
    urls = {p.id: p.base_url for p in default_providers()}
    assert urls == {"lmstudio": "http://mini.local:1234/v1", "ollama": "http://mini.local:11434/v1", "openai": "https://oa.proxy/v1",
                    "openrouter": "https://or.proxy/api/v1", "gemini": "https://gm.proxy/openai",
                    "anthropic": "https://claude.proxy/v1"}  # /v1 added: Odie lists Claude's models there


def test_unset_addresses_stay_the_presets_own():
    for p in PRESETS:
        save_secret(p.env, "k-1")
    urls = {p.id: p.base_url for p in default_providers()}
    assert urls["ollama"] == "http://localhost:11434/v1" and urls["lmstudio"].endswith(":1234/v1")
    assert all(urls[p.id] == p.base_url for p in PRESETS)


def _claude(base_url: str) -> Provider:
    return Provider("anthropic", "Claude", base_url, "sk-ant-test", False)


def test_claude_keeps_litellms_own_address_when_unset():
    from odie.agent.model import model_for
    llm = model_for(Selection(_claude(PRESET_BY_ID["anthropic"].base_url), "claude-sonnet-5-5", "chat"), False)
    assert "api_base" not in llm._additional_args  # litellm's default, as before
    assert llm._additional_args["api_key"] == "sk-ant-test"


async def test_claude_requests_go_to_anthropic_base_url(monkeypatch):
    """Through litellm's real HTTP over a fake server: the override reaches litellm as the root, and its requests land on
    <root>/v1/messages (not /v1/v1)."""
    from odie.agent.model import model_for
    from tests.test_model_contract import _served
    script = Script([Reply(text="hello")])
    requests = _served(monkeypatch, "anthropic", script)
    save_secret("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://claude.proxy/v1")
    provider = next(p for p in default_providers() if p.id == "anthropic")
    llm = model_for(Selection(provider, "claude-sonnet-5-5", "chat"), False)
    assert llm._additional_args["api_base"] == "https://claude.proxy"
    from google.adk.models.llm_request import LlmRequest
    from google.genai import types
    req = LlmRequest(model=llm.model, contents=[types.Content(role="user", parts=[types.Part(text="hi")])],
                     config=types.GenerateContentConfig(system_instruction="You are Odie."))
    out = [r async for r in llm.generate_content_async(req, stream=False)]
    assert out[-1].content.parts[-1].text == "hello"
    assert [str(r.url) for r in requests] == ["https://claude.proxy/v1/messages"]


async def test_model_list_shows_each_address_and_how_to_change_it(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://mini.local:11434/v1")
    custom = Provider("mine", "Mine", "https://api.example/v1", "k", False)

    def handler(req):
        return httpx.Response(200, json={"data": [{"id": "m1"}]})
    from odie.models import list_models
    out = {e["id"]: e for e in await list_models(default_providers() + [custom], transport=httpx.MockTransport(handler))}
    assert out["ollama"]["base_url"] == "http://mini.local:11434/v1" and out["ollama"]["base_url_env"] == "OLLAMA_BASE_URL"
    assert out["lmstudio"]["base_url_env"] == "LM_STUDIO_BASE_URL"
    assert out["mine"]["base_url"] == "https://api.example/v1" and out["mine"]["base_url_env"] is None


# ── 2. The fallback model ──

MODEL = "gemma-4-26b-a4b-it-qat"
OFF = {"models": [], "error": "ConnectError", "local": True}


def test_fallback_prefers_lm_studio_with_the_configured_model():
    listing = [_listed("lmstudio", "qwen3.8-27b", MODEL), _listed("ollama", "glm-5.3-flash:cloud")]
    assert pick_fallback(listing, [], MODEL) == {"provider": "lmstudio", "model": MODEL}


def test_fallback_takes_the_first_listed_model_when_the_configured_one_isnt_there():
    listing = [_listed("lmstudio", "qwen3.8-27b", "gemma-4-12b"), {"id": "ollama", **OFF}]
    assert pick_fallback(listing, [], MODEL) == {"provider": "lmstudio", "model": "qwen3.8-27b"}


def test_fallback_moves_on_to_ollama_when_lm_studio_is_off_or_empty():
    worked_example = [{"id": "lmstudio", **OFF}, _listed("ollama", "glm-5.3-flash:cloud")]
    assert pick_fallback(worked_example, [], MODEL) == {"provider": "ollama", "model": "glm-5.3-flash:cloud"}
    no_chat_models = [_listed("lmstudio"), _listed("ollama", "glm-5.3-flash:cloud")]
    assert pick_fallback(no_chat_models, [], MODEL) == {"provider": "ollama", "model": "glm-5.3-flash:cloud"}


def test_fallback_then_takes_the_first_cloud_preset_with_a_key():
    both_off = [{"id": "lmstudio", **OFF}, {"id": "ollama", **OFF}]
    keyed = [PRESET_BY_ID["openai"], PRESET_BY_ID["anthropic"]]
    assert pick_fallback(both_off, keyed, MODEL) == {"provider": "openai", "model": "gpt-5.5"}
    assert pick_fallback(both_off, [PRESET_BY_ID["anthropic"]], MODEL) == {"provider": "anthropic", "model": "claude-sonnet-5-5"}
    assert pick_fallback(both_off, [], MODEL) is None


def test_every_preset_has_a_default_model():
    assert {p.id: p.default_model for p in PRESETS} == {"openai": "gpt-5.5", "openrouter": "anthropic/claude-sonnet-5-5",
                                                        "gemini": "gemini-3-pro", "anthropic": "claude-sonnet-5-5"}


async def test_nothing_chosen_uses_the_cached_fallback(store, monkeypatch):
    sel = resolve_selection(store)
    assert (sel.provider.id, sel.model) == ("lmstudio", MODEL)  # nothing worked out yet: today's behaviour
    monkeypatch.setattr(models, "ask_local_providers", _answers(_listed("ollama", "glm-5.3-flash:cloud")))
    assert await refresh_fallback(store) == {"provider": "ollama", "model": "glm-5.3-flash:cloud"}
    sel = resolve_selection(store)
    assert (sel.provider.id, sel.model) == ("ollama", "glm-5.3-flash:cloud")
    store.set_setting("model.chat", {"provider": "lmstudio", "model": "qwen3.8-27b"})
    assert resolve_selection(store).model == "qwen3.8-27b"  # a chosen model always wins
    store.set_setting("model.chat", {"provider": "gone", "model": "x"})
    assert resolve_selection(store).provider.id == "ollama"  # its provider is gone: the fallback


async def test_a_cloud_fallback_needs_its_key_to_still_be_there(store):
    save_secret("ANTHROPIC_API_KEY", "sk-ant-test")
    assert await refresh_fallback(store) == {"provider": "anthropic", "model": "claude-sonnet-5-5"}  # nobody local answers
    assert resolve_selection(store).provider.id == "anthropic"
    from odie.secrets import remove_secret
    remove_secret("ANTHROPIC_API_KEY")
    assert resolve_selection(store).provider.id == "lmstudio"


async def test_the_fallback_asks_the_local_providers_at_their_env_address(store, monkeypatch):
    monkeypatch.setattr(models, "ask_local_providers", REAL_ASK_LOCAL_PROVIDERS)
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://mini.local:11434/v1")
    asked = []

    def handler(req):
        asked.append(str(req.url))
        if req.url.host == "mini.local":
            return httpx.Response(200, json={"data": [{"id": "glm-5.3-flash:cloud"}]})
        return httpx.Response(503)
    picked = await refresh_fallback(store, transport=httpx.MockTransport(handler))
    assert picked == {"provider": "ollama", "model": "glm-5.3-flash:cloud"}
    assert "http://mini.local:11434/v1/models" in asked
    assert store.get_setting(FALLBACK_SETTING) == picked


async def test_startup_asks_again_until_lm_studio_answers(store, monkeypatch):
    calls = []
    answers = [_answers(_listed("ollama", "glm-5.3-flash:cloud")), _answers(_listed("lmstudio", MODEL))]

    async def ask(transport=None):
        calls.append(1)
        fake = answers[min(len(calls), len(answers)) - 1]
        return await fake()
    monkeypatch.setattr(models, "ask_local_providers", ask)
    await refresh_fallback_at_startup(store, waits=(0, 0, 0))
    assert store.get_setting(FALLBACK_SETTING) == {"provider": "lmstudio", "model": MODEL}
    assert len(calls) == 2  # stopped once LM Studio answered


@pytest.fixture
async def client(isolated_settings, tmp_path):
    from odie.app.main import create_app
    from tests.test_models import FakeRunner
    s = Store(tmp_path / "api.db")
    s.init_schema()
    app = create_app(runner=FakeRunner(), store=s)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        async with app.router.lifespan_context(app):
            yield c, s


async def test_changing_providers_works_the_fallback_out_again(client, monkeypatch):
    import asyncio

    from odie.app import routes
    c, s = client
    save_secret("OPENAI_API_KEY", "sk-1")
    r = await c.post("/api/models/providers", json={"name": "Mine", "base_url": "https://api.example/v1"})
    assert r.status_code == 200
    await asyncio.gather(*routes._fallback_refreshes)
    assert s.get_setting(FALLBACK_SETTING) == {"provider": "openai", "model": "gpt-5.5"}


# ── 3. Chat temperature: the Creativity setting ──

def test_chat_temperature_is_the_setting_or_the_default(store):
    from odie.sampling import CHAT_TEMPERATURE_DEFAULT, CHAT_TEMPERATURE_SETTING, chat_temperature
    assert chat_temperature(store) == CHAT_TEMPERATURE_DEFAULT == 0.7
    store.set_setting(CHAT_TEMPERATURE_SETTING, 1.1)
    assert chat_temperature(store) == 1.1
    for bad in (5, -1, "hot", True, None):
        store.set_setting(CHAT_TEMPERATURE_SETTING, bad)
        assert chat_temperature(store) == 0.7


async def test_creativity_api(client):
    c, s = client
    r = (await c.get("/api/models")).json()
    assert r["creativity"] == {"value": 0.7, "default": 0.7, "min": 0.0, "max": 1.2, "step": 0.1}
    r = await c.put("/api/models/creativity", json={"temperature": 0.30000000004})
    assert r.status_code == 200 and r.json()["creativity"]["value"] == 0.3
    assert s.get_setting("chat.temperature") == 0.3
    assert (await c.put("/api/models/creativity", json={"temperature": 1.5})).status_code == 422
    assert (await c.put("/api/models/creativity", json={"temperature": -0.1})).status_code == 422
    assert (await c.get("/api/models")).json()["creativity"]["value"] == 0.3


async def test_the_next_message_uses_the_creativity_setting(isolated_settings, tmp_path):
    from odie.app.runner import OdieRunner
    s = Store(tmp_path / "assistant.db")
    s.init_schema()
    r = OdieRunner(s)
    seen = []

    async def fake_run(**kw):
        seen.append((r.agent.generate_content_config.temperature, r.agent.generate_content_config.top_p))
        if False:
            yield None
    r.runner.run_async = fake_run
    [e async for e in r.chat("hi", session_id="t-1")]
    s.set_setting("chat.temperature", 1.0)
    [e async for e in r.chat("again", session_id="t-1")]
    assert seen == [(0.7, 0.95), (1.0, 0.95)]
    await r.close()


async def test_the_next_message_uses_a_new_fallback(isolated_settings, tmp_path):
    from odie.app.runner import OdieRunner
    s = Store(tmp_path / "assistant.db")
    s.init_schema()
    r = OdieRunner(s)

    async def fake_run(**kw):
        if False:
            yield None
    r.runner.run_async = fake_run
    [e async for e in r.chat("hi", session_id="t-1")]
    assert r.agent.model.model == "openai/" + MODEL          # litellm's name for it (odie.agent.model.litellm_model)
    s.set_setting(FALLBACK_SETTING, {"provider": "ollama", "model": "glm-5.3-flash:cloud"})
    [e async for e in r.chat("again", session_id="t-1")]
    assert r.agent.model.model == "openai/glm-5.3-flash:cloud"
    await r.close()


async def _one_turn(store, provider: str, monkeypatch) -> dict:
    """One chat turn with the agent's own chat sampling, against the provider's fake server; the request body sent."""
    from odie.agent.agent import chat_generate_config
    from odie.agent.model import model_for
    from tests.test_model_contract import PATHS, _served
    script = Script([Reply(text="Hello.")])
    _served(monkeypatch, provider, script)
    base, model = PATHS[provider]
    llm = model_for(Selection(Provider(provider, provider, base, "sk-test", provider != "anthropic"), model, "chat"), False)
    agent = LlmAgent(name="odie", model=llm, instruction="You are Odie.", generate_content_config=chat_generate_config(store))
    sessions = InMemorySessionService()
    runner = Runner(app=App(name="odie_creativity", root_agent=agent), session_service=sessions)
    sess = await sessions.create_session(app_name="odie_creativity", user_id="u")
    async for _ in runner.run_async(user_id="u", session_id=sess.id, run_config=RunConfig(streaming_mode=StreamingMode.SSE),
                                    new_message=types.Content(role="user", parts=[types.Part(text="Hi")])):
        pass
    await runner.close()
    return script.bodies[0]


async def test_creativity_reaches_the_model_but_not_claude(store, isolated_settings, monkeypatch):
    store.set_setting("chat.temperature", 1.1)
    body = await _one_turn(store, "ollama", monkeypatch)
    assert body["temperature"] == 1.1 and body["top_p"] == 0.95
    body = await _one_turn(store, "anthropic", monkeypatch)
    assert not {"temperature", "top_p", "top_k"} & set(body)  # Claude sets its own
    assert json.dumps(body)  # a real request was sent
