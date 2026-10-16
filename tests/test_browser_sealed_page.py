"""A sealed page in a real browser: it evaluates, takes pictures, reports errors, WebGL works in the render
browser (three.js needs it), and nothing in the render browser reaches the network, WebSockets and workers included."""
import asyncio

import pytest

from odie.browser import RENDER_ARGS, engine, find
from odie.browser.engine import Browser, BrowserError, BrowserTimeout

BIN = find.installed()
pytestmark = pytest.mark.skipif(BIN is None, reason="no Chrome, Edge, Chromium or Brave here")

PAGE = "<!doctype html><body style='margin:0;background:#123'><script>window.answer = 6 * 7;</script></body>"


async def test_a_sealed_page_evaluates_and_takes_a_picture(tmp_path):
    b = Browser(tmp_path / "p", BIN)
    try:
        async with b.sealed_page(PAGE, 320, 180) as page:
            assert await page.eval("window.answer") == 42
            shot = await page.shot()
    finally:
        await b.close()
    assert shot[:3] == b"\xff\xd8\xff"


async def test_errors_are_reported_in_order(tmp_path):
    html = "<script>console.error('first'); null.boom;</script>"
    b = Browser(tmp_path / "p", BIN)
    try:
        async with b.sealed_page(html, 320, 180) as page:
            await page.eval("1")
            errors = list(page.errors)
    finally:
        await b.close()
    assert "first" in errors[0] and ("null" in errors[1].lower() or "boom" in errors[1])


async def test_a_page_that_never_answers_is_told_as_a_timeout(tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "SEALED_TIMEOUT", 1)  # a second, not two minutes
    html = "<script>window.spin = () => { while (true) {} };</script>"
    b = Browser(tmp_path / "p", BIN)
    try:
        with pytest.raises(BrowserTimeout):
            async with b.sealed_page(html, 320, 180) as page:
                await page.eval("spin()")
    finally:
        await b.close()


async def test_the_callers_own_errors_come_out_as_they_are(tmp_path):
    b = Browser(tmp_path / "p", BIN)
    try:
        with pytest.raises(TimeoutError, match="the caller's own") as caught:
            async with b.sealed_page(PAGE, 320, 180):
                raise TimeoutError("the caller's own")
    finally:
        await b.close()
    assert not isinstance(caught.value, BrowserError)


async def test_webgl_works_in_the_render_browser(tmp_path):
    b = Browser(tmp_path / "p", BIN, extra_args=RENDER_ARGS)
    try:
        async with b.sealed_page("<canvas id=c></canvas>", 320, 180) as page:
            ok = await page.eval("!!document.getElementById('c').getContext('webgl2')")
    finally:
        await b.close()
    assert ok


SOCKET_PAGE = """<script>
window.pageSocket = "pending";
window.workerSocket = "pending";
const page = new WebSocket("ws://127.0.0.1:PORT");
page.onopen = () => { window.pageSocket = "open"; page.send("from the page"); };
page.onclose = () => { if (window.pageSocket === "pending") window.pageSocket = "refused"; };
const source = `const w = new WebSocket("ws://127.0.0.1:PORT");
w.onopen = () => { w.send("from a worker"); postMessage("open"); };
w.onclose = () => postMessage("refused");`;
const worker = new Worker(URL.createObjectURL(new Blob([source], {type: "text/javascript"})));
worker.onmessage = (e) => { if (window.workerSocket === "pending") window.workerSocket = e.data; };
</script>"""


async def test_the_render_browser_lets_no_websocket_out_from_the_page_or_a_worker(tmp_path):
    websockets = pytest.importorskip("websockets")
    heard = []

    async def listen(socket):
        heard.append("connected")
        async for message in socket:
            heard.append(message)

    server = await websockets.serve(listen, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    b = Browser(tmp_path / "p", BIN, extra_args=RENDER_ARGS)
    try:
        async with b.sealed_page(SOCKET_PAGE.replace("PORT", str(port)), 320, 180) as page:
            for _ in range(100):  # until both sockets have an answer, at most 10 s
                outcome = await page.eval("[window.pageSocket, window.workerSocket]")
                if "pending" not in outcome:
                    break
                await asyncio.sleep(0.1)
    finally:
        await b.close()
        server.close()
        await server.wait_closed()
    assert outcome == ["refused", "refused"]
    assert heard == []
