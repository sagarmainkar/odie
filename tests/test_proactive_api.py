"""The Proactive intelligence switch per personality (Pulse design §2): offered only when it has a mail or calendar
app of its own, off until switched on; everyday Odie has no such switch (its watch keeps its own setting)."""
import httpx
import pytest

from odie import personalities
from odie.plugins import access, mcp
from odie.store.db import Store
from odie.watch import owner


@pytest.fixture
def store(isolated_settings, tmp_path):
    s = Store(tmp_path / "a.db")
    s.init_schema()
    return s


@pytest.fixture
async def api(store, monkeypatch):
    from odie.app.main import create_app
    from tests.test_api import FakeRunner
    monkeypatch.setenv("ODIE_SCHEDULER", "0")
    app = create_app(runner=FakeRunner(), store=store)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c, \
            app.router.lifespan_context(app):
        yield c


async def test_the_switch_is_offered_only_with_its_own_inbox(api, store):
    mcp.write_config({"home": {"url": "https://home.invalid/mcp"}, "work": {"url": "https://work.invalid/mcp"}})
    access.remember_tools(store, {"home": ["gmail_search"], "work": ["gmail_search"]})
    mira = personalities.create(store, "Mira").id
    got = (await api.get(f"/api/proactive?personality={mira}")).json()
    assert got == {"offered": False, "on": False, "apps": []}  # Odie's mail is Odie's to check
    assert (await api.put(f"/api/proactive?personality={mira}", json={"on": True})).status_code == 409
    access.set_allowed(store, "work", access.ODIE, False)  # work is hers alone now
    got = (await api.get(f"/api/proactive?personality={mira}")).json()
    assert got == {"offered": True, "on": False, "apps": ["work"]}  # off by default
    assert (await api.put(f"/api/proactive?personality={mira}", json={"on": True})).json()["on"] is True
    assert owner.is_proactive(store, mira) is True
    assert (await api.get("/api/proactive")).json() == {"offered": False, "on": False, "apps": []}  # Odie: no switch
    assert (await api.put("/api/proactive", json={"on": True})).status_code == 409
