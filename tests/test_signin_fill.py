"""The engine fills a login itself (spec "Sign in for me", Part 2), on local pages: one step, two steps, a code step
and a wrong password; and it types nothing for a lookalike site, a form posting elsewhere, plain http or a sign-up."""
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from odie.browser import find
from odie.browser.engine import Browser

BIN = find.installed()
chrome = pytest.mark.skipif(BIN is None, reason="no Chrome, Edge, Chromium or Brave here")
USER, PW, CODE = "asha@example.com", "right pw ₹", "123456"  # an email: the two-step page's field is type=email


def form(action, *fields, title="Log in", button="Log in"):
    return (f'<!doctype html><title>{title}</title><main><form method="post" action="{action}">' + "".join(fields)
            + f'<button type="submit">{button}</button></form></main>')


OFFSITE: list = []
USERF = '<label>Email<input name="username" autocomplete="username"></label>'
PASSF = '<label>Password<input type="password" name="password" autocomplete="current-password"></label>'


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
            pages = {
                "/one": form("/session", USERF, PASSF),
                "/two": form("/two/next", '<label>Email or mobile<input type="email" name="email"></label>', title="Sign in", button="Continue"),
                "/code-login": form("/code-session", USERF, PASSF),
                "/offsite": form(f"http://localhost:{port}/session", USERF, PASSF),
                "/signup": form("/session", USERF, '<label>New password<input type="password" autocomplete="new-password"></label>', title="Sign up"),
                "/account": f'<!doctype html><title>Account</title><main><p>cookie: {self.headers.get("Cookie") or "none"}</p></main>',
                "/slow-links": '<!doctype html><title>Links</title><main><a href="/slow-out"><i>Log</i> out</a></main>',
                "/bye": "<!doctype html><title>Bye</title><main><p>signed out</p></main>",
                "/slow-login": form("/slow-session", USERF, PASSF),
                "/base": f'<base href="http://localhost:{port}/">' + form("session", USERF, PASSF),
                "/formaction": form("/session", USERF, PASSF).replace('<button type="submit">', f'<button type="submit" formaction="http://localhost:{port}/session">'),
                "/scripted": form("/session", USERF, PASSF) + f'<script>document.forms[0].addEventListener("submit", (e) => {{ e.target.action = "http://localhost:{port}/session"; }});</script>',
                "/account/close": form("/close", PASSF, title="Close your account", button="Close account"),
                "/two-nopass": form("/two/sent", '<label>Email<input type="email" name="email"></label>', title="Sign in", button="Continue"),
                "/shifty": ('<!doctype html><title>Shifty</title><main><div id="top"></div><a href="/bye">Log out</a></main><script>'
                            'addEventListener("mousemove", () => { if (!window.moved) { window.moved = 1; '
                            'document.getElementById("top").style.height = "300px"; } }, true);</script>'),
            }
            if self.path == "/slow-out":  # a slow site: the answer comes seconds after the click
                import time
                time.sleep(2.5)
                return self.page("", status=303, location="/bye")
            self.page(pages.get(self.path.split("?")[0], "<title>t</title><p>x</p>"))

        def do_POST(self):
            data = urllib.parse.parse_qs(self.rfile.read(int(self.headers.get("Content-Length", 0))).decode())
            if self.headers.get("Host", "").startswith("localhost"):
                OFFSITE.append(self.path)  # a login that reached the other site
            if self.path == "/two/sent":
                return self.page("<!doctype html><title>Check your email</title><main><p>We sent you a link.</p></main>")
            got = lambda k: data.get(k, [""])[0]  # noqa: E731
            if self.path == "/two/next":
                self.page(form("/session", f'<input type="hidden" name="username" value="{got("email")}">', PASSF, title="Sign in"))
            elif self.path == "/slow-session" and got("username") == USER and got("password") == PW:
                import time
                time.sleep(6)  # longer than the old fixed waits (3 s, then 5 s)
                self.page("", cookie="sid=ok; Path=/", status=303, location="/account")
            elif self.path in ("/session", "/code-session") and got("username") == USER and got("password") == PW:
                if self.path == "/code-session":
                    self.page(form("/verify", '<label>Enter the code<input name="otp" autocomplete="one-time-code"></label>', title="Verify", button="Verify"))
                else:
                    self.page("", cookie="sid=ok; Path=/", status=303, location="/account")
            elif self.path == "/verify" and got("otp") == CODE:
                self.page("", cookie="sid=ok; Path=/", status=303, location="/account")
            else:
                self.page(form("/session", USERF, PASSF) + "<p>Wrong password</p>")

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


async def typed(browser, tab):
    s = await browser._session(tab, False)
    return await browser._eval(s, "[...document.querySelectorAll('input')].map(i => i.value).join('')")


@chrome
async def test_a_one_step_login(browser, site):
    page = await browser.open("chat", f"http://127.0.0.1:{site}/one")
    assert page.signin
    assert await browser.sign_in("chat", "127.0.0.1", USER, PW) == {"status": "signed_in"}
    assert "cookie: sid=ok" in (await browser.look("chat")).text


@chrome
async def test_a_two_step_login(browser, site):
    assert (await browser.open("chat", f"http://127.0.0.1:{site}/two")).signin  # no password field yet
    assert await browser.sign_in("chat", "127.0.0.1", USER, PW) == {"status": "signed_in"}


@chrome
async def test_a_code_step(browser, site):
    await browser.open("chat", f"http://127.0.0.1:{site}/code-login")
    assert await browser.sign_in("chat", "127.0.0.1", USER, PW) == {"status": "code"}
    assert await browser.enter_code("chat", "127.0.0.1", CODE) == {"status": "signed_in"}


@chrome
async def test_a_wrong_password(browser, site):
    await browser.open("chat", f"http://127.0.0.1:{site}/one")
    assert await browser.sign_in("chat", "127.0.0.1", USER, "wrong") == {"status": "failed"}


@chrome
async def test_a_lookalike_gets_nothing(browser, site):
    await browser.open("chat", f"http://localhost:{site}/one")  # saved for 127.0.0.1; this page is another site
    assert await browser.sign_in("chat", "127.0.0.1", USER, PW) == {"status": "wrong_site"}
    assert await typed(browser, "chat") == ""


@chrome
async def test_a_form_posting_elsewhere_gets_nothing(browser, site):
    await browser.open("chat", f"http://127.0.0.1:{site}/offsite")
    assert await browser.sign_in("chat", "127.0.0.1", USER, PW) == {"status": "wrong_site"}
    assert await typed(browser, "chat") == ""


@chrome
async def test_a_sign_up_form_is_never_filled(browser, site):
    await browser.open("chat", f"http://127.0.0.1:{site}/signup")
    assert await browser.sign_in("chat", "127.0.0.1", USER, PW) == {"status": "failed"}
    assert await typed(browser, "chat") == ""


@chrome
async def test_plain_http_is_refused(tmp_path, site):
    b = Browser(tmp_path / "profile", BIN, policy=allow_all, ip_ok=lambda ip: True)  # the real setting: https only
    try:
        await b.open("chat", f"http://127.0.0.1:{site}/one")
        assert await b.sign_in("chat", "127.0.0.1", USER, PW) == {"status": "wrong_site"}
        assert await typed(b, "chat") == ""
    finally:
        await b.close()


@chrome
async def test_ordinary_pages_are_not_sign_in_pages(browser, site):
    assert not (await browser.open("chat", f"http://127.0.0.1:{site}/account")).signin


@chrome
async def test_a_click_waits_for_a_slow_page(browser, site):
    """Found live: on a slow site the click read the old page, and the model's next step cancelled the logout still
    in flight. A click that starts a navigation waits for it."""
    await browser.open("chat", f"http://127.0.0.1:{site}/slow-links")
    page = await browser.click("chat", "Log out")
    assert page.title == "Bye" and page.url.endswith("/bye")


@chrome
async def test_a_slow_sign_in_is_not_a_failure(browser, site):
    await browser.open("chat", f"http://127.0.0.1:{site}/slow-login")
    assert await browser.sign_in("chat", "127.0.0.1", USER, PW) == {"status": "signed_in"}


@chrome
async def test_a_click_that_misses_still_clicks(browser, site):
    """Found live: a click sometimes missed (the page shifted between finding the link and pressing it, as a banner
    came in), and the logout never happened. A click that didn't reach its element is sent to it directly."""
    await browser.open("chat", f"http://127.0.0.1:{site}/shifty")
    page = await browser.click("chat", "Log out")
    assert page.title == "Bye"


@chrome
@pytest.mark.parametrize("path", ["/base", "/formaction"])
async def test_a_form_sent_elsewhere_by_html_gets_nothing(browser, site, path):
    """From the review: a <base href> or a button's formaction sends a same-looking form to another site."""
    await browser.open("chat", f"http://127.0.0.1:{site}{path}")
    assert await browser.sign_in("chat", "127.0.0.1", USER, PW) == {"status": "wrong_site"}
    assert await typed(browser, "chat") == ""


@chrome
async def test_a_form_rewritten_on_submit_never_leaves(browser, site):
    """A script changes the form's action as it's sent: the fill keeps the tab on the login's site, so it's stopped."""
    from odie.browser.engine import BrowserError
    OFFSITE.clear()
    await browser.open("chat", f"http://127.0.0.1:{site}/scripted")
    try:
        got = await browser.sign_in("chat", "127.0.0.1", USER, PW)
        assert got["status"] != "signed_in"
    except BrowserError:
        pass
    assert OFFSITE == []


@chrome
async def test_a_password_prompt_isnt_a_sign_in_page(browser, site):
    """From the review: "confirm with your password" on a signed-in site must never get the saved login by itself."""
    page = await browser.open("chat", f"http://127.0.0.1:{site}/account/close")
    assert page.login and not page.signin


@chrome
async def test_no_password_step_is_no_sign_in(browser, site):
    """From the review: a two-step flow that ends without a password ("we emailed you a link") isn't signed in."""
    await browser.open("chat", f"http://127.0.0.1:{site}/two-nopass")
    assert await browser.sign_in("chat", "127.0.0.1", USER, PW) == {"status": "failed"}
