"""Paired devices: with pairing on, every API answers only a browser holding a device key (except the exempt list);
codes are one-time and short-lived, the passcode locks after five wrong tries, the first device comes through the setup
link, and nothing secret is stored in the clear."""
import asyncio
import re
import sqlite3

import httpx
import pytest
from fastapi.routing import APIRoute

from odie import devices
from odie.store.db import Store

PRIVATE = {"detail": "This Odie is private.", "pair": True}


@pytest.fixture
def store(isolated_settings, tmp_path, monkeypatch):
    monkeypatch.setenv("ODIE_PAIRING", "on")
    s = Store(tmp_path / "assistant.db")
    s.init_schema()
    return s


def _app(store):
    from odie.app.main import create_app
    from tests.test_api import FakeRunner
    return create_app(runner=FakeRunner(), store=store)


def _client(app, https=False):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://t" if https else "http://t")


async def _pair(store, c):
    """Pairs this client through the setup link."""
    link = devices.setup_link(store, "http://t")
    r = await c.get(link.removeprefix("http://t"), follow_redirects=False)
    assert r.status_code == 303 and devices.COOKIE in c.cookies


def _attrs(set_cookie: str) -> set[str]:
    return {a.strip().split("=")[0].lower() for a in set_cookie.split(";")[1:]}


async def test_every_route_is_closed_without_a_device(store):
    from odie.app.routes import router
    app = _app(store)
    async with _client(app) as c, app.router.lifespan_context(app):
        for r in router.routes:
            if not isinstance(r, APIRoute):
                continue
            path = re.sub(r"\{[^}]+\}", "1", r.path)
            for method in r.methods - {"HEAD", "OPTIONS"}:
                got = await asyncio.wait_for(c.request(method, path), 5)
                if path == "/api/health" or path.startswith("/api/pair/"):
                    assert got.status_code != 401 or got.json().get("pair") is not True, path
                else:
                    assert got.status_code == 401 and got.json() == PRIVATE, (method, path)
        assert (await c.get("/api/not-a-route")).json() == PRIVATE
        assert (await c.get("/api/health")).json() == {"status": "ok"}  # no data for a stranger
        assert (await c.get("/manifest.webmanifest")).status_code == 200  # open on purpose: browsers fetch it without cookies


async def test_a_paired_browser_gets_in(store):
    app = _app(store)
    async with app.router.lifespan_context(app), _client(app) as c:
        await _pair(store, c)
        assert (await c.get("/api/setup")).status_code == 200
        assert "model" in (await c.get("/api/health")).json()
        st = (await c.get("/api/pair/status")).json()
        assert st == {"on": True, "paired": True, "devices": 1, "passcode": False}


async def test_codes_are_one_time_and_expire(store, monkeypatch):
    app = _app(store)
    async with app.router.lifespan_context(app), _client(app) as owner, _client(app) as phone, _client(app) as other:
        await _pair(store, owner)
        made = (await owner.post("/api/devices/code")).json()
        assert re.fullmatch(r"[A-Z0-9]{4}-[A-Z0-9]{4}", made["code"]) and made["svg"].startswith("<svg")
        assert made["url"] == "http://t/#pair=" + made["code"] and made["expires_in"] == 600  # a fragment: never in a server log
        assert (await phone.post("/api/pair/code", json={"code": made["code"].lower(), "name": "Phone"})).status_code == 200
        assert (await phone.get("/api/setup")).status_code == 200
        assert (await other.post("/api/pair/code", json={"code": made["code"]})).status_code == 401  # one time
        late = (await owner.post("/api/devices/code")).json()["code"]
        real = devices.now()
        monkeypatch.setattr(devices, "now", lambda: real + 11 * 60)
        assert (await other.post("/api/pair/code", json={"code": late})).status_code == 401  # expired
        assert (await other.get("/api/setup")).status_code == 401


async def test_wrong_passcodes_lock(store, monkeypatch, tmp_path):
    words = devices.new_passcode(store)
    assert len(words.split()) == 4
    for _ in range(5):
        assert devices.try_passcode(store, "wrong words here please") is False
    assert devices.try_passcode(store, words) is None  # locked, even with the right one
    again = Store(tmp_path / "assistant.db")  # a restart keeps the lock
    assert devices.try_passcode(again, words) is None
    real = devices.now()
    monkeypatch.setattr(devices, "now", lambda: real + 11 * 60)
    assert devices.try_passcode(store, words.upper()) is True
    app = _app(store)
    async with _client(app) as c, app.router.lifespan_context(app):
        r = await c.post("/api/pair/passcode", json={"passcode": words, "name": "Laptop"})
        assert r.status_code == 200 and devices.COOKIE in c.cookies
        for _ in range(5):
            await c.post("/api/pair/passcode", json={"passcode": "no no no no"})
        assert (await c.post("/api/pair/passcode", json={"passcode": words})).status_code == 429


async def test_the_setup_link_pairs_the_first_device_once(store):
    link = devices.setup_link(store, "http://t")
    assert link.startswith("http://t/api/pair/setup?token=")
    token = link.split("token=")[1]
    assert devices.redeem_setup(store, token) is True and devices.redeem_setup(store, token) is False
    devices.add_device(store, "Mac")
    assert devices.setup_link(store, "http://t") is None  # only while nothing is paired
    devices.remove_device(store, devices.list_devices(store)[0]["id"])
    stale = devices.setup_link(store, "http://t").split("token=")[1]
    devices.add_device(store, "Phone")  # paired some other way first
    assert devices.redeem_setup(store, stale) is False


async def test_a_new_install_writes_the_setup_link_for_the_installer(store, isolated_settings):
    app = _app(store)
    path = isolated_settings.config_dir / "setup-link"
    async with app.router.lifespan_context(app):
        assert path.stat().st_mode & 0o777 == 0o600
        link = path.read_text().strip()
        async with _client(app) as c:
            r = await c.get(link.removeprefix(f"http://localhost:{isolated_settings.port}"), follow_redirects=False)
            assert r.status_code == 303 and r.headers["location"] == "/"
            assert not path.exists()  # used: nobody else can pair with it
            r = await c.get(link.removeprefix(f"http://localhost:{isolated_settings.port}"), follow_redirects=False)
            assert r.headers["location"] == "/?pair=used"


async def test_turning_pairing_on_keeps_you_in(store, monkeypatch):
    monkeypatch.delenv("ODIE_PAIRING")
    store.audit("user", "message", result_summary="hi")  # an install that already chats: pairing starts off
    app = _app(store)
    async with _client(app) as c, app.router.lifespan_context(app):
        assert (await c.get("/api/setup")).status_code == 200
        assert (await c.get("/api/pair/status")).json() == {"on": False, "paired": False, "devices": 0, "passcode": False}
        r = await c.put("/api/devices/pairing", json={"on": True})
        assert r.status_code == 200 and devices.COOKIE in c.cookies
        assert (await c.get("/api/setup")).status_code == 200  # still in
        async with _client(app) as stranger:
            assert (await stranger.get("/api/setup")).status_code == 401


def test_existing_install_starts_with_pairing_off(store, monkeypatch, tmp_path):
    monkeypatch.delenv("ODIE_PAIRING")
    assert devices.pairing_on(store) is True  # a new install
    store.audit("user", "message", result_summary="hi")
    assert devices.pairing_on(store) is True  # decided once: chatting later doesn't turn it off
    old = Store(tmp_path / "old.db")
    old.init_schema()
    old.audit("user", "message", result_summary="hi")
    assert devices.pairing_on(old) is False
    devices.set_pairing(old, True)
    assert devices.pairing_on(old) is True
    monkeypatch.setenv("ODIE_PAIRING", "off")
    assert devices.pairing_on(old) is False  # the override wins


async def test_removing_the_last_device_asks_first(store):
    app = _app(store)
    async with app.router.lifespan_context(app), _client(app) as c:
        await _pair(store, c)
        [me] = (await c.get("/api/devices")).json()
        assert me["this"] is True and me["name"]
        assert (await c.delete(f"/api/devices/{me['id']}")).status_code == 409
        assert (await c.delete("/api/devices/999?confirm=1")).status_code == 404
        assert (await c.delete(f"/api/devices/{me['id']}?confirm=1")).status_code == 200
        assert (await c.get("/api/setup")).status_code == 401


async def test_secrets_are_stored_hashed(store, tmp_path):
    link = devices.setup_link(store, "http://t")
    key = devices.add_device(store, "Mac")
    code = devices.new_code(store)
    words = devices.new_passcode(store)
    db = tmp_path / "assistant.db"
    raw = b"".join(p.read_bytes() for p in (db, db.with_name("assistant.db-wal")) if p.exists())
    for secret in (key, code, code.replace("-", ""), words, words.replace(" ", ""), link.split("token=")[1]):
        assert secret.encode() not in raw and secret.lower().encode() not in raw, secret[:6]
    rows = sqlite3.connect(db).execute("select key_hash from devices").fetchall()
    assert rows and all(len(r[0]) == 64 for r in rows)


async def test_the_cookie_is_httponly_and_secure_over_https(store):
    app = _app(store)
    async with app.router.lifespan_context(app):
        for https, forwarded in ((False, False), (True, False), (False, True)):
            link = devices.setup_link(store, "http://t")
            async with _client(app, https=https) as c:
                headers = {"x-forwarded-proto": "https"} if forwarded else {}
                r = await c.get(link.removeprefix("http://t"), headers=headers, follow_redirects=False)
                cookie = r.headers["set-cookie"]
                assert cookie.startswith(devices.COOKIE + "=") and "max-age=31536000" in cookie.lower()
                assert {"httponly", "samesite", "path"} <= _attrs(cookie) and "samesite=lax" in cookie.lower()
                assert ("secure" in _attrs(cookie)) is (https or forwarded)
            devices.remove_device(store, devices.list_devices(store)[0]["id"])


async def test_the_status_says_whether_there_is_a_recovery_passcode(store):
    app = _app(store)
    async with app.router.lifespan_context(app), _client(app) as c:
        assert (await c.get("/api/pair/status")).json()["passcode"] is False
        devices.new_passcode(store)
        assert (await c.get("/api/pair/status")).json()["passcode"] is True


async def test_removing_a_device_stops_its_push(store):
    app = _app(store)
    async with app.router.lifespan_context(app), _client(app) as mac, _client(app) as phone:
        await _pair(store, mac)
        code = (await mac.post("/api/devices/code")).json()["code"]
        assert (await phone.post("/api/pair/code", json={"code": code, "name": "Phone"})).status_code == 200
        sub = lambda who: {"endpoint": f"https://push.example/{who}", "keys": {"p256dh": "p", "auth": "a"}}  # noqa: E731
        assert (await mac.post("/api/push/subscribe", json=sub("mac"))).status_code == 200
        assert (await phone.post("/api/push/subscribe", json=sub("phone"))).status_code == 200
        phone_id = next(d["id"] for d in (await mac.get("/api/devices")).json() if not d["this"])
        assert (await mac.delete(f"/api/devices/{phone_id}")).status_code == 200
        assert [s["endpoint"] for s in store.list_subscriptions()] == ["https://push.example/mac"]


async def test_a_removed_device_loses_its_live_stream(store, monkeypatch):
    from odie.app import routes
    monkeypatch.setattr(routes, "PING_EVERY", 0.05)
    app = _app(store)
    async with app.router.lifespan_context(app), _client(app) as c:
        await _pair(store, c)
        stream = asyncio.create_task(c.get("/api/events"))  # the test transport returns once the stream ends
        await asyncio.sleep(0.3)
        assert not stream.done()
        devices.remove_device(store, devices.list_devices(store)[0]["id"])
        r = await asyncio.wait_for(stream, 3)
        assert '"ping"' in r.text


# ── the setup token never reaches the server log ──

def test_without_pairing_query():
    assert devices.without_pairing_query("/api/pair/setup?token=abc") == "/api/pair/setup?[hidden]"
    assert devices.without_pairing_query("/api/pair/status") == "/api/pair/status"
    assert devices.without_pairing_query("/api/chat?x=1") == "/api/chat?x=1"
    assert devices.without_pairing_query("127.0.0.1:50000") == "127.0.0.1:50000"


def test_a_real_uvicorn_access_log_hides_the_setup_token():
    """A real uvicorn server writes its access lines; the setup link's token isn't in them, the rest of the line is."""
    import logging
    import threading
    import time
    import urllib.request

    import uvicorn

    async def app(scope, receive, send):
        if scope["type"] != "http":
            return
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    lines: list[str] = []

    class Keep(logging.Handler):
        def emit(self, record):
            lines.append(record.getMessage())

    access = logging.getLogger("uvicorn.access")
    keep = Keep()
    access.addHandler(keep)
    devices.hide_pairing_queries_in_access_log()  # what create_app does
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_config=None, log_level="info",
                                           lifespan="off"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.05)
        port = server.servers[0].sockets[0].getsockname()[1]
        for path in ("/api/pair/setup?token=SECRET-TOKEN", "/api/chat?x=1"):
            urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5).read()
    finally:
        server.should_exit = True
        thread.join(5)
        access.removeHandler(keep)
    assert any('"GET /api/pair/setup?[hidden] HTTP/1.1" 200' in line for line in lines), lines
    assert any('"GET /api/chat?x=1 HTTP/1.1" 200' in line for line in lines), lines
    assert not any("SECRET-TOKEN" in line for line in lines)


def test_odie_hides_pairing_queries_from_its_access_log(store):
    import logging
    access = logging.getLogger("uvicorn.access")
    access.removeFilter(devices.ACCESS_LOG_FILTER)  # whatever an earlier test left
    _app(store)
    _app(store)
    assert access.filters.count(devices.ACCESS_LOG_FILTER) == 1  # added once, however many apps are made
