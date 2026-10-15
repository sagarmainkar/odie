"""The live view (spec Part 1), server side: the phone gets the tab's frames and page, and its taps, typing and keys
become engine calls; one device holds a tab, another can take over; Done records the site; a dropped or idle view hands
the tab back; nothing typed is logged or saved; and while signed-in browsing is off, there's no live view at all."""
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from odie.signin import sites, state
from odie.store.db import Store
from tests.test_api import FakeRunner

NOW = datetime(2026, 10, 8, 9, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
HELLO = {"t": "hello", "w": 390, "h": 844}
URL = "/api/browser/live/chat-2026-10-08"


class FakeEngine:
    def __init__(self):
        self.calls = []
        self.holds = {}
        self.upi = []

    def hold(self, tab, holder):
        self.holds[tab] = holder

    def release(self, tab, holder=None):
        self.holds.pop(tab, None)

    def held_by(self, tab):
        return self.holds.get(tab)

    def on_upi(self, fn):
        self.upi.append(fn)

    async def live_start(self, tab, width, height, on_frame, on_page):
        self.calls.append(("start", tab, width, height))
        await on_page({"url": "https://www.amazon.in/ap/signin", "title": "Amazon Sign-In", "loading": False})
        await on_frame("/9j/AAAA", {"deviceWidth": width, "deviceHeight": height})

    async def live_input(self, tab, msg):
        self.calls.append(("input", tab, msg))

    async def live_stop(self, tab):
        self.calls.append(("stop", tab))

    async def close(self):
        pass


@pytest.fixture
def store(isolated_settings, tmp_path):
    s = Store(tmp_path / "a.db")
    s.init_schema()
    state.turn_on(s, accepted=True, version=state.VERSION, now=NOW)
    return s


@pytest.fixture
def engine(monkeypatch):
    import odie.browser
    e = FakeEngine()
    monkeypatch.setattr(odie.browser, "_shared", e)
    return e


@pytest.fixture
def app(store, engine):
    from odie.app.main import create_app
    a = create_app(runner=FakeRunner(), store=store)
    with TestClient(a) as c:
        a.state.client = c
        yield a


def opened(ws):
    """hello, then the page and the first frame."""
    ws.send_json(HELLO)
    return ws.receive_json(), ws.receive_json()


def settle(ws):
    ws.send_json({"t": "ping"})
    assert ws.receive_json() == {"t": "pong"}


def test_the_live_protocol(app, engine):
    c = app.state.client
    with c.websocket_connect(URL) as ws:
        page, frame = opened(ws)
        assert page == {"t": "page", "url": "https://www.amazon.in/ap/signin", "title": "Amazon Sign-In", "loading": False}
        assert frame == {"t": "frame", "jpeg": "/9j/AAAA", "w": 390, "h": 844}
        assert engine.held_by("chat-2026-10-08") and engine.calls[0] == ("start", "chat-2026-10-08", 390, 844)
        sent = [{"t": "tap", "x": 120, "y": 300.5}, {"t": "drag", "x0": 100, "y0": 600, "x1": 100, "y1": 200},
                {"t": "text", "s": "asha@example.com"}, {"t": "key", "k": "Enter"}, {"t": "back"}, {"t": "reload"},
                {"t": "go", "url": "https://www.amazon.in/"}]
        junk = [{"t": "tap", "x": "a", "y": 1}, {"t": "key", "k": "F12"}, {"t": "eval", "js": "alert(1)"}, {"t": "text", "s": 5}]
        for m in [*sent, *junk]:
            ws.send_json(m)
        settle(ws)
        assert [c[2] for c in engine.calls if c[0] == "input"] == sent  # junk never reaches the browser
        engine.upi[0]("chat-2026-10-08", "upi://pay?pa=shop@okaxis&am=499.00")
        assert ws.receive_json() == {"t": "upi", "url": "upi://pay?pa=shop@okaxis&am=499.00"}


def test_one_holder_and_take_over(app, engine):
    c = app.state.client
    with c.websocket_connect(URL) as first:
        opened(first)
        with c.websocket_connect(URL) as second:
            second.send_json(HELLO)
            assert second.receive_json() == {"t": "busy"}
            second.send_json({"t": "take"})
            assert first.receive_json() == {"t": "bye", "why": "taken"}
            assert second.receive_json()["t"] == "page" and second.receive_json()["t"] == "frame"
            second.send_json({"t": "tap", "x": 1, "y": 2})
            settle(second)
            assert engine.held_by("chat-2026-10-08")
    assert engine.calls[-1][0] != "stop"  # a dropped view keeps the tab for a while


def test_done_records_the_site_and_releases(app, store, engine):
    c = app.state.client
    with c.websocket_connect(URL) as ws:
        opened(ws)
        r = c.post(f"{URL}/done")
        assert r.status_code == 200 and r.json() == {"site": "amazon.in"}
        assert ws.receive_json() == {"t": "bye", "why": "done"}
    assert [s["domain"] for s in sites.listing(store)] == ["amazon.in"]
    assert sites.origins_of(store, "amazon.in") == ["https://www.amazon.in"]  # where the user signed in, for Sign out
    assert engine.held_by("chat-2026-10-08") is None and ("stop", "chat-2026-10-08") in engine.calls
    assert c.post(f"{URL}/done").status_code == 404  # nothing is live there now
    sites.remove(store, "amazon.in")
    with c.websocket_connect(URL) as ws:
        opened(ws)
        assert c.post(f"{URL}/cancel").json() == {"site": "amazon.in"}
        assert ws.receive_json() == {"t": "bye", "why": "cancel"}
    assert sites.listing(store) == [] and engine.held_by("chat-2026-10-08") is None


def test_a_dropped_or_idle_view_hands_the_tab_back(app, engine):
    c = app.state.client
    app.state.live.grace = 0.3
    with c.websocket_connect(URL) as ws:
        opened(ws)
    assert engine.held_by("chat-2026-10-08")  # the phone slept: the tab waits for it
    with c.websocket_connect(URL) as ws:
        opened(ws)  # and it comes back without a busy
    deadline = time.monotonic() + 3
    while engine.held_by("chat-2026-10-08") and time.monotonic() < deadline:
        time.sleep(0.05)
    assert engine.held_by("chat-2026-10-08") is None and engine.calls[-1] == ("stop", "chat-2026-10-08")
    app.state.live.idle = 0.3
    with c.websocket_connect(URL) as ws:
        opened(ws)
        assert ws.receive_json() == {"t": "bye", "why": "idle"}
    assert engine.held_by("chat-2026-10-08") is None


def test_turning_off_ends_the_live_view(app, store, engine):
    c = app.state.client
    with c.websocket_connect(URL) as ws:
        opened(ws)
        assert c.post("/api/browser/signin/off").json()["on"] is False
        assert ws.receive_json() == {"t": "bye", "why": "off"}
    assert engine.held_by("chat-2026-10-08") is None and ("stop", "chat-2026-10-08") in engine.calls


def test_live_input_is_never_logged(app, store, engine, isolated_settings):
    c = app.state.client
    with c.websocket_connect(URL) as ws:
        opened(ws)
        ws.send_json({"t": "text", "s": "hunter2-secret"})
        ws.send_json({"t": "key", "k": "Enter"})
        settle(ws)
        c.post(f"{URL}/done")
    rows = store.query("select * from audit_log")
    assert rows and not any("hunter2" in " ".join(str(v) for v in dict(r).values()) for r in rows)
    media = isolated_settings.data_dir / "media"
    assert not media.exists() or not any(media.iterdir())  # no frame is ever saved


def test_off_means_403(app, store, engine):
    c = app.state.client
    state.turn_off(store)
    with pytest.raises(WebSocketDisconnect) as e:
        with c.websocket_connect(URL) as ws:
            ws.send_json(HELLO)
            ws.receive_json()
    assert e.value.code == 4403
    assert c.post(f"{URL}/done").status_code == 403 and engine.calls == []


TAP_PAGE = """<!doctype html><meta name="viewport" content="width=device-width"><title>start</title><body style="margin:0">
<button style="position:absolute;left:0;top:0;width:200px;height:120px" onclick="document.title='tapped'">Tap me</button>
<input style="position:absolute;left:0;top:200px;width:300px;height:60px;font-size:20px"
       onkeydown="if (event.key === 'Enter') document.title = 'entered:' + this.value">
<div style="height:4000px"></div></body>"""


DESKTOP_PAGE = """<!doctype html><title>Desktop sign-in</title><body style="margin:0;width:980px">
<div style="height:260px;background:#eee">header</div>
<form style="margin-left:380px"><label>Email <input id="e" style="width:300px;height:30px;font-size:13px"></label></form></body>"""


@pytest.fixture
def tap_site():
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            port = self.server.server_port
            pages = {"/desktop": DESKTOP_PAGE,
                     "/framed": f'<!doctype html><title>X sign-in</title><main>Sign in to X</main><iframe src="http://localhost:{port}/button"></iframe>',
                     "/button": '<!doctype html><title>Sign in with Google</title><script>setTimeout(() => location.reload(), 400);</script>'}
            self.wfile.write(pages.get(self.path, TAP_PAGE).encode())

        def log_message(self, *a):
            pass
    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv.server_port
    srv.shutdown()


async def _until(check, seconds=8.0):
    import asyncio
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if await check():
            return True
        await asyncio.sleep(0.1)
    return False


@pytest.mark.skipif(__import__("odie.browser.find", fromlist=["installed"]).installed() is None, reason="no Chrome here")
async def test_real_frames_and_a_tap(tmp_path, tap_site):
    from odie.browser import find
    from odie.browser.engine import Browser

    async def allow_all(url):
        return True
    b = Browser(tmp_path / "profile", find.installed(), policy=allow_all, ip_ok=lambda ip: True)
    frames, pages = [], []

    async def on_frame(jpeg, meta):
        frames.append((jpeg, meta))

    async def on_page(info):
        pages.append(info)
    try:
        await b.open("chat", f"http://127.0.0.1:{tap_site}/")
        b.hold("chat", "phone-1")
        await b.live_start("chat", 390, 844, on_frame, on_page)
        s = b._tabs["chat"]

        async def title():
            return await b._eval(s, "document.title")
        assert await _until(lambda: _true(frames))
        assert frames[0][0].startswith("/9j/") and frames[0][1]["deviceWidth"] == 390  # a JPEG, phone-sized
        assert pages[0]["title"] == "start" and await b._eval(s, "window.innerWidth") == 390
        await b.live_input("chat", {"t": "tap", "x": 100, "y": 60})
        assert await _until(lambda: _eq(title, "tapped"))
        await b.live_input("chat", {"t": "tap", "x": 100, "y": 230})
        await b.live_input("chat", {"t": "text", "s": "hello"})
        await b.live_input("chat", {"t": "key", "k": "Enter"})
        assert await _until(lambda: _eq(title, "entered:hello"))
        await b.live_input("chat", {"t": "drag", "x0": 200, "y0": 700, "x1": 200, "y1": 200})
        assert await _until(lambda: _gt(lambda: b._eval(s, "window.scrollY"), 100))
        await b.live_stop("chat")
        assert await b._eval(s, "window.innerWidth") == 1280  # desktop-shaped again
    finally:
        await b.close()


async def _true(xs):
    return bool(xs)


async def _eq(get, want):
    return await get() == want


async def _gt(get, n):
    return (await get() or 0) > n



def _jpeg_size(b64):
    import base64
    import struct
    d, i = base64.b64decode(b64), 2
    while i < len(d):
        if d[i] != 0xFF:
            i += 1
            continue
        if d[i + 1] in (0xC0, 0xC2):
            h, w = struct.unpack(">HH", d[i + 5:i + 9])
            return w, h
        i += 2 + struct.unpack(">H", d[i + 2:i + 4])[0]


@pytest.mark.skipif(__import__("odie.browser.find", fromlist=["installed"]).installed() is None, reason="no Chrome here")
async def test_a_desktop_page_on_a_phone(tmp_path, tap_site):
    """Found in a phone test: a desktop-only page (amazon.in's sign-in, with Odie's desktop identity) is shown at
    about 40%. A tap where the box shows must focus it (taps arrive in the phone's pixels, Chrome reads them in the
    page's), and frames are sharp (2x), not the screencast's blurry 1x."""
    import asyncio

    from odie.browser import find
    from odie.browser.engine import Browser

    async def allow_all(url):
        return True
    b = Browser(tmp_path / "profile", find.installed(), policy=allow_all, ip_ok=lambda ip: True)
    frames = []

    async def on_frame(jpeg, meta):
        frames.append((jpeg, meta))

    async def on_page(info):
        pass
    try:
        await b.open("chat", f"http://127.0.0.1:{tap_site}/desktop")
        await b.live_start("chat", 390, 732, on_frame, on_page)
        s = b._tabs["chat"]
        assert await _until(lambda: _true(frames))
        jpeg, meta = frames[-1]
        assert meta["deviceWidth"] == 390 and _jpeg_size(jpeg)[0] >= 780  # sharp: 2x the phone's pixels
        r = await b._eval(s, "(() => { const e = document.getElementById('e').getBoundingClientRect(); "
                             "return [e.x + e.width / 2, e.y + e.height / 2, visualViewport.scale]; })()")
        assert r[2] < 0.5  # shown shrunk, as on the phone
        await b.live_input("chat", {"t": "tap", "x": r[0] * r[2], "y": r[1] * r[2]})  # where the user sees it
        assert await _until(lambda: _eq(lambda: b._eval(s, "document.activeElement && document.activeElement.id"), "e"))
        await b.live_input("chat", {"t": "text", "s": "asha@example.com"})
        assert await b._eval(s, "document.getElementById('e').value") == "asha@example.com"
        await asyncio.sleep(0.1)
    finally:
        await b.close()


@pytest.mark.skipif(__import__("odie.browser.find", fromlist=["installed"]).installed() is None, reason="no Chrome here")
async def test_an_embedded_box_from_another_site_isnt_the_page(tmp_path, tap_site):
    """X's sign-in page embeds Google's "Sign in with Google" button from accounts.google.com, in a process of its own.
    Its loads are not the page's: the live view (and so Done) keeps the page's own address (found 2026-10-08, when Done
    recorded google.com and amazon-adsystem.com)."""
    import asyncio

    from odie.browser import find
    from odie.browser.engine import Browser

    async def allow_all(url):
        return True
    b = Browser(tmp_path / "profile", find.installed(), policy=allow_all, ip_ok=lambda ip: True)
    pages = []

    async def on_frame(jpeg, meta):
        pass

    async def on_page(info):
        pages.append(info.get("url", ""))
    try:
        await b.open("chat", f"http://127.0.0.1:{tap_site}/framed")
        b.hold("chat", "phone-1")
        await b.live_start("chat", 390, 844, on_frame, on_page)
        await asyncio.sleep(2.5)  # the box reloads itself a few times
        assert any(r != s for s, r in b._root.items()), "the box should have its own process (session)"
        assert pages and all(u.startswith(f"http://127.0.0.1:{tap_site}/") for u in pages), pages
    finally:
        await b.close()
