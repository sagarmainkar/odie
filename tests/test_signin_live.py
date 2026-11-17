"""The live view (spec Part 1), server side: the phone gets the tab's frames and page, and its taps, typing and keys
become engine calls; one device holds a tab, another can take over; Done records the site; a dropped or idle view hands
the tab back; nothing typed is logged or saved; and while signed-in browsing is off, there's no live view at all.
Watching: the user sees Odie's page while Odie works, holds nothing and sends nothing, until they take control."""
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
        self.watched = []  # tabs opened only to watch (emulate=False)

    def hold(self, tab, holder):
        self.holds[tab] = holder

    def release(self, tab, holder=None):
        self.holds.pop(tab, None)

    def held_by(self, tab):
        return self.holds.get(tab)

    def on_upi(self, fn):
        self.upi.append(fn)

    async def live_start(self, tab, width, height, on_frame, on_page, emulate=True):
        self.calls.append(("start", tab, width, height))
        if not emulate:
            self.watched.append(tab)
        await on_page({"url": "https://www.amazon.in/ap/signin", "title": "Amazon Sign-In", "loading": False})
        await on_frame("/9j/AAAA", {"deviceWidth": width, "deviceHeight": height})

    async def live_control(self, tab, width, height):
        self.calls.append(("control", tab, width, height))

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


WATCH = {**HELLO, "watch": True}
TAB = "chat-2026-10-08"


def inputs(engine):
    return [c[2] for c in engine.calls if c[0] == "input"]


def test_watching_holds_nothing_until_take_control(app, engine):
    """Watch from the chat: Odie keeps the tab (no hold) and the user's taps go nowhere. Take control holds it and
    makes it the user's to drive; Close hands it back."""
    from odie.signin import live
    c = app.state.client
    with c.websocket_connect(URL) as ws:
        ws.send_json(WATCH)
        assert ws.receive_json()["t"] == "page" and ws.receive_json()["t"] == "frame"
        assert engine.watched == [TAB] and engine.held_by(TAB) is None  # Odie keeps working on its page
        ws.send_json({"t": "tap", "x": 10, "y": 10})
        ws.send_json({"t": "go", "url": "https://evil.example/"})
        settle(ws)
        assert inputs(engine) == []  # watching: nothing reaches the page
        ws.send_json({"t": "control"})
        assert ws.receive_json() == {"t": "control"}
        assert engine.held_by(TAB) and ("control", TAB, 390, 844) in engine.calls  # Odie's browser steps wait now
        ws.send_json({"t": "control"})  # already in control: nothing more
        ws.send_json({"t": "forward"})
        settle(ws)
        assert inputs(engine) == [{"t": "forward"}]
        assert [c for c in engine.calls if c[0] == "control"] == [("control", TAB, 390, 844)]
        ws.send_json({"t": "close"})
    assert engine.held_by(TAB) is None and engine.calls[-1] == ("stop", TAB)  # handed back
    for step in ({"t": "forward"}, {"t": "control"}, {"t": "close"}):
        assert live.clean(step) == step
    assert live.clean({"t": "control", "js": "alert(1)"}) == {"t": "control"}  # nothing rides along


def test_after_control_i_signed_in_records_the_site_and_hand_back_does_not(app, store, engine):
    """After Take control the bar has two ways back: Hand back (Cancel) records nothing, "I signed in" (Done) records
    the site, so its order and pay clicks ask. Done on a view that only watched records nothing: the user never
    touched the page."""
    c = app.state.client
    with c.websocket_connect(URL) as ws:
        ws.send_json(WATCH)
        ws.receive_json(), ws.receive_json()
        assert c.post(f"{URL}/done").json() == {"site": "amazon.in"}  # only watched
    assert sites.listing(store) == []
    with c.websocket_connect(URL) as ws:
        ws.send_json(WATCH)
        ws.receive_json(), ws.receive_json()
        ws.send_json({"t": "control"})
        assert ws.receive_json() == {"t": "control"}
        assert c.post(f"{URL}/cancel").json() == {"site": "amazon.in"}  # Hand back
        assert ws.receive_json() == {"t": "bye", "why": "cancel"}
    assert sites.listing(store) == [] and engine.held_by(TAB) is None
    with c.websocket_connect(URL) as ws:
        ws.send_json(WATCH)
        ws.receive_json(), ws.receive_json()
        ws.send_json({"t": "control"})
        assert ws.receive_json() == {"t": "control"}
        assert c.post(f"{URL}/done").json() == {"site": "amazon.in"}  # I signed in
        assert ws.receive_json() == {"t": "bye", "why": "done"}
    assert [s["domain"] for s in sites.listing(store)] == ["amazon.in"]
    assert sites.is_signed_in(store, "https://www.amazon.in/gp/buy")
    assert engine.held_by(TAB) is None


def test_a_watcher_who_only_watched_hands_nothing_back_but_the_view(app, engine):
    """Close without ever taking control: the view stops, and there was never a hold to release."""
    c = app.state.client
    with c.websocket_connect(URL) as ws:
        ws.send_json(WATCH)
        ws.receive_json(), ws.receive_json()
        ws.send_json({"t": "close"})
    assert engine.held_by(TAB) is None and engine.calls[-1] == ("stop", TAB)
    assert not [c for c in engine.calls if c[0] in ("control", "input")]


def test_a_driver_joining_a_watched_view_takes_control(app, engine):
    """The watcher's socket dropped without Close; within the grace a Sign in card opens the same tab to drive it:
    the view becomes the user's turn (held, phone-shaped), not a watch that ignores their taps."""
    c = app.state.client
    with c.websocket_connect(URL) as ws:
        ws.send_json(WATCH)
        ws.receive_json(), ws.receive_json()
    assert engine.held_by(TAB) is None
    with c.websocket_connect(URL) as ws:
        ws.send_json(HELLO)
        got = [ws.receive_json() for _ in range(3)]
        assert {"t": "control"} in got
        assert engine.held_by(TAB) and ("control", TAB, 390, 844) in engine.calls
        ws.send_json({"t": "tap", "x": 5, "y": 5})
        settle(ws)
        assert inputs(engine) == [{"t": "tap", "x": 5, "y": 5}]


def test_a_watcher_joining_a_driven_view_is_told_it_drives(app, engine):
    """The other way round: the user is mid sign-in (the tab is theirs), the socket drops, and Watch opens the same
    tab. The view is still the user's turn, so the phone is told it drives, and the hold stays."""
    c = app.state.client
    with c.websocket_connect(URL) as ws:
        opened(ws)
    with c.websocket_connect(URL) as ws:
        ws.send_json(WATCH)
        got = [ws.receive_json() for _ in range(3)]
        assert {"t": "control"} in got and engine.held_by(TAB)
        assert engine.watched == []  # the page was never opened watch-only


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


# A page that never stops changing, so the live view keeps taking pictures of it (most real pages do: a clock, an ad,
# a spinner). The tab's shape must still change when the user takes control and when they hand back.
BUSY_PAGE = """<!doctype html><meta name="viewport" content="width=device-width"><title>busy</title><body style="margin:0">
<div id="c" style="font-size:40px"></div><script>setInterval(() => { c.textContent = Date.now(); }, 30);</script></body>"""


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
            pages = {"/desktop": DESKTOP_PAGE, "/busy": BUSY_PAGE,
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


@pytest.mark.skipif(__import__("odie.browser.find", fromlist=["installed"]).installed() is None, reason="no Chrome here")
async def test_watching_leaves_the_real_page_as_it_is_until_control(tmp_path, tap_site):
    """In real Chrome, on a page that never stops changing: a watched tab keeps its desktop shape and its fence while
    frames arrive; Take control makes it phone-shaped and lifts the fence; forward goes forward; stopping puts the
    desktop shape back. A tab that was only watched is never reshaped at all.
    (Found on the way: Chrome puts a page's old shape back after a screenshot, so a new shape sent while a live picture
    was being taken was lost. Take control left the page desktop-shaped, and a stop left it phone-shaped.)"""
    from odie.browser import find
    from odie.browser.engine import Browser, BrowserError

    async def allow_all(url):
        return True
    b = Browser(tmp_path / "profile", find.installed(), policy=allow_all, ip_ok=lambda ip: True)
    frames = []

    async def on_frame(jpeg, meta):
        frames.append((jpeg, meta))

    async def on_page(info):
        pass

    async def many_frames():
        return len(frames) >= 10
    try:
        await b.open("chat", f"http://127.0.0.1:{tap_site}/busy")
        s = b._tabs["chat"]

        async def title():
            return await b._eval(s, "document.title")

        async def width():
            return await b._eval(s, "window.innerWidth")
        with pytest.raises(BrowserError):
            await b.live_control("chat", 390, 844)  # nothing is live on the tab yet
        b.fence("chat", {"127.0.0.1"})
        await b.live_start("chat", 390, 844, on_frame, on_page, emulate=False)
        assert await _until(many_frames)  # pictures keep being taken
        assert frames[0][0].startswith("/9j/") and _jpeg_size(frames[-1][0])[0] == 1280
        assert await width() == 1280 and b._fences.get("chat") == {"127.0.0.1"}  # watching changed nothing
        assert b.held_by("chat") is None

        await b.live_control("chat", 390, 844)
        assert await _until(lambda: _eq(width, 390))  # the user's to drive now, even with a picture in flight
        assert "chat" not in b._fences
        frames.clear()
        assert await _until(many_frames)
        assert _jpeg_size(frames[-1][0])[0] == 780  # and the pictures are phone-shaped, at 2x
        await b.live_input("chat", {"t": "go", "url": f"http://127.0.0.1:{tap_site}/desktop"})
        assert await _until(lambda: _eq(title, "Desktop sign-in"))
        await b.live_input("chat", {"t": "back"})
        assert await _until(lambda: _eq(title, "busy"))
        await b.live_input("chat", {"t": "forward"})
        assert await _until(lambda: _eq(title, "Desktop sign-in"))
        await b.live_input("chat", {"t": "back"})
        assert await _until(lambda: _eq(title, "busy"))
        frames.clear()
        assert await _until(many_frames)
        await b.live_stop("chat")
        assert await _until(lambda: _eq(width, 1280))  # desktop-shaped again, for Odie's next step

        await b.live_start("chat", 390, 844, on_frame, on_page, emulate=False)  # watched, never driven
        await b.live_stop("chat")
        assert await width() == 1280 and "chat" not in b._emulated
    finally:
        await b.close()


@pytest.mark.skipif(__import__("odie.browser.find", fromlist=["installed"]).installed() is None, reason="no Chrome here")
async def test_a_still_page_sends_one_picture_not_a_stream(tmp_path, tap_site):
    """Taking the live picture makes Chrome cast the page again, and that echo used to be answered with another
    picture: a still page being watched sent about 25 a second for as long as it was watched. Now the echo is dropped;
    a real change still arrives, and a phone that joins again still gets its first picture."""
    import asyncio

    from odie.browser import find
    from odie.browser.engine import Browser

    async def allow_all(url):
        return True
    b = Browser(tmp_path / "profile", find.installed(), policy=allow_all, ip_ok=lambda ip: True)
    frames = []

    async def on_frame(jpeg, meta):
        frames.append(jpeg)

    async def on_page(info):
        pass
    try:
        await b.open("chat", f"http://127.0.0.1:{tap_site}/")
        s = b._tabs["chat"]
        await b.live_start("chat", 390, 844, on_frame, on_page, emulate=False)
        assert await _until(lambda: _true(frames))
        await asyncio.sleep(1.5)
        assert len(frames) <= 3, f"{len(frames)} pictures of a page that didn't change"

        frames.clear()
        await b._eval(s, "document.body.style.background = 'crimson'")
        assert await _until(lambda: _true(frames))  # a change on the page reaches the phone

        await asyncio.sleep(0.5)
        frames.clear()
        await b.live_start("chat", 390, 844, on_frame, on_page, emulate=False)  # the phone joins again
        assert await _until(lambda: _true(frames))  # and gets a picture, though nothing changed
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
