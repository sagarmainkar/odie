import httpx

from odie import persona
from odie.app.main import create_app
from odie.store.db import Store
from tests.test_approvals import FakeRunner


async def test_manifest_uses_the_assistants_name(isolated_settings, tmp_path):
    s = Store(tmp_path / "a.db")
    s.init_schema()
    persona.set_name(s, "Iris")
    app = create_app(runner=FakeRunner(), store=s)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c, app.router.lifespan_context(app):
        r = await c.get("/manifest.webmanifest")
    m = r.json()
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/manifest+json")
    assert m["name"] == m["short_name"] == "Iris" and m["start_url"] == "/"
