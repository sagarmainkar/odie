"""POST /api/brain/check runs the check on one model and keeps the last report per model; GET lists them."""
import httpx

from odie.brain_check import Part, Report
from odie.store.db import Store


async def _client(tmp_path):
    from odie.app.main import create_app
    from tests.test_api import FakeRunner
    s = Store(tmp_path / "a.db")
    s.init_schema()
    app = create_app(runner=FakeRunner(), store=s)
    return app, httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


async def test_check_route_runs_and_keeps_the_report(isolated_settings, tmp_path, monkeypatch):
    from odie import brain_check
    seen = []

    async def fake(sel, **kw):
        seen.append((sel.provider.id, sel.model))
        return Report(sel.provider.id, sel.model, "good", f"{sel.model}: uses tools correctly · fast · good choice",
                      (Part("tools", "pass", "3 of 3"), Part("result", "pass", "used it"), Part("speed", "pass", "40 tokens a second"),
                       Part("context", "pass", "128K tokens of context")))
    monkeypatch.setattr(brain_check, "check", fake)
    app, c = await _client(tmp_path)
    async with c, app.router.lifespan_context(app):
        r = await c.post("/api/brain/check", json={"provider": "ollama", "model": "glm-5.3-flash:cloud"})
        assert r.status_code == 200 and r.json()["verdict"] == "good" and seen == [("ollama", "glm-5.3-flash:cloud")]
        assert [p["name"] for p in r.json()["parts"]] == ["tools", "result", "speed", "context"]
        kept = (await c.get("/api/brain/checks")).json()
        assert kept["ollama/glm-5.3-flash:cloud"]["sentence"].endswith("good choice")


async def test_check_route_refuses_an_unknown_provider(isolated_settings, tmp_path):
    app, c = await _client(tmp_path)
    async with c, app.router.lifespan_context(app):
        r = await c.post("/api/brain/check", json={"provider": "nowhere", "model": "x"})
        assert r.status_code == 404



async def test_check_route_says_why_when_the_check_breaks(isolated_settings, tmp_path, monkeypatch):
    from odie import brain_check

    async def broken(sel, **kw):
        raise ValueError("odd answer")
    monkeypatch.setattr(brain_check, "check", broken)
    app, c = await _client(tmp_path)
    async with c, app.router.lifespan_context(app):
        r = await c.post("/api/brain/check", json={"provider": "ollama", "model": "m"})
        assert r.status_code == 200 and r.json()["verdict"] == "fail" and "ValueError" in r.json()["sentence"]
