"""Settings → Providers: every provider's address shown and changed in the app (LM Studio's port, a custom server's
address, name and key), where the change is kept (~/.odie/.env for the built-ins) and what wins over what."""
import asyncio
from pathlib import Path

import httpx
import pytest

from odie import models
from odie.models import (BASE_URL_ENV, PRESETS, Provider, address_problem, check_address, custom_key_name,
                         default_providers, lm_studio_url, local_providers, reset_address, resolve_selection,
                         save_address)
from odie.secrets import env_file, load_secret, save_secret
from odie.store.db import Store

REAL_ENV = Path("~/.odie/.env").expanduser()


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in BASE_URL_ENV.values():
        monkeypatch.delenv(name, raising=False)
    for p in PRESETS:
        monkeypatch.delenv(p.env, raising=False)
    assert env_file() != REAL_ENV  # conftest's no_real_secrets: these tests write to a throwaway .env


def _env_text() -> str:
    try:
        return env_file().read_text()
    except OSError:
        return ""


# ── Where an address is kept, and what wins ──

def test_a_saved_address_is_used_at_once_and_reset_goes_back_to_the_default():
    assert lm_studio_url() == "http://localhost:1234/v1"
    save_address("lmstudio", "http://localhost:1235/v1/")
    assert "LM_STUDIO_BASE_URL=http://localhost:1235/v1\n" in _env_text()  # the same line a person would write
    assert lm_studio_url() == "http://localhost:1235/v1"
    assert local_providers()[0].base_url == "http://localhost:1235/v1"  # no restart
    reset_address("lmstudio")
    assert "LM_STUDIO_BASE_URL" not in _env_text()
    assert lm_studio_url() == "http://localhost:1234/v1"


def test_saving_the_default_address_removes_the_line():
    save_secret("OPENAI_API_KEY", "sk-1")
    save_address("ollama", "http://studio.local:11434/v1")
    save_address("ollama", "http://localhost:11434/v1")
    assert "OLLAMA_BASE_URL" not in _env_text()
    assert "OPENAI_API_KEY=sk-1" in _env_text()  # every other line kept


def test_the_service_environment_wins_over_the_saved_address(monkeypatch):
    save_address("lmstudio", "http://localhost:1235/v1")
    monkeypatch.setenv("LM_STUDIO_BASE_URL", "http://studio.local:1234/v1")
    assert lm_studio_url() == "http://studio.local:1234/v1"
    assert models.address_set_in_environment("lmstudio")
    monkeypatch.delenv("LM_STUDIO_BASE_URL")
    assert lm_studio_url() == "http://localhost:1235/v1"
    assert not models.address_set_in_environment("lmstudio")


def test_a_cloud_preset_moves_too():
    save_secret("OPENAI_API_KEY", "sk-1")
    save_address("openai", "https://gateway.example/openai/v1")
    urls = {p.id: p.base_url for p in default_providers()}
    assert urls["openai"] == "https://gateway.example/openai/v1"


def test_address_problems():
    assert address_problem("http://localhost:1235/v1") is None
    assert address_problem("https://api.example/v1") is None
    assert address_problem("localhost:1235") == "Start the address with http:// or https://."
    assert "computer name" in address_problem("http:///v1")
    assert address_problem("http://my server/v1") == "An address has no spaces, quotes or # in it."


# ── Does it answer? ──

def _at(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


async def test_check_counts_the_chat_models():
    def handler(req):
        assert str(req.url) == "http://localhost:1235/v1/models"
        return httpx.Response(200, json={"data": [{"id": "gemma-4-12b"}, {"id": "qwen3.6-35b"}, {"id": "text-embed-3"}]})
    p = Provider("lmstudio", "LM Studio", "http://localhost:1235/v1", "lm-studio", True)
    assert await check_address(p, transport=_at(handler)) == {"ok": True, "models": 2, "problem": None}


async def test_check_says_why_not():
    p = Provider("x", "X", "http://studio.local:1/v1", "k", False)

    def nobody(req):
        raise httpx.ConnectError("refused")
    assert (await check_address(p, transport=_at(nobody)))["problem"] == "Nothing answers at that address."
    refused = await check_address(p, transport=_at(lambda req: httpx.Response(401)))
    assert refused["ok"] is False and "key" in refused["problem"]
    wrong_path = await check_address(p, transport=_at(lambda req: httpx.Response(404, text="not here")))
    assert "/v1" in wrong_path["problem"]


# ── The routes Settings uses ──

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


async def _settle():
    from odie.app import routes
    await asyncio.gather(*routes._fallback_refreshes)


async def test_every_row_shows_its_address(client):
    c, _ = client
    rows = {r["id"]: r for r in (await c.get("/api/providers")).json()["providers"]}
    assert rows["lmstudio"]["base_url"] == "http://localhost:1234/v1"
    assert rows["lmstudio"]["default_url"] == "http://localhost:1234/v1"
    assert rows["lmstudio"]["address_from_env"] is False
    assert rows["ollama"]["base_url"] == "http://localhost:11434/v1"
    assert rows["anthropic"]["default_url"] == "https://api.anthropic.com/v1"


async def test_moving_lm_studio_to_another_port(client):
    from tests.test_models import FakeRunner
    c, _ = client
    FakeRunner.swapped = None
    r = await c.put("/api/providers/lmstudio/address", json={"base_url": "http://localhost:1235/v1"})
    assert r.status_code == 200
    await _settle()
    assert FakeRunner.swapped is True  # the chat model is built again from the next message
    rows = {r["id"]: r for r in (await c.get("/api/providers")).json()["providers"]}
    assert rows["lmstudio"]["base_url"] == "http://localhost:1235/v1"
    listed = {p["id"]: p for p in (await c.get("/api/models")).json()["providers"]}
    assert listed["lmstudio"]["base_url"] == "http://localhost:1235/v1"  # Brain asks the new port, no restart
    r = await c.delete("/api/providers/lmstudio/address")
    assert r.status_code == 200
    await _settle()
    rows = {r["id"]: r for r in (await c.get("/api/providers")).json()["providers"]}
    assert rows["lmstudio"]["base_url"] == "http://localhost:1234/v1"


async def test_a_bad_address_or_one_the_environment_sets_is_refused(client, monkeypatch):
    c, _ = client
    r = await c.put("/api/providers/lmstudio/address", json={"base_url": "localhost:1235"})
    assert r.status_code == 422 and "http://" in r.json()["detail"]
    assert (await c.put("/api/providers/nope/address", json={"base_url": "http://a.local/v1"})).status_code == 404
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://studio.local:11434/v1")
    rows = {r["id"]: r for r in (await c.get("/api/providers")).json()["providers"]}
    assert rows["ollama"]["address_from_env"] is True
    r = await c.put("/api/providers/ollama/address", json={"base_url": "http://localhost:11435/v1"})
    assert r.status_code == 409 and "OLLAMA_BASE_URL" in r.json()["detail"]
    assert "OLLAMA_BASE_URL" not in _env_text()


async def test_the_test_button_asks_the_typed_address_with_the_saved_key(client, monkeypatch):
    from odie.app import routes
    c, _ = client
    asked = []

    async def fake_check(provider, transport=None):
        asked.append(provider)
        return {"ok": True, "models": 3, "problem": None}
    monkeypatch.setattr(routes, "check_address", fake_check)
    save_secret("ANTHROPIC_API_KEY", "sk-ant-test")
    r = await c.post("/api/providers/anthropic/check", json={"base_url": "https://claude.proxy"})
    assert r.json() == {"ok": True, "models": 3, "problem": None}
    assert (asked[-1].base_url, asked[-1].api_key) == ("https://claude.proxy/v1", "sk-ant-test")
    await c.post("/api/providers/lmstudio/check", json={})
    assert asked[-1].base_url == "http://localhost:1234/v1"  # no address typed: where it is now
    await c.post("/api/providers/new/check", json={"base_url": "http://studio.local:8080/v1", "api_key": "k-1"})
    assert (asked[-1].base_url, asked[-1].api_key) == ("http://studio.local:8080/v1", "k-1")
    r = await c.post("/api/providers/lmstudio/check", json={"base_url": "nope"})
    assert r.json()["ok"] is False and len(asked) == 3  # a malformed address isn't asked


async def test_editing_a_custom_provider_keeps_its_id_and_key(client):
    c, s = client
    r = await c.post("/api/models/providers", json={"name": "Work box", "base_url": "http://studio.local:8080/v1", "api_key": "k-1"})
    pid = r.json()["id"]
    s.set_setting("model.chat", {"provider": pid, "model": "qwen"})
    r = await c.put(f"/api/models/providers/{pid}", json={"name": "Big box", "base_url": "http://studio.local:9090/v1/"})
    assert r.status_code == 200
    await _settle()
    assert s.get_setting("providers.custom") == [{"id": pid, "name": "Big box", "base_url": "http://studio.local:9090/v1"}]
    assert load_secret(custom_key_name(pid)) == "k-1"  # no key sent: the old one stays
    rows = {r["id"]: r for r in (await c.get("/api/providers")).json()["providers"]}
    assert rows[pid]["has_key"] is True and rows[pid]["name"] == "Big box"
    assert "api_key" not in rows[pid]  # a key is never sent back
    await c.put(f"/api/models/providers/{pid}", json={"name": "Big box", "base_url": "http://studio.local:9090/v1", "api_key": "k-2"})
    assert load_secret(custom_key_name(pid)) == "k-2"
    assert resolve_selection(s).provider.id == pid  # the brain that uses it still finds it
    bad = await c.put(f"/api/models/providers/{pid}", json={"name": "Big box", "base_url": "studio.local"})
    assert bad.status_code == 422
    assert (await c.put("/api/models/providers/nope", json={"name": "x", "base_url": "http://a.local/v1"})).status_code == 404
