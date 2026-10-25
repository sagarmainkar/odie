"""Where a request comes from (odie.app.origin): a Host Odie doesn't own is refused (DNS rebinding), and a change or a
WebSocket from a page that isn't Odie's is refused (cross-site requests the browser sends without a preflight)."""
import httpx
import pytest
from starlette.testclient import TestClient

from odie.app import origin
from odie.app.main import create_app
from odie.store.db import Store
from tests.test_api import FakeRunner

EVIL = "https://rebind.attacker.test"


def test_hosts_odie_answers_to(monkeypatch):
    monkeypatch.setenv("ODIE_PUBLIC_URL", "https://mac.ts.net")
    monkeypatch.setenv("ODIE_HOSTS", "odie.lan,t,testserver")
    for host in ("127.0.0.1:8000", "192.168.1.5:8000", "[::1]:8000", "localhost:8000", "LOCALHOST", "mac.ts.net",
                 "mac.local", "odie.lan", "t", "testserver", "x.ts.net"):
        assert origin.host_allowed(host), host
    for host in ("rebind.attacker.test", "rebind.attacker.test:8000", "127.0.0.1.attacker.test", "", "localhost.evil.test"):
        assert not origin.host_allowed(host), host


def test_origins_that_are_odies_own_page():
    assert origin.origin_allowed(None, "127.0.0.1:8000")  # no browser: curl, a test
    assert origin.origin_allowed("http://127.0.0.1:8000", "127.0.0.1:8000")
    assert origin.origin_allowed("https://mac.ts.net", "mac.ts.net")  # behind Tailscale's proxy the port differs
    assert origin.origin_allowed("http://localhost:5173", "127.0.0.1:8000")  # the dev server, the same computer
    assert origin.origin_allowed("https://mac.ts.net", "127.0.0.1:8000")  # the phone, through a proxy that rewrote Host
    assert origin.origin_allowed("http://192.168.1.5:8000", "192.168.1.5:8000")
    assert not origin.origin_allowed("http://203.0.113.5", "127.0.0.1:8000")  # another machine's page is not Odie's
    assert not origin.origin_allowed("http://192.168.1.9", "192.168.1.5:8000")
    assert not origin.origin_allowed(EVIL, "127.0.0.1:8000")
    assert not origin.origin_allowed("null", "127.0.0.1:8000")
    assert not origin.origin_allowed("http://127.0.0.1.attacker.test", "127.0.0.1")


@pytest.fixture
async def client(isolated_settings, tmp_path):
    s = Store(tmp_path / "assistant.db")
    s.init_schema()
    app = create_app(runner=FakeRunner(), store=s)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c, app.router.lifespan_context(app):
        yield c, app


async def test_a_host_odie_does_not_own_is_refused_everywhere(client):
    c, _ = client
    assert (await c.get("/api/health")).status_code == 200
    for path in ("/api/health", "/api/pair/status", "/api/mcp", "/"):
        r = await c.get(path, headers={"Host": "rebind.attacker.test"})
        assert r.status_code == 421, path
    r = await c.post("/api/mcp/check", json={"spec": {"command": "/bin/sh", "args": ["-c", "id"]}}, headers={"Host": "rebind.attacker.test"})
    assert r.status_code == 421 and "ODIE_HOSTS" in r.json()["detail"]
    assert (await c.get("/api/health", headers={"Host": "127.0.0.1:8000"})).status_code == 200


async def test_a_change_from_another_page_is_refused(client):
    c, _ = client
    png = b"\x89PNG\r\n\x1a\n" + b"\0" * 32
    files = {"file": ("x.png", png, "image/png")}
    r = await c.post("/api/upload", files=files, headers={"Origin": EVIL})
    assert r.status_code == 403 and r.json() == origin.REFUSED_ORIGIN  # a multipart POST needs no preflight: refused here
    r = await c.post("/api/upload", files=files, headers={"Origin": "http://t"})
    assert r.status_code == 422  # Odie's own page: the request reaches the route (the bytes aren't an image)
    r = await c.post("/api/upload", files=files)
    assert r.status_code == 422  # no Origin: not a browser
    r = await c.get("/api/pair/status", headers={"Origin": EVIL})
    assert r.status_code == 200  # a GET changes nothing, and its answer isn't readable cross-site anyway


def test_a_websocket_from_another_page_is_closed(isolated_settings, tmp_path, monkeypatch):
    from odie.signin import state
    s = Store(tmp_path / "assistant.db")
    s.init_schema()
    monkeypatch.setattr(state, "is_on", lambda store: True)
    app = create_app(runner=FakeRunner(), store=s)

    class Live:
        async def serve(self, tab, websocket):
            await websocket.send_json({"tab": tab})
            await websocket.close()

        async def close(self):
            pass
    with TestClient(app) as c:
        app.state.live = Live()  # after startup, which sets the real one (it would start a browser)
        with c.websocket_connect("/api/browser/live/chat-1", headers={"Origin": "http://testserver"}) as ws:
            assert ws.receive_json() == {"tab": "chat-1"}
        with c.websocket_connect("/api/browser/live/chat-1") as ws:  # no Origin: not a browser
            assert ws.receive_json() == {"tab": "chat-1"}
        from starlette.websockets import WebSocketDisconnect
        with pytest.raises(WebSocketDisconnect) as closed, c.websocket_connect("/api/browser/live/chat-1", headers={"Origin": EVIL}) as ws:
            ws.receive_json()
        assert closed.value.code == 4403
