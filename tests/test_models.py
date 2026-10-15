import json

import httpx
import pytest

from odie.app.main import create_app
from odie.models import Provider, default_providers, list_models, resolve_selection
from odie.store.db import Store


def _store(tmp_path):
    s = Store(tmp_path / "a.db")
    s.init_schema()
    return s


def test_default_providers_and_locality():
    ps = {p.id: p for p in default_providers()}
    assert ps["lmstudio"].base_url.endswith(":1234/v1") and ps["lmstudio"].local is True
    assert ps["ollama"].base_url.endswith(":11434/v1") and ps["ollama"].local is True


async def test_list_models_marks_cloud_and_handles_failures():
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.port == 1234:
            return httpx.Response(200, json={"data": [{"id": "gemma-4-26b-a4b-it-qat"}, {"id": "text-embedding-nomic-embed-text-v1.5"}]})
        if req.url.port == 11434:
            return httpx.Response(200, json={"data": [{"id": "glm-5.3-flash:cloud"}, {"id": "gemma4:31b-cloud"}]})
        return httpx.Response(500)
    custom = Provider(id="mine", name="My endpoint", base_url="https://api.example/v1", api_key="k", local=False)
    out = await list_models(default_providers() + [custom], transport=httpx.MockTransport(handler))
    by = {p["id"]: p for p in out}
    assert [m["id"] for m in by["lmstudio"]["models"]] == ["gemma-4-26b-a4b-it-qat"]  # embeddings filtered
    assert by["ollama"]["models"][0] == {"id": "glm-5.3-flash:cloud", "local": False}
    assert by["mine"]["models"] == [] and by["mine"]["error"]


def test_selection_persists_and_resolves(tmp_path):
    s = _store(tmp_path)
    sel = resolve_selection(s, "chat")
    assert sel.provider.id == "lmstudio" and sel.model == "gemma-4-26b-a4b-it-qat"  # config default
    s.set_setting("model.chat", {"provider": "ollama", "model": "glm-5.3-flash:cloud"})
    sel = resolve_selection(s, "chat")
    assert sel.provider.id == "ollama" and sel.model == "glm-5.3-flash:cloud" and sel.leaves_mini is True
    assert resolve_selection(s, "jobs").model == "glm-5.3-flash:cloud"  # one model: any slot is the chat one
    s.set_setting("model.jobs", {"provider": "lmstudio", "model": "google/gemma-4-12b-qat"})
    assert resolve_selection(s, "jobs").model == "glm-5.3-flash:cloud"  # a saved jobs model is ignored
    s.set_setting("providers.custom", [{"id": "mine", "name": "Mine", "base_url": "https://api.example/v1", "api_key": "k"}])
    s.set_setting("model.chat", {"provider": "mine", "model": "foo"})
    assert resolve_selection(s, "chat").provider.base_url == "https://api.example/v1"


class FakeRunner:
    swapped = None

    async def chat(self, text, thinking=False, session_id=None):
        if False:
            yield None

    async def history(self, date, limit=None, before=None):
        return {"items": [], "total": 0, "start": 0}

    def apply_model_selection(self):
        FakeRunner.swapped = True

    async def close(self):
        pass


@pytest.fixture
async def client(isolated_settings, tmp_path):
    s = _store(tmp_path)
    app = create_app(runner=FakeRunner(), store=s)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        async with app.router.lifespan_context(app):
            yield c, s


async def test_model_routes(client, monkeypatch):
    c, s = client
    import odie.app.routes as routes

    async def fake_list(providers, transport=None):
        return [{"id": p.id, "name": p.name, "local": p.local, "models": [{"id": "m1", "local": p.local}], "error": None} for p in providers]
    monkeypatch.setattr(routes, "list_models", fake_list)
    r = (await c.get("/api/models")).json()
    assert {p["id"] for p in r["providers"]} >= {"lmstudio", "ollama"} and r["selection"]["chat"]["provider"] == "lmstudio"
    r = await c.put("/api/models/selection", json={"slot": "chat", "provider": "ollama", "model": "m1"})
    assert r.status_code == 200 and FakeRunner.swapped is True
    assert json.loads(s.one("select value_json from settings where key='model.chat'")["value_json"])["model"] == "m1"
    r = await c.post("/api/models/providers", json={"name": "Mine", "base_url": "https://api.example/v1", "api_key": "k"})
    assert r.status_code == 200 and r.json()["id"] == "mine"
    assert (await c.put("/api/models/selection", json={"slot": "chat", "provider": "nope", "model": "x"})).status_code == 404
