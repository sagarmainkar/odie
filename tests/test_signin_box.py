"""The sign-in box (spec "Sign in for me", Parts 3 and 6): the sheet's login goes to the engine, is saved only after it
worked, waits in memory through a code step, and nothing of it is kept outside the vault. Off and Sign out forget."""
import json
import subprocess
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import httpx
import pytest

from odie.signin import box, sites, state, vault
from odie.store.db import Store
from tests.test_api import FakeRunner

NOW = datetime(2026, 10, 8, 9, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
SECRET = "pw-never-kept"


class FakeEngine:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = []
        self.signed_out = []

    async def sign_in(self, tab, site, username, password):
        self.calls.append(("sign_in", tab, site, username, password))
        return {"status": self.answers.pop(0)}

    async def enter_code(self, tab, site, code):
        self.calls.append(("code", tab, site, code))
        return {"status": self.answers.pop(0)}

    async def sign_out(self, domains=None, origins=()):
        self.signed_out.append(domains)

    async def close(self):
        pass


@pytest.fixture
def store(isolated_settings, tmp_path, keychain):
    s = Store(tmp_path / "a.db")
    s.init_schema()
    state.turn_on(s, accepted=True, version=state.VERSION, now=NOW)
    return s


async def test_a_login_is_saved_only_after_it_worked(store):
    b = box.SignInBox(store)
    got = await b.submit("chat-1", "amazon.in", "asha", SECRET, True, browser=FakeEngine("failed"))
    assert got == {"status": "failed", "site": "amazon.in"} and vault.listing(store) == []
    got = await b.submit("chat-1", "amazon.in", "asha", SECRET, True, browser=FakeEngine("signed_in"))
    assert got["status"] == "signed_in" and vault.get(store, "amazon.in") == ("asha", SECRET)
    assert [s["domain"] for s in sites.listing(store)] == ["amazon.in"]


async def test_remember_off_saves_nothing(store):
    b = box.SignInBox(store)
    await b.submit("chat-1", "amazon.in", "asha", SECRET, False, browser=FakeEngine("signed_in"))
    assert vault.listing(store) == []


async def test_a_code_step(store):
    b, engine = box.SignInBox(store), FakeEngine("code", "signed_in")
    assert (await b.submit("chat-1", "amazon.in", "asha", SECRET, True, browser=engine))["status"] == "code"
    assert vault.listing(store) == []  # not yet: it hasn't worked yet
    assert (await b.code("chat-1", " 123456 ", browser=engine))["status"] == "signed_in"
    assert engine.calls[-1] == ("code", "chat-1", "amazon.in", "123456") and vault.get(store, "amazon.in") == ("asha", SECRET)
    assert (await b.code("chat-1", "123456", browser=engine))["status"] == "expired"  # nothing pending any more


async def test_a_code_waits_ten_minutes_at_most(store, monkeypatch):
    b = box.SignInBox(store)
    await b.submit("chat-1", "amazon.in", "asha", SECRET, True, browser=FakeEngine("code"))
    monkeypatch.setattr(box, "PENDING_FOR", -1)
    b._pending["chat-1"].until = 0
    assert (await b.code("chat-1", "123456", browser=FakeEngine()))["status"] == "expired"


async def test_saving_can_fail_after_signing_in(store, monkeypatch):
    def refuse(*a, **k):
        raise vault.VaultError("Odie couldn't save it in the Mac's Keychain.")
    monkeypatch.setattr(vault, "save", refuse)
    got = await box.SignInBox(store).submit("chat-1", "amazon.in", "asha", SECRET, True, browser=FakeEngine("signed_in"))
    assert got["status"] == "signed_in" and "Keychain" in got["warning"]


async def test_nothing_kept_but_the_vault(store, isolated_settings):
    b, engine = box.SignInBox(store), FakeEngine("code", "signed_in")
    await b.submit("chat-1", "amazon.in", "asha", SECRET, True, browser=engine)
    await b.code("chat-1", "123456", browser=engine)
    rows = json.dumps([dict(r) for r in store.query("select * from audit_log")])
    settings = json.dumps([dict(r) for r in store.query("select * from settings")])
    assert SECRET not in rows and SECRET not in settings and "asha" not in rows
    assert not b._pending  # the login left memory once it worked


# --- the routes ---

@pytest.fixture
async def api(store, monkeypatch):
    import odie.browser
    engine = FakeEngine()
    monkeypatch.setattr(odie.browser, "_shared", engine)
    from odie.app.main import create_app
    app = create_app(runner=FakeRunner(), store=store)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        async with app.router.lifespan_context(app):
            yield SimpleNamespace(c=c, engine=engine)


async def test_the_sheet_route(api, store):
    api.engine.answers = ["code", "signed_in"]
    r = await api.c.post("/api/browser/sign-in/chat-1", json={"site": "amazon.in", "username": "asha", "password": SECRET, "remember": True})
    assert r.json() == {"status": "code", "site": "amazon.in"}
    r = await api.c.post("/api/browser/sign-in/chat-1/code", json={"code": "123456"})
    assert r.json()["status"] == "signed_in" and vault.get(store, "amazon.in") == ("asha", SECRET)
    assert (await api.c.post("/api/browser/sign-in/chat-1", json={"site": "amazon.in", "username": "", "password": ""})).status_code == 422


async def test_saved_logins_in_settings(api, store, keychain):
    r = await api.c.post("/api/browser/logins", json={"site": "https://www.airbnb.co.in/login", "username": "asha", "password": SECRET})
    assert [x["site"] for x in r.json()["logins"]] == ["airbnb.co.in"] and SECRET not in r.text
    assert [x["username"] for x in (await api.c.get("/api/browser/logins")).json()["logins"]] == ["asha"]
    assert (await api.c.delete("/api/browser/logins/airbnb.co.in")).json()["logins"] == []
    assert (await api.c.delete("/api/browser/logins/airbnb.co.in")).status_code == 404
    vault.save(store, "amazon.in", "asha", "a", NOW)
    vault.save(store, "airbnb.co.in", "asha", "b", NOW)
    assert (await api.c.post("/api/browser/logins/forget")).json()["logins"] == []


async def test_off_forgets_every_saved_login(api, store, keychain):
    vault.save(store, "amazon.in", "asha", "a", NOW)
    vault.save(store, "airbnb.co.in", "asha", "b", NOW)
    await api.c.post("/api/browser/signin/off")
    assert vault.listing(store) == []
    for site in ("amazon.in", "airbnb.co.in"):  # gone from the Keychain itself, not just the list
        assert subprocess.run(["security", "find-internet-password", "-s", site, str(keychain)], capture_output=True).returncode != 0


async def test_sign_out_forgets_that_sites_login(api, store):
    sites.record(store, "amazon.in", NOW)
    sites.record(store, "airbnb.co.in", NOW)
    vault.save(store, "amazon.in", "asha", "a", NOW)
    vault.save(store, "airbnb.co.in", "asha", "b", NOW)
    await api.c.post("/api/browser/sites/amazon.in/signout")
    assert [x["site"] for x in vault.listing(store)] == ["airbnb.co.in"]
    await api.c.post("/api/browser/signout")  # everything
    assert vault.listing(store) == []


async def test_off_means_no_box(api, store):
    state.turn_off(store)
    assert (await api.c.get("/api/browser/logins")).status_code == 403
    r = await api.c.post("/api/browser/sign-in/chat-1", json={"site": "amazon.in", "username": "asha", "password": SECRET})
    assert r.status_code == 403



def test_a_pending_login_never_prints_its_password():
    assert SECRET not in repr(box.Pending("amazon.in", "asha", SECRET, True))
