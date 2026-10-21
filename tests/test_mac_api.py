"""Settings → Mac apps: the rows, the Allow that raises macOS's dialog, the calendar picker; and the setup step."""
import httpx
import pytest

from odie.mac import permissions, scripts
from odie.store.db import Store


@pytest.fixture
def store(isolated_settings, tmp_path):
    s = Store(tmp_path / "a.db")
    s.init_schema()
    return s


def client(store):
    from odie.app.main import create_app
    from tests.test_api import FakeRunner
    app = create_app(runner=FakeRunner(), store=store)
    return app, httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


async def test_not_a_mac_means_no_rows(store):
    app, c = client(store)
    async with c, app.router.lifespan_context(app):
        got = (await c.get("/api/mac/apps")).json()
        assert got == {"mac": False, "apps": [], "default_calendar": ""}
        assert (await c.post("/api/mac/apps/mail/allow")).status_code == 400
        assert (await c.get("/api/mac/calendars")).json() == {"calendars": []}


async def test_rows_allow_and_the_calendar_choice(store, monkeypatch):
    from odie.mac import calendar
    from odie.watch import sources
    monkeypatch.setattr(scripts, "available", lambda: True)
    permissions.forget()
    monkeypatch.setattr(permissions, "_determine", lambda bundle: 0 if bundle == "com.apple.mail" else -1744)
    asked = []

    async def fake_request(app_id, run=None):
        asked.append(app_id)
        permissions.remember(app_id, "granted")
        return "granted"
    monkeypatch.setattr(permissions, "request", fake_request)

    async def fake_calendars(run=None):
        return [{"name": "Home", "writable": True}, {"name": "Work", "writable": True}]
    monkeypatch.setattr(calendar, "calendars", fake_calendars)
    sources_forgotten = []
    monkeypatch.setattr(sources, "forget", lambda s: sources_forgotten.append(True))
    app, c = client(store)
    async with c, app.router.lifespan_context(app):
        got = (await c.get("/api/mac/apps")).json()
        assert got["mac"] is True and {r["id"]: r["status"] for r in got["apps"]} == {"mail": "granted", "calendar": "unknown", "reminders": "unknown", "contacts": "unknown"}
        assert (await c.get("/api/mac/calendars")).json() == {"calendars": []}  # not granted yet: nothing asked of Calendar
        after = (await c.post("/api/mac/apps/calendar/allow")).json()
        assert asked == ["calendar"] and sources_forgotten == [True]
        permissions.forget()
        monkeypatch.setattr(permissions, "_determine", lambda bundle: -600)  # Calendar closed now: the remembered grant holds
        assert {r["id"]: r["status"] for r in (await c.get("/api/mac/apps")).json()["apps"]}["calendar"] == "granted"
        assert (await c.get("/api/mac/calendars")).json()["calendars"][1]["name"] == "Work"
        assert (await c.put("/api/mac/calendar", json={"name": "Work"})).json()["default_calendar"] == "Work"
        assert (await c.get("/api/mac/apps")).json()["default_calendar"] == "Work"
        assert (await c.post("/api/mac/apps/nothing/allow")).status_code == 404
    assert calendar.chosen(store) == "Work"
    permissions.forget()


async def test_the_apps_step_shows_the_mac_rows_on_a_mac(store, monkeypatch):
    from odie.setup import panels
    from tests.test_setup_panels import no_models, through_names
    await through_names(store)
    assert "mac_apps" not in await panels.panel(store, "apps", transport=no_models())
    monkeypatch.setattr(scripts, "available", lambda: True)
    permissions.forget()
    monkeypatch.setattr(permissions, "_determine", lambda bundle: -1744)
    p = await panels.panel(store, "apps", transport=no_models())
    assert p["mac_apps"]["mac"] is True and [r["id"] for r in p["mac_apps"]["apps"]] == ["mail", "calendar", "reminders", "contacts"]
    permissions.forget()


async def test_the_add_tool_uses_the_chosen_calendar(store, monkeypatch):
    from odie.mac import calendar
    from odie.skills.registry import BUILTIN, discover
    store.set_setting(calendar.SETTING, "Work")
    monkeypatch.setattr(calendar, "chosen", lambda s=None: "Work")
    permissions.forget()
    monkeypatch.setattr(permissions, "_determine", lambda bundle: 0)
    seen = {}

    async def fake_add(title, start, end, cal="", where="", notes="", run=None):
        seen["calendar"] = cal
        return {"id": "u1", "calendar": cal}
    monkeypatch.setattr(calendar, "add", fake_add)
    tools = {t.name: t for e in discover(store, BUILTIN, store.path.parent / "none", system="Darwin") if e.name == "mac-apps" for t in e.tool_objs}
    out = await tools["mac_calendar_add"].func(title="Pay Axis", start="2026-10-29T09:00", end="2026-10-29T09:30")
    assert out["calendar"] == "Work" and seen["calendar"] == "Work"
    permissions.forget()
