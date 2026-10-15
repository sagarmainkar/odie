"""The engine for signed-in browsing, against a real headless browser and a local site that sets and shows a cookie:
background tabs see no cookie; signing out of one site keeps the others, and out of everything clears all; a tab the
user holds refuses tools; UPI app launches are caught (as upi:// links); page text reaches the model masked."""
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from odie.browser import find
from odie.browser.engine import Browser, BrowserError, upi_link

BIN = find.installed()
chrome = pytest.mark.skipif(BIN is None, reason="no Chrome, Edge, Chromium or Brave here")

PAY = """<!doctype html><title>Checkout</title><main><h1>Pay ₹499</h1>
<a id="a1" href="upi://pay?pa=shop@okaxis&am=499.00&tr=ORDER1">Pay with UPI app</a>
<a id="a2" href="intent://pay?pa=shop@okaxis&am=499.00#Intent;scheme=upi;package=com.google.android.apps.nbu.paisa.user;end">GPay</a>
<button id="b2" onclick="window.open('upi://pay?pa=shop@okaxis&am=2.00')">Pay (window)</button></main>"""
CODES = """<!doctype html><title>Verify</title><main><form onsubmit="return false">
<label>Email<input id="e"></label>
<input autocomplete="one-time-code" placeholder="Enter the code we sent">
<input autocomplete="cc-exp" placeholder="MM / YY">
<label>UPI PIN<input id="p"></label>
<label>Enter OTP<input id="o"></label></form></main>"""
CARD = """<!doctype html><title>Payment methods</title><main><h1>Your cards</h1>
<p>Visa 4111 1111 1111 1111 expires 12/28.</p><p>Bank A/c 50100123456789 IFSC HDFC0001234.</p>
<p>Order 402-7731234-1234567 for ₹4,200 to pin code 411001.</p></main>"""


@pytest.fixture
def site():
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            body = "<!doctype html><title>t</title><main><p>ok</p></main>"
            extra = []
            if self.path == "/set":
                extra = [("Set-Cookie", "sid=abc; Path=/")]
                body = "<!doctype html><title>set</title><main><p>signed in</p></main>"
            elif self.path == "/who":
                c = self.headers.get("Cookie") or "none"
                body = f"<!doctype html><title>who</title><main><p>cookie: {c}</p></main>"
            elif self.path == "/pay":
                body = PAY
            elif self.path == "/card":
                body = CARD
            elif self.path == "/codes":
                body = CODES
            elif self.path == "/login":
                body = '<!doctype html><title>Sign in</title><main><form><label>Email<input></label><label>Password<input type="password"></label></form></main>'
            elif self.path == "/links":
                port = self.server.server_port
                body = (f'<!doctype html><title>links</title><main><a href="http://localhost:{port}/who">Continue</a>'
                        f'<form action="http://localhost:{port}/who" method="get"><label>Notes<input name="n"></label></form></main>')
            elif self.path == "/go":
                self.send_response(302)
                self.send_header("Location", f"http://localhost:{self.server.server_port}/who")
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            for k, v in extra:
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body.encode())

        def log_message(self, *a):
            pass
    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv.server_port
    srv.shutdown()


async def allow_all(url):
    return True


@pytest.fixture
async def browser(tmp_path):
    b = Browser(tmp_path / "profile", BIN, policy=allow_all, ip_ok=lambda ip: True)
    yield b
    await b.close()


def text(page):
    return " ".join(page.text.split())


@chrome
async def test_background_tabs_have_no_cookies(browser, site):
    await browser.open("chat", f"http://127.0.0.1:{site}/set")
    assert "cookie: sid=abc" in text(await browser.open("chat2", f"http://127.0.0.1:{site}/who"))
    assert "cookie: none" in text(await browser.open("bg", f"http://127.0.0.1:{site}/who", isolated=True))
    await browser.open("bg", f"http://127.0.0.1:{site}/set")  # an isolated tab's own cookies stay in it
    await browser.close_tab("bg")
    assert "cookie: none" in text(await browser.open("bg2", f"http://127.0.0.1:{site}/who", isolated=True))


@chrome
async def test_sign_out_one_site_keeps_the_others(browser, site):
    await browser.open("a", f"http://127.0.0.1:{site}/set")
    await browser.open("b", f"http://localhost:{site}/set")
    await browser.sign_out(["127.0.0.1"])
    assert "cookie: none" in text(await browser.open("a", f"http://127.0.0.1:{site}/who"))
    assert "cookie: sid=abc" in text(await browser.open("b", f"http://localhost:{site}/who"))


@chrome
async def test_turning_off_signs_out_of_everything(browser, site):
    await browser.open("a", f"http://127.0.0.1:{site}/set")
    await browser.open("b", f"http://localhost:{site}/set")
    await browser.sign_out(None)
    assert "cookie: none" in text(await browser.open("a", f"http://127.0.0.1:{site}/who"))
    assert "cookie: none" in text(await browser.open("b", f"http://localhost:{site}/who"))


@chrome
async def test_a_held_tab_refuses_tools(browser, site):
    await browser.open("chat", f"http://127.0.0.1:{site}/who")
    browser.hold("chat", "phone-1")
    assert browser.held_by("chat") == "phone-1"
    with pytest.raises(BrowserError, match="The user is using the browser"):
        await browser.open("chat", f"http://127.0.0.1:{site}/set")
    with pytest.raises(BrowserError, match="The user is using the browser"):
        await browser.scroll("chat")
    browser.release("chat")
    assert (await browser.open("chat", f"http://127.0.0.1:{site}/who")).title == "who"


@chrome
async def test_a_upi_launch_is_caught(browser, site):
    import asyncio
    caught = []
    browser.on_upi(lambda tab, url: caught.append((tab, url)))
    await browser.open("chat", f"http://127.0.0.1:{site}/pay")
    s = await browser._session("chat", False)
    for el in ("a1", "a2", "b2"):
        await browser._eval(s, f"document.getElementById('{el}').click()")
        await asyncio.sleep(0.8)
    urls = [u for _, u in caught]
    assert urls[0] == "upi://pay?pa=shop@okaxis&am=499.00&tr=ORDER1"
    assert "upi://pay?pa=shop@okaxis&am=499.00" in urls  # the intent:// link, as the upi:// link it carries
    assert "upi://pay?pa=shop@okaxis&am=2.00" in urls and all(t == "chat" for t, _ in caught)
    assert browser.take_upi("chat") == urls[-1] and browser.take_upi("chat") is None


def test_upi_link():
    assert upi_link("upi://pay?pa=a@ybl&am=1") == "upi://pay?pa=a@ybl&am=1"
    assert upi_link("intent://pay?pa=a@ybl&am=1#Intent;scheme=upi;package=x;end") == "upi://pay?pa=a@ybl&am=1"
    assert upi_link("intent://maps?q=x#Intent;scheme=geo;end") is None
    assert upi_link("https://shop.example/pay") is None


@chrome
async def test_page_text_is_masked(browser, site, isolated_settings, tmp_path):
    from odie.agent.tools.browser import make_browser_tools
    from odie.store.db import Store
    st = Store(tmp_path / "a.db")
    st.init_schema()
    tools = {t.name: t for t in make_browser_tools(st, browser_for=lambda: browser)}
    out = await tools["browser_open"].run_async(args={"url": f"http://127.0.0.1:{site}/card"},
                                                tool_context=SimpleNamespace(session=SimpleNamespace(id="chat-2026-10-08")))
    body = out["result"]
    assert "4111 1111 1111 1111" not in body and "•••• 1111" in body and "••••6789" in body
    assert "402-7731234-1234567" in body and "411001" in body  # not card or account numbers: kept


@chrome
async def test_codes_pins_and_expiry_are_never_typed(browser, site):
    await browser.open("chat", f"http://127.0.0.1:{site}/codes")
    for field in ("Enter the code we sent", "MM / YY", "UPI PIN", "Enter OTP"):
        with pytest.raises(BrowserError, match="never type"):
            await browser.type("chat", field, "123456", submit=False)
    await browser.type("chat", "Email", "asha@example.com", submit=False)


@chrome
async def test_a_fenced_tab_stays_on_its_sites(browser, site):
    """In a private chat a step may take the tab only to the chat's signed-in sites (and the page it's on): a planted
    link, a same-site redirect or a form that posts elsewhere is stopped, and says how to ask."""
    links = f"http://127.0.0.1:{site}/links"
    await browser.open("chat", links)
    browser.fence("chat", {"127.0.0.1"})
    with pytest.raises(BrowserError, match="localhost"):
        await browser.click("chat", "Continue")
    await browser.open("chat", links)
    with pytest.raises(BrowserError, match="localhost"):
        await browser.open("chat", f"http://127.0.0.1:{site}/go")
    await browser.open("chat", links)
    with pytest.raises(BrowserError, match="localhost"):
        await browser.type("chat", "Notes", "order 402-77", submit=True)
    assert (await browser.open("chat", links)).title == "links"  # the signed-in site itself stays open
    browser.fence("chat", None)
    assert (await browser.open("chat", f"http://localhost:{site}/who")).title == "who"


@chrome
async def test_sign_out_clears_site_storage(browser, site):
    """Signing out of a site clears the storage of the origins it was seen on (a token in localStorage survives
    cookie deletion); signing out of everything leaves no storage anywhere."""
    a, b = f"http://127.0.0.1:{site}", f"http://localhost:{site}"

    async def token(origin, put=False):
        await browser.open("t", f"{origin}/who")
        s = await browser._session("t", False)
        if put:
            await browser._eval(s, "localStorage.setItem('token', 'abc')")
        return await browser._eval(s, "localStorage.getItem('token')")
    assert await token(a, put=True) == "abc" and await token(b, put=True) == "abc"
    await browser.sign_out(["127.0.0.1"], origins=[a])
    assert await token(a) is None and await token(b) == "abc"  # the other site keeps its session
    await browser.sign_out(None)
    assert await token(b) is None


def test_only_real_origins_are_cleared():
    from odie.browser.engine import _origin_ok
    assert _origin_ok("https://www.amazon.in") and _origin_ok("http://127.0.0.1:8011") and _origin_ok("http://localhost:5173")
    assert not _origin_ok("http://www.127.0.0.1")  # Chrome reads it as every site
    assert not _origin_ok("https://") and not _origin_ok("javascript:alert(1)") and not _origin_ok("https://a.in/path")


@chrome
async def test_the_reader_sees_a_sign_in_form(browser, site):
    assert (await browser.open("chat", f"http://127.0.0.1:{site}/codes")).login is False
    page = await browser.open("chat", f"http://127.0.0.1:{site}/login")
    assert page.login is True
