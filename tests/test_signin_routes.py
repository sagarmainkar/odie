"""The switch, the signed-in sites and the UPI ID over the API; the sign-in tool and the rules, present only while the
switch is on (spec Parts 0, 1, 2 and 4)."""
import json
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import httpx
import pytest

from odie.agent import turn
from odie.signin import guard, sites, state
from odie.store.db import Store
from tests.test_api import FakeRunner

NOW = datetime(2026, 10, 8, 9, 0, tzinfo=ZoneInfo("Asia/Kolkata"))


class SignInRunner(FakeRunner):
    reloads = 0

    async def reload_signin(self):
        self.reloads += 1


class FakeBrowser:
    def __init__(self):
        self.signed_out = []

    async def sign_out(self, domains=None, origins=()):
        self.signed_out.append(None if domains is None else list(domains))
        self.origins = list(origins)

    async def close(self):
        pass


@pytest.fixture
def store(isolated_settings, tmp_path):
    s = Store(tmp_path / "a.db")
    s.init_schema()
    return s


@pytest.fixture
def browser(monkeypatch):
    import odie.browser
    b = FakeBrowser()
    monkeypatch.setattr(odie.browser, "_shared", b)
    return b


@pytest.fixture
async def api(store, browser):
    from odie.app.main import create_app
    runner = SignInRunner()
    app = create_app(runner=runner, store=store)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        async with app.router.lifespan_context(app):
            yield SimpleNamespace(c=c, runner=runner)


@pytest.fixture
def has_browser(monkeypatch):
    from odie.browser import find
    monkeypatch.setattr(find, "browser_binary", lambda: "/Applications/Chrome")


async def test_off_by_default_no_tool_no_route(api, store, has_browser):
    from odie import capabilities
    from odie.agent.agent import signin_tools
    got = (await api.c.get("/api/browser/signin")).json()
    assert got["on"] is False and got["version"] == state.VERSION and got["disclaimer"] == state.DISCLAIMER
    r = await api.c.get("/api/browser/sites")
    assert r.status_code == 403 and r.json()["detail"] == "Signed-in browsing is off"
    assert (await api.c.post("/api/browser/sites/amazon.in/signout")).status_code == 403
    assert signin_tools(store) == [] and "signin" not in capabilities.detect(store=store)
    state.turn_on(store, accepted=True, version=state.VERSION, now=NOW)
    assert [t.name for t in signin_tools(store)] == ["browser_sign_in"] and "signin" in capabilities.detect(store=store)


async def test_turning_on_needs_the_box_and_the_version(api, store):
    r = await api.c.post("/api/browser/signin", json={"accepted": False, "version": state.VERSION})
    assert r.status_code == 422 and "Tick" in r.json()["detail"]
    r = await api.c.post("/api/browser/signin", json={"accepted": True, "version": state.VERSION - 1})
    assert r.status_code == 422 and "changed" in r.json()["detail"]
    assert not state.is_on(store) and api.runner.reloads == 0
    r = await api.c.post("/api/browser/signin", json={"accepted": True, "version": state.VERSION})
    assert r.status_code == 200 and r.json()["on"] is True and r.json()["accepted_at"]
    assert state.is_on(store) and api.runner.reloads == 1
    assert store.one("select 1 from audit_log where event='signin_turned_on'")


async def test_turning_off_signs_out_of_everything(api, store, browser):
    state.turn_on(store, accepted=True, version=state.VERSION, now=NOW)
    sites.record(store, "amazon.in", NOW)
    r = await api.c.post("/api/browser/signin/off")
    assert r.status_code == 200 and r.json()["on"] is False
    assert browser.signed_out == [None] and sites.listing(store) == [] and api.runner.reloads == 1


async def test_sites_and_sign_out(api, store, browser):
    state.turn_on(store, accepted=True, version=state.VERSION, now=NOW)
    sites.record(store, "amazon.in", NOW, origins=["https://www.amazon.in"])
    sites.record(store, "airbnb.co.in", NOW)
    assert {s["domain"] for s in (await api.c.get("/api/browser/sites")).json()["sites"]} == {"amazon.in", "airbnb.co.in"}
    r = await api.c.post("/api/browser/sites/amazon.in/signout")
    assert r.status_code == 200 and [s["domain"] for s in r.json()["sites"]] == ["airbnb.co.in"]
    assert browser.signed_out == [["amazon.in"]] and browser.origins == ["https://www.amazon.in"]
    assert (await api.c.post("/api/browser/sites/example.com/signout")).status_code == 404
    r = await api.c.post("/api/browser/signout")
    assert r.status_code == 200 and r.json()["sites"] == [] and browser.signed_out[-1] is None
    assert state.is_on(store)  # signed out of everything, still on


async def test_upi_id_is_checked_and_kept_out_of_memory(api, store, isolated_settings, tmp_path):
    from odie.memory.store import MemoryFile
    for bad in ("not a upi id", "ashaa@", "@okaxis", "ashaa@okaxis; drop"):
        r = await api.c.put("/api/browser/upi", json={"upi_id": bad})
        assert r.status_code == 422, bad
    r = await api.c.put("/api/browser/upi", json={"upi_id": " ashaa@okaxis "})
    assert r.status_code == 200 and r.json()["upi_id"] == "ashaa@okaxis"
    assert (await api.c.get("/api/browser/signin")).json()["upi_id"] == "ashaa@okaxis"
    memory = MemoryFile(tmp_path / "m.md", tmp_path / "m.lock", "t")
    with pytest.raises(ValueError, match="UPI"):
        memory.update("Payments", "UPI ID is ashaa@okaxis")
    assert (await api.c.put("/api/browser/upi", json={"upi_id": ""})).json()["upi_id"] is None


def test_the_rules_follow_the_switch():
    from odie.agent.prompt import Who, build_static_prompt
    now = datetime(2026, 10, 8, 9, 0, tzinfo=ZoneInfo("Asia/Kolkata"))

    def prompt(*caps):
        return build_static_prompt(now, None, "", gated=True, who=Who(user="Asha", machine="Mac", currency="₹", caps=frozenset(caps)))
    off, on, none = prompt("browser"), prompt("browser", "signin"), prompt()
    assert "Settings → Browser" in off and "browser_sign_in" not in off
    assert "call browser_sign_in" in on and "never type a password" in on and "Settings → Browser" not in on
    assert "browser_sign_in" not in none and "Settings → Browser" not in none


async def test_browser_sign_in_returns_a_turn_card(store):
    from odie import media
    from odie.agent.tools.browser import make_signin_tools
    state.turn_on(store, accepted=True, version=state.VERSION, now=NOW)
    tool = make_signin_tools(store)[0]
    ctx = SimpleNamespace(session=SimpleNamespace(id="chat-2026-10-08"))
    guard.LAST_URL.pop("chat-2026-10-08", None)
    token = turn.USER_TEXT.set("track my last amazon order")
    try:
        assert "error" in await tool.run_async(args={"why": "x"}, tool_context=ctx)  # no page open in this chat yet
        guard.LAST_URL["chat-2026-10-08"] = "https://www.amazon.in/ap/signin?openid.return_to=x"
        out = await tool.run_async(args={"why": "Amazon asks you to sign in"}, tool_context=ctx)
    finally:
        turn.USER_TEXT.reset(token)
    assert out["media"]["kind"] == "turn" and "your turn" in out["result"].lower()
    path, _ = media.get(out["media"]["id"])
    card = json.loads(path.read_bytes())
    with pytest.raises(ValueError):
        media.save(b"{}", "turn", "json", "application/json", "x")  # .json is the sidecar's own name
    assert card == {"site": "amazon.in", "tab": "chat-2026-10-08", "why": "Amazon asks you to sign in",
                    "url": "https://www.amazon.in/ap/signin?openid.return_to=x"}
    assert "error" in await tool.run_async(args={"why": "x"}, tool_context=ctx)  # background work never signs in


async def test_only_chat_has_the_sign_in_tool(store, has_browser, monkeypatch):
    from odie.app import runner as runner_mod
    state.turn_on(store, accepted=True, version=state.VERSION, now=NOW)
    r = runner_mod.OdieRunner(store)
    names = lambda tools: {getattr(t, "name", "") for t in tools}  # noqa: E731
    assert "browser_sign_in" in names(r.agent.tools)
    seen = {}

    class FakeADK:
        def __init__(self, app, session_service, **kw):
            seen["tools"] = names(app.root_agent.tools)

        async def run_async(self, **kw):
            return
            yield
    monkeypatch.setattr(runner_mod, "Runner", FakeADK)
    await r.background_turn("Is the order out for delivery?")
    assert seen["tools"] and "browser_sign_in" not in seen["tools"]  # trackers and the watch never sign in
    state.turn_off(store)
    await r.reload_signin()
    assert "browser_sign_in" not in names(r.agent.tools)
    await r.close()
