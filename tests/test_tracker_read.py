"""A signed-in tracker reads its one page (spec 2026-10-08-odie-signed-in-trackers-design.md, Part 2), on local pages in
real Chrome: it signs in with the saved login when asked, comes back to the page asked for, scrolls and reads, never
clicks, stops when the page leaves the site, and always closes its tab."""
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from odie.browser import find
from odie.browser.engine import Browser
from odie.trackers import signed_in

BIN = find.installed()
chrome = pytest.mark.skipif(BIN is None, reason="no Chrome, Edge, Chromium or Brave here")
USER, PW = "someone@example.com", "right pw ₹"
CLICKED: list = []
FILLER = "<p>" + "Order placed 2 October. " * 20 + "</p>"


@pytest.fixture
def site():
    class H(BaseHTTPRequestHandler):
        def page(self, body, cookie=None, status=200, location=None):
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            if cookie:
                self.send_header("Set-Cookie", cookie)
            if location:
                self.send_header("Location", location)
            self.end_headers()
            self.wfile.write(body.encode())

        def do_GET(self):
            port = self.server.server_port
            signed = "sid=ok" in (self.headers.get("Cookie") or "")
            path = self.path.split("?")[0]
            if path == "/orders":
                if not signed:
                    return self.page("", status=303, location="/signin")
                return self.page(f"<!doctype html><title>Your Orders</title><main><h1>Your Orders</h1>{FILLER}<p>Refund of ₹1,299 issued</p></main>")
            if path == "/signin":
                return self.page('<!doctype html><title>Sign in</title><main><form method="post" action="/session">'
                                 '<label>Email<input name="username" autocomplete="username"></label>'
                                 '<label>Password<input type="password" name="password" autocomplete="current-password"></label>'
                                 '<button type="submit">Sign in</button></form></main>')
            if path == "/long":
                return self.page(f'<!doctype html><title>Long</title><main id="m">{FILLER}</main><div style="height:4000px"></div>'
                                 '<script>let n = 0; addEventListener("scroll", () => { if (n < 3) { n++; document.getElementById("m")'
                                 '.insertAdjacentHTML("beforeend", "<p>More item " + n + " " + "x".repeat(200) + "</p>"); } });</script>')
            if path == "/button":
                return self.page(f'<!doctype html><title>Deal</title><main>{FILLER}<button onclick="fetch(\'/clicked\')">Buy now</button></main>')
            if path == "/settings":
                return self.page(f'<!doctype html><title>Account settings</title><main>{FILLER}<form method="post" action="/close">'
                                 '<label>Confirm your password<input type="password" name="password" autocomplete="current-password"></label>'
                                 '<button type="submit">Save</button></form></main>')
            if path == "/clicked":
                CLICKED.append(self.path)
                return self.page("ok")
            if path == "/away":
                return self.page("", status=302, location=f"http://localhost:{port}/x")
            self.page(f"<!doctype html><title>Home</title><main><p>Home</p>{FILLER}</main>")  # "/": where sign-in lands

        def do_POST(self):
            data = urllib.parse.parse_qs(self.rfile.read(int(self.headers.get("Content-Length", 0))).decode())
            if data.get("username", [""])[0] == USER and data.get("password", [""])[0] == PW:
                return self.page("", cookie="sid=ok; Path=/", status=303, location="/")  # lands on the home page, not the orders
            self.page("<!doctype html><title>Sign in</title><main><form method=\"post\" action=\"/session\">"
                      "<label>Email<input name=\"username\" autocomplete=\"username\"></label>"
                      "<label>Password<input type=\"password\" name=\"password\" autocomplete=\"current-password\"></label>"
                      "<button type=\"submit\">Sign in</button></form><p>Wrong password</p></main>")

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
    b = Browser(tmp_path / "profile", BIN, policy=allow_all, ip_ok=lambda ip: True, plain_http_ok=True)
    yield b
    await b.close()


def row(port, path="/orders"):
    return {"id": 1, "page_url": f"http://127.0.0.1:{port}{path}"}


def no_login():
    raise AssertionError("no login should be needed")


@chrome
async def test_it_signs_in_and_reads_the_page_asked_for(browser, site):
    got = await signed_in.read(browser, row(site), lambda: (USER, PW))
    assert got["status"] == "ok" and got["signed_in"] and "Refund of ₹1,299 issued" in got["text"]  # not the home page
    assert "tracker-1" not in browser._tabs


@chrome
async def test_the_cookie_is_enough_next_time(browser, site):
    assert (await signed_in.read(browser, row(site), lambda: (USER, PW)))["status"] == "ok"
    got = await signed_in.read(browser, row(site), no_login)
    assert got["status"] == "ok" and not got["signed_in"]


@chrome
async def test_no_saved_login_or_a_wrong_one_is_stuck(browser, site):
    assert (await signed_in.read(browser, row(site), lambda: None))["status"] == "signin"
    assert (await signed_in.read(browser, row(site), lambda: (USER, "nope")))["status"] == "failed"


@chrome
async def test_a_locked_vault_is_stuck(browser, site):
    from odie.signin.vault import VaultError

    def locked():
        raise VaultError("Odie couldn't open its vault on the Mac.")
    assert (await signed_in.read(browser, row(site), locked))["status"] == "vault"


@chrome
async def test_a_long_page_is_scrolled_and_read(browser, site):
    got = await signed_in.read(browser, row(site, "/long"), no_login)
    assert got["status"] == "ok" and "More item 1" in got["text"]


@chrome
async def test_the_page_is_never_clicked(browser, site):
    CLICKED.clear()
    got = await signed_in.read(browser, row(site, "/button"), no_login)
    assert got["status"] == "ok" and "Buy now" in got["text"] and CLICKED == []


@chrome
async def test_leaving_the_site_is_stuck(browser, site):
    got = await signed_in.read(browser, row(site, "/away"), no_login)
    assert got["status"] == "left" and "tracker-1" not in browser._tabs


@chrome
async def test_a_password_prompt_that_isnt_a_sign_in_page_gets_nothing(browser, site):
    """A "confirm your password" prompt on the site (a settings page): never the saved login, with nobody watching."""
    got = await signed_in.read(browser, row(site, "/settings"), no_login)
    assert got["status"] == "signin" and "tracker-1" not in browser._tabs
