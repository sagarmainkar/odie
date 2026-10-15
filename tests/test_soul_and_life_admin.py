
import httpx
import pytest

from odie.app.main import create_app
from odie.store.db import Store


class FakeRunner:
    async def chat(self, text, thinking=False, session_id=None):
        if False:
            yield None

    async def history(self, date, limit=None, before=None):
        return {"items": [], "total": 0, "start": 0}

    def invalidate_prompt(self):
        FakeRunner.invalidated = True

    async def close(self):
        pass


@pytest.fixture
async def client(isolated_settings, tmp_path, monkeypatch):
    import odie.app.routes as routes
    monkeypatch.setattr(routes, "SOUL_PATH", tmp_path / "SOUL.md")
    s = Store(tmp_path / "assistant.db")
    s.init_schema()
    app = create_app(runner=FakeRunner(), store=s)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        async with app.router.lifespan_context(app):
            yield c, tmp_path


async def test_soul_get_default_and_put(client):
    c, tmp = client
    r = await c.get("/api/soul")
    assert r.status_code == 200 and r.json()["text"].startswith("You are Odie") and r.json()["custom"] is False
    r = await c.put("/api/soul", json={"text": "You are Odie. Dry wit."})
    assert r.json() == {"ok": True, "custom": True} and (tmp / "SOUL.md").read_text() == "You are Odie. Dry wit."
    assert FakeRunner.invalidated is True
    assert (await c.get("/api/soul")).json()["custom"] is True
    r = await c.put("/api/soul", json={"text": "   "})
    assert r.json()["custom"] is False and not (tmp / "SOUL.md").exists()


async def test_soul_default_has_the_chosen_names(client):
    """Settings shows the default personality filled in: the assistant's chosen name and the user's."""
    from odie import persona, profile
    c, _ = client
    store = c._transport.app.state.store
    profile.set_user_name(store, "Asha")
    persona.set_name(store, "Iris")
    text = (await c.get("/api/soul")).json()["text"]
    assert text.startswith("You are Iris, Asha's personal assistant.") and "Learn Asha's preferences" in text
