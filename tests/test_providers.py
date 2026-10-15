import stat

import httpx
import pytest

from pathlib import Path

from odie.models import PRESETS, all_providers, context_window, custom_key_name, list_models, Selection
from odie.secrets import env_file, load_secret, remove_secret, save_secret
from odie.store.db import Store

REAL = Path("~/.odie/.env").expanduser()


@pytest.fixture(autouse=True)
def _no_env_keys(monkeypatch):
    for p in PRESETS:
        monkeypatch.delenv(p.env, raising=False)
    assert env_file() != REAL  # conftest's no_real_secrets: these tests write keys


def _store(tmp_path):
    s = Store(tmp_path / "a.db")
    s.init_schema()
    return s


def test_env_file_follows_config_dir():
    f = env_file()
    save_secret("OPENROUTER_API_KEY", "sk-or-1")
    assert f.exists() and "sk-or-1" in f.read_text()
    assert stat.S_IMODE(f.stat().st_mode) == 0o600
    assert load_secret("OPENROUTER_API_KEY") == "sk-or-1"


def test_save_replaces_keeps_others_and_remove():
    f = env_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("# mine\nTAVILY_API_KEY=t1\nexport OPENAI_API_KEY='old'\n")
    save_secret("OPENAI_API_KEY", "sk-new")
    text = f.read_text()
    assert "# mine" in text and "TAVILY_API_KEY=t1" in text and "old" not in text
    assert load_secret("OPENAI_API_KEY") == "sk-new"
    assert remove_secret("OPENAI_API_KEY") is True
    assert load_secret("OPENAI_API_KEY") is None and load_secret("TAVILY_API_KEY") == "t1"
    assert remove_secret("OPENAI_API_KEY") is False


def test_save_rejects_odd_values():
    for bad in ("", "two words", "a\nB=c", "quote'd", "x#y"):
        with pytest.raises(ValueError):
            save_secret("OPENAI_API_KEY", bad)
    with pytest.raises(ValueError):
        save_secret("lower", "k")


def test_presets_appear_only_with_a_key(tmp_path):
    s = _store(tmp_path)
    assert {p.id for p in all_providers(s)} == {"lmstudio", "ollama"}
    save_secret("GEMINI_API_KEY", "g-1")
    ps = {p.id: p for p in all_providers(s)}
    assert ps["gemini"].api_key == "g-1" and ps["gemini"].local is False
    assert ps["gemini"].base_url == "https://generativelanguage.googleapis.com/v1beta/openai"


def test_custom_provider_key_lives_in_env_file(tmp_path):
    s = _store(tmp_path)
    s.set_setting("providers.custom", [{"id": "my-box", "name": "My box", "base_url": "https://x.example/v1", "reasoning": "openai"}])
    save_secret(custom_key_name("my-box"), "k-9")
    p = {p.id: p for p in all_providers(s)}["my-box"]
    assert p.api_key == "k-9" and custom_key_name("my-box") == "ODIE_PROVIDER_MY_BOX_KEY"
    s.set_setting("providers.custom", [{"id": "old", "name": "Old", "base_url": "https://o.example/v1", "api_key": "legacy"}])
    assert {p.id: p for p in all_providers(s)}["old"].api_key == "legacy"  # older settings still work


async def test_list_models_filters_non_chat_and_anthropic_headers(tmp_path):
    save_secret("OPENAI_API_KEY", "sk-1")
    save_secret("ANTHROPIC_API_KEY", "an-1")
    save_secret("GEMINI_API_KEY", "g-1")
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        host = req.url.host
        seen[host] = req.headers
        if host == "api.openai.com":
            return httpx.Response(200, json={"data": [{"id": i} for i in ("gpt-5.5", "dall-e-3", "tts-1", "text-embedding-3-small",
                                                                          "whisper-1", "omni-moderation-latest", "gpt-realtime", "gpt-image-1")]})
        if host == "api.anthropic.com":
            return httpx.Response(200, json={"data": [{"id": "claude-opus-5-5"}]})
        if host == "generativelanguage.googleapis.com":
            return httpx.Response(200, json={"data": [{"id": "models/gemini-3-pro"}]})
        return httpx.Response(500)
    out = {p["id"]: p for p in await list_models(all_providers(_store(tmp_path)), transport=httpx.MockTransport(handler))}
    assert [m["id"] for m in out["openai"]["models"]] == ["gpt-5.5"]
    assert [m["id"] for m in out["anthropic"]["models"]] == ["claude-opus-5-5"]
    assert seen["api.anthropic.com"]["x-api-key"] == "an-1" and "anthropic-version" in seen["api.anthropic.com"]
    assert [m["id"] for m in out["gemini"]["models"]] == ["gemini-3-pro"]


async def test_cloud_context_window(tmp_path):
    save_secret("OPENROUTER_API_KEY", "or-1")
    save_secret("OPENAI_API_KEY", "sk-1")
    ps = {p.id: p for p in all_providers(_store(tmp_path))}

    def handler(req):
        return httpx.Response(200, json={"data": [{"id": "z-ai/glm-5.3", "context_length": 262144}]})
    t = httpx.MockTransport(handler)
    assert await context_window(Selection(ps["openrouter"], "z-ai/glm-5.3", "chat"), transport=t) == 262144
    assert await context_window(Selection(ps["openai"], "gpt-5.5", "chat"), transport=t) == 128_000


@pytest.fixture
async def client(isolated_settings, tmp_path):
    from odie.app.main import create_app
    from tests.test_models import FakeRunner
    s = _store(tmp_path)
    app = create_app(runner=FakeRunner(), store=s)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        async with app.router.lifespan_context(app):
            yield c, s


async def test_provider_routes_never_return_keys(client, monkeypatch):
    c, s = client
    import odie.app.routes as routes

    async def accept(provider):
        return None
    monkeypatch.setattr(routes, "check_key", accept)
    rows = {p["id"]: p for p in (await c.get("/api/providers")).json()["providers"]}
    assert rows["lmstudio"]["kind"] == "local" and rows["openai"]["connected"] is False and rows["anthropic"]["name"] == "Claude"
    assert rows["lmstudio"]["connected"] is False and rows["ollama"]["connected"] is False  # neither answers in tests

    async def ollama_runs(transport=None):
        return [{"id": "lmstudio", "error": "ConnectError"}, {"id": "ollama", "error": None}]
    monkeypatch.setattr("odie.models.ask_local_providers", ollama_runs)
    rows = {p["id"]: p for p in (await c.get("/api/providers")).json()["providers"]}
    assert rows["ollama"]["connected"] is True and rows["lmstudio"]["connected"] is False
    r = await c.put("/api/providers/openrouter/key", json={"api_key": "sk-or-abc"})
    assert r.status_code == 200 and "sk-or-abc" not in r.text
    assert load_secret("OPENROUTER_API_KEY") == "sk-or-abc"
    body = (await c.get("/api/providers")).text
    assert "sk-or-abc" not in body and '"connected":true' in body.replace(" ", "")
    assert (await c.delete("/api/providers/openrouter/key")).status_code == 200
    assert load_secret("OPENROUTER_API_KEY") is None
    assert (await c.put("/api/providers/nope/key", json={"api_key": "k"})).status_code == 404
    assert (await c.put("/api/providers/openai/key", json={"api_key": "bad key"})).status_code == 422


async def test_rejected_key_is_not_saved(client, monkeypatch):
    c, _ = client
    import odie.app.routes as routes

    async def reject(provider):
        return "OpenAI didn't accept that key."
    monkeypatch.setattr(routes, "check_key", reject)
    r = await c.put("/api/providers/openai/key", json={"api_key": "sk-wrong"})
    assert r.status_code == 422 and "didn't accept" in r.text
    assert load_secret("OPENAI_API_KEY") is None


async def test_custom_provider_key_goes_to_env_file(client):
    c, s = client
    r = await c.post("/api/models/providers", json={"name": "My box", "base_url": "https://x.example/v1", "api_key": "k-1"})
    assert r.status_code == 200
    assert "k-1" not in str(s.get_setting("providers.custom")) and load_secret("ODIE_PROVIDER_MY_BOX_KEY") == "k-1"
    rows = {p["id"]: p for p in (await c.get("/api/providers")).json()["providers"]}
    assert rows["my-box"]["kind"] == "custom" and rows["my-box"]["base_url"] == "https://x.example/v1"
    await c.delete("/api/models/providers/my-box")
    assert load_secret("ODIE_PROVIDER_MY_BOX_KEY") is None


async def test_voice_hides_openai_without_a_key(client):
    c, _ = client
    j = (await c.get("/api/voice")).json()
    assert j["engine"] == "kokoro" and "openai" not in [e["id"] for e in j["engines"]]
    save_secret("OPENAI_API_KEY", "sk-1")
    j = (await c.get("/api/voice")).json()
    assert "openai" in [e["id"] for e in j["engines"]]


def test_a_brain_counts_as_chosen_only_when_someone_picked_it(tmp_path):
    """A fresh install falls back to a built-in default nobody chose: Settings says "No brain yet" instead of naming it."""
    from odie.models import FALLBACK_SETTING, brain_chosen
    from odie.store.db import Store
    s = Store(tmp_path / "a.db")
    s.init_schema()
    assert brain_chosen(s) is False
    s.set_setting(FALLBACK_SETTING, {"provider": "ollama", "model": "glm-5.3-flash:cloud"})
    assert brain_chosen(s) is True
