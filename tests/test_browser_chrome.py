"""The browser engine against a real headless browser and a local test site. A second local server stands in for the
home network: the test policy treats it as private, and nothing may reach it. Skipped when there's no browser."""
import asyncio
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from odie.browser import find
from odie.browser.engine import Browser, BrowserError

BIN = find.installed()  # whatever ODIE_BROWSER says for the rest of the tests
pytestmark = pytest.mark.skipif(BIN is None, reason="no Chrome, Edge, Chromium or Brave here")
SITE = Path(__file__).parent / "fixtures" / "browser_site"


def _serve(handler):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


@pytest.fixture
def servers():
    hits = []

    class Private(BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append(self.path)
            self.send_response(200)
            self.end_headers()

        def log_message(self, *a):
            pass
    private = _serve(Private)

    class Site(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/slow.html":  # a page that takes a moment
                import time
                time.sleep(1.5)
                body = b"<!doctype html><title>Slow page</title><main><h1>Slow page</h1></main>"
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(body)
                return
            if self.path.startswith("/img/"):  # a generated picture of the size its name says: /img/big1-800x600.jpg
                import io
                import re as _re

                from PIL import Image
                w, h = map(int, _re.search(r"-(\d+)x(\d+)\.", self.path).groups())
                out = io.BytesIO()
                fmt = "PNG" if self.path.endswith(".png") else "JPEG"
                Image.new("RGB", (w, h), (90, 120, 150)).save(out, fmt)
                self.send_response(200)
                self.send_header("Content-Type", "image/png" if fmt == "PNG" else "image/jpeg")
                self.end_headers()
                self.wfile.write(out.getvalue())
                return
            if self.path == "/redirect":
                self.send_response(302)
                self.send_header("Location", f"http://127.0.0.1:{private.server_port}/redirected")
                self.end_headers()
                return
            name = self.path.split("?")[0].lstrip("/") or "index.html"
            f = SITE / name
            if not f.is_file():
                self.send_response(404)
                self.end_headers()
                return
            body = f.read_text().replace("{PRIVATE}", str(private.server_port)).replace("{OTHER}", f"http://127.0.0.1:{other.server_port}").encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass
    site = _serve(Site)
    other = _serve(Site)  # a second "public" site, for cross-site frames
    yield f"http://127.0.0.1:{site.server_port}", f"http://127.0.0.1:{private.server_port}", hits, f"http://127.0.0.1:{other.server_port}"
    for srv in (site, other, private):
        srv.shutdown()


@pytest.fixture
async def browser(servers, tmp_path):
    public = (servers[0], servers[3])

    async def policy(url):  # the test sites are "public"; everything else, the private server included, is not
        return any(url == b or url.startswith(b + "/") for b in public)
    b = Browser(tmp_path / "profile", binary=BIN, policy=policy, ip_ok=lambda ip: True)  # the test sites are on 127.0.0.1
    yield b
    await b.close()


async def test_open_reads_the_main_content(browser, servers):
    page = await browser.open("t1", servers[0] + "/")
    assert page.title == "Test Shop" and page.url == servers[0] + "/"
    assert "AirPods Pro 3" in page.text and "₹24,930" in page.text and "Bottom of the page" in page.text
    assert "Hello, sign in" not in page.text and "Terms. Privacy." not in page.text  # navigation and footer left out
    assert "AirPods Max" not in page.text  # hidden until shown
    assert "Search the shop" not in page.text  # a #search box before the content isn't taken for it
    assert page.shot[:2] == b"\xff\xd8" and len(page.shot) > 1000  # a JPEG


async def test_click_by_text(browser, servers):
    await browser.open("t1", servers[0] + "/")
    page = await browser.click("t1", "Show more")
    assert "AirPods Max: ₹59,900" in page.text
    page = await browser.click("t1", "next PAGE")
    assert page.url.endswith("/page2.html") and "More results here." in page.text
    with pytest.raises(BrowserError) as e:
        await browser.click("t1", "Buy now")
    assert "Buy now" in str(e.value)


async def test_type_and_submit(browser, servers):
    await browser.open("t1", servers[0] + "/")
    page = await browser.type("t1", "search products", "airpods pro")
    assert "/search.html?q=airpods" in page.url and "You searched for airpods pro" in page.text


async def test_password_fields_are_refused(browser, servers):
    await browser.open("t1", servers[0] + "/")
    with pytest.raises(BrowserError) as e:
        await browser.type("t1", "Password", "hunter2")
    assert "never type" in str(e.value)  # refused as a secret field, not just "not found"
    s = await browser._session("t1", False)
    assert await browser._eval(s, "document.getElementById('pw').value") == ""


async def test_requests_to_the_home_network_are_blocked(browser, servers):
    page = await browser.open("t1", servers[0] + "/")
    await asyncio.sleep(0.5)
    assert servers[2] == [] and "Blocked 1" in page.note  # the page's image on the "home network" never loaded
    with pytest.raises(BrowserError) as e:
        await browser.open("t1", servers[1] + "/")
    assert "home network" in str(e.value) or "public" in str(e.value)
    assert servers[2] == []


async def test_one_tab_per_thread(browser, servers):
    await browser.open("a", servers[0] + "/")
    await browser.open("b", servers[0] + "/page2.html")
    page = await browser.scroll("a")
    assert page.title == "Test Shop"
    page = await browser.scroll("b")
    assert page.title == "Page two"
    with pytest.raises(BrowserError):
        await browser.click("c", "Next page")  # nothing open there yet


async def test_idle_close_and_restart(servers, tmp_path):
    base = servers[0]

    async def policy(url):
        return url.startswith(base)
    b = Browser(tmp_path / "profile", binary=BIN, policy=policy, idle=0.5, ip_ok=lambda ip: True)
    try:
        await b.open("t1", base + "/")
        proc = b._proc
        await asyncio.sleep(1.5)
        assert proc.poll() is not None and not b.running  # closed after being idle
        page = await b.open("t1", base + "/page2.html")
        assert page.title == "Page two" and b.running
    finally:
        await b.close()


async def test_no_process_is_left_behind(servers, tmp_path):
    base = servers[0]

    async def policy(url):
        return url.startswith(base)
    b = Browser(tmp_path / "profile", binary=BIN, policy=policy, ip_ok=lambda ip: True)
    await b.open("t1", base + "/")
    proc = b._proc
    await b.close()
    assert proc.poll() is not None
    out = await asyncio.create_subprocess_exec("pgrep", "-f", str(tmp_path / "profile"), stdout=asyncio.subprocess.PIPE)
    found, _ = await out.communicate()
    assert found.strip() == b""


async def test_a_hung_browser_is_still_closed(servers, tmp_path):
    import os
    import signal
    base = servers[0]

    async def policy(url):
        return url.startswith(base)
    b = Browser(tmp_path / "profile", binary=BIN, policy=policy, ip_ok=lambda ip: True)
    await b.open("t1", base + "/")
    os.kill(b._proc.pid, signal.SIGSTOP)  # the browser stops answering
    await asyncio.wait_for(b.close(), 15)
    out = await asyncio.create_subprocess_exec("pgrep", "-f", str(tmp_path / "profile"), stdout=asyncio.subprocess.PIPE)
    found, _ = await out.communicate()
    assert found.strip() == b""


async def test_pop_ups_never_reach_the_home_network(browser, servers):
    await browser.open("t1", servers[0] + "/deals.html")
    for button in ("Open deal", "Quiet deal"):  # scripts that open windows to the home network
        await browser.click("t1", button)
    with pytest.raises(BrowserError) as e:  # a new-window link opens in the tab, and is refused there
        await browser.click("t1", "Partner deal")
    assert "home network" in str(e.value)
    await browser.open("t1", servers[0] + "/deals.html")
    await browser.type("t1", "Coupon", "SAVE10")  # a form that opens a new window
    await asyncio.sleep(1.0)
    assert servers[2] == []


async def test_another_sites_frames_are_checked_too(browser, servers):
    page = await browser.open("t1", servers[0] + "/frames.html")
    await asyncio.sleep(1.0)
    assert servers[2] == [] and page.title == "Frames"


async def test_websockets_to_the_home_network_are_refused(browser, servers):
    page = await browser.open("t1", servers[0] + "/ws.html")
    await asyncio.sleep(0.5)
    assert servers[2] == [] and "refused" in page.text


async def test_a_redirect_to_the_home_network_says_so(browser, servers):
    with pytest.raises(BrowserError) as e:
        await browser.open("t1", servers[0] + "/redirect")
    assert "home network" in str(e.value) and servers[2] == []


async def test_booking_fields_can_be_typed_into(browser, servers):
    await browser.open("t1", servers[0] + "/deals.html")
    await browser.type("t1", "Passenger name", "Asha Rao", submit=False)
    await browser.type("t1", "PIN code", "411006", submit=False)
    with pytest.raises(BrowserError) as e:
        await browser.type("t1", "Card number", "4111 1111 1111 1111", submit=False)
    assert "never type" in str(e.value)


async def test_an_empty_click_is_refused(browser, servers):
    await browser.open("t1", servers[0] + "/")
    with pytest.raises(BrowserError):
        await browser.click("t1", "  ")


async def test_one_action_at_a_time_per_tab(browser, servers):
    await browser.open("t1", servers[0] + "/")
    opened, scrolled = await asyncio.gather(browser.open("t1", servers[0] + "/slow.html"), browser.scroll("t1"))
    assert opened.title == "Slow page" and scrolled.title == "Slow page"  # the scroll waited for the open


async def test_a_left_over_browser_doesnt_lock_the_profile(servers, tmp_path):
    base = servers[0]

    async def policy(url):
        return url.startswith(base)
    first = Browser(tmp_path / "profile", binary=BIN, policy=policy, ip_ok=lambda ip: True)
    await first.open("t1", base + "/")
    orphan = first._proc  # Odie killed hard: its browser keeps running, holding the profile
    second = Browser(tmp_path / "profile", binary=BIN, policy=policy, ip_ok=lambda ip: True)
    try:
        page = await second.open("t1", base + "/page2.html")
        assert page.title == "Page two"
        await asyncio.sleep(0.5)
        assert orphan.poll() is not None
    finally:
        await second.close()
        first._proc, first._cdp = None, None


async def test_a_host_that_turns_out_local_is_refused_after_its_first_answer(servers, tmp_path):
    port = servers[0].rsplit(":", 1)[1]

    async def fooled(url):  # what DNS rebinding looks like to Odie: "localhost" checked as public
        return url.startswith(f"http://localhost:{port}")
    b = Browser(tmp_path / "profile", binary=BIN, policy=fooled)  # the real check of where answers come from
    try:
        await b.open("t1", f"http://localhost:{port}/page2.html")  # the first request lands
        with pytest.raises(BrowserError) as e:
            await b.open("t1", f"http://localhost:{port}/")
        assert "home network" in str(e.value)
    finally:
        await b.close()


async def test_a_bot_check_that_clears_is_waited_out(browser, servers, monkeypatch):
    from odie.browser import engine
    monkeypatch.setattr(engine, "BOT_CHECK_WAIT", 6)
    site, *_ = servers
    page = await browser.open("t1", f"{site}/check-clears.html")
    assert page.title == "Dayara Bugyal Trek" and "14 Nov 2026" in page.text and "bot check" not in page.note


async def test_a_bot_check_that_stays_says_so(browser, servers, monkeypatch):
    from odie.browser import engine
    monkeypatch.setattr(engine, "BOT_CHECK_WAIT", 2)
    site, *_ = servers
    page = await browser.open("t1", f"{site}/check-stuck.html")
    assert "bot check" in page.note and "another source" in page.note


async def test_images_on_this_page_are_labelled_and_filtered(browser, servers):
    page = await browser.open("t1", servers[0] + "/listing.html")
    urls = [i["url"] for i in page.images]
    labels = {i["url"].rsplit("/", 1)[1]: i["label"] for i in page.images}
    assert urls[0].endswith("/img/og-1200x630.jpg")  # the page's own cover first
    assert labels["big1-800x600.jpg"] == "Orchidale Homestay" and labels["big2-1000x700.jpg"] == "Ri Kynjai"  # no alt: its card
    assert labels["big3-700x500.jpg"] == "Polo Towers lobby"  # the alt text when there is one
    assert urls[1].endswith("big2-1000x700.jpg")  # largest first
    for junk in ("logo", "icon", "small", "deal", "strip"):
        assert not any(junk in u for u in urls), junk


async def test_a_dropdown_option_is_picked_by_its_words(browser, servers):
    """NSE's option chain picks its expiry from a dropdown (2026-10-08): "click 29-Dec-2026" chooses it, and the page
    hears the change. A miss lists the dropdowns' choices too."""
    await browser.open("t1", servers[0] + "/expiry.html")
    page = await browser.click("t1", "29-dec-2026")
    assert "Showing 29-Dec-2026 contracts: 23000 PE 412.50" in page.text
    with pytest.raises(BrowserError) as e:
        await browser.click("t1", "31-Mar-2027")
    assert 'Dropdowns: "expiry date": "13-oct-2026", "29-dec-2026"' in str(e.value)
