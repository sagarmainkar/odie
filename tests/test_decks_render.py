"""Rendering a deck in a real headless browser: one PDF page and one picture per slide; the render tab reaches
nothing (a remote image, stylesheet or fetch in the HTML is refused, even with a policy that would allow it)."""
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from odie.browser import find
from odie.browser.engine import Browser

BIN = find.installed()
pytestmark = pytest.mark.skipif(BIN is None, reason="no Chrome, Edge, Chromium or Brave here")


def slides(n, extra=""):
    body = "".join(f'<section style="width:640px;height:360px;background:#{i}{i}3355;color:#fff;break-after:page">S{i}{extra}</section>'
                   for i in range(n))
    return f"<!doctype html><html><head><style>@page{{size:640px 360px;margin:0}}body{{margin:0}}</style></head><body>{body}</body></html>"


async def allow_all(url):
    return True


async def test_a_deck_renders_to_a_pdf_and_pictures(tmp_path):
    b = Browser(tmp_path / "profile", BIN)
    try:
        pdf, shots = await b.render(slides(3), 640, 360, 3)
    finally:
        await b.close()
    assert pdf.startswith(b"%PDF") and len(re.findall(rb"/Type\s*/Page[^s]", pdf)) == 3
    assert len(shots) == 3 and all(s[:3] == b"\xff\xd8\xff" for s in shots)


async def test_the_render_tab_reaches_nothing(tmp_path):
    hits = []

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append(self.path)
            self.send_response(200)
            self.end_headers()

        def log_message(self, *a):
            pass
    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_port
    sneaky = (f'<img src="http://127.0.0.1:{port}/img"><link rel=stylesheet href="http://127.0.0.1:{port}/css">'
              f'<script>fetch("http://127.0.0.1:{port}/js")</script>')
    b = Browser(tmp_path / "profile", BIN, policy=allow_all, ip_ok=lambda ip: True)
    try:
        pdf, shots = await b.render(slides(1, sneaky), 640, 360, 1)
        browsing = await b.open("chat", f"http://127.0.0.1:{port}/page")  # the same browser still browses as before
    finally:
        await b.close()
        srv.shutdown()
    assert pdf.startswith(b"%PDF") and len(shots) == 1
    assert not {"/img", "/css", "/js"} & set(hits)  # the sealed tab sent nothing
    assert "/page" in hits  # the ordinary tab still reaches the server
    assert browsing is not None
