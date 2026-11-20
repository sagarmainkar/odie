"""Saved cards (Settings → Vault → Cards): kept in a keychain (a throwaway one here), listed as "Visa •••• 4242" without
the number, and typed into a payment page by the engine only from the live view; never the CVV."""
import json
import subprocess
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from odie.signin import live, wallet
from odie.store.db import Store

NOW = datetime(2026, 11, 20, 14, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
VISA = "4242 4242 4242 4242"


@pytest.fixture
def store(isolated_settings, tmp_path):
    s = Store(tmp_path / "a.db")
    s.init_schema()
    return s


def test_a_card_is_saved_read_and_listed_without_its_number(store, keychain):
    got = wallet.save(store, VISA, "03/29", "Asha Rao", "", NOW)
    listed = wallet.listing(store)
    assert listed == [{"id": got["id"], "label": "Visa •••• 4242", "brand": "Visa", "last4": "4242", "expiry": "03/29",
                       "saved_at": "2026-11-20T14:00:00+05:30", "last_used": None}]
    assert wallet.get(store, got["id"]) == {"number": "4242424242424242", "month": 3, "year": 2029, "name": "Asha Rao"}
    assert "42424242" not in json.dumps(store.get_setting(wallet.KEY)) and "Asha" not in json.dumps(listed)
    raw = subprocess.run(["security", "find-generic-password", "-s", wallet.SERVICE, "-a", got["id"], "-w", str(keychain)],
                         capture_output=True, text=True).stdout
    assert raw.startswith("b64:") and "4242" not in raw


def test_its_own_label_and_brands(store, keychain):
    assert wallet.save(store, "5555555555554444", "1/2030", "", "Office card", NOW)["label"] == "Office card"
    assert wallet.brand("378282246310005") == "Amex" and wallet.brand("6521000000000001") == "RuPay"
    assert wallet.brand("5105105105105100") == "Mastercard" and wallet.brand("4111111111111111") == "Visa"


@pytest.mark.parametrize("number, expiry, why", [
    ("4242 4242 4242 4241", "03/29", "That card number doesn't look right."),  # fails the Luhn check
    ("1234", "03/29", "That card number doesn't look right."),
    (VISA, "13/29", "Type the expiry as MM/YY, for example 03/29."),
    (VISA, "march", "Type the expiry as MM/YY, for example 03/29."),
])
def test_a_wrong_card_is_refused(store, keychain, number, expiry, why):
    with pytest.raises(ValueError, match=why.replace("(", r"\(").replace(")", r"\)")):
        wallet.save(store, number, expiry, "", "", NOW)
    assert wallet.listing(store) == []


def test_a_cvv_is_never_asked_for():
    import inspect
    assert "cvv" not in inspect.signature(wallet.save).parameters


def test_delete_removes_it_from_the_keychain(store, keychain):
    got = wallet.save(store, VISA, "03/29", "", "", NOW)
    assert wallet.delete(store, got["id"]) is True and wallet.listing(store) == []
    assert wallet.delete(store, got["id"]) is False
    assert wallet.get(store, got["id"]) is None


def test_the_live_view_passes_a_card_pick_and_nothing_else():
    assert live.clean({"t": "card", "id": "a1b2c3d4"}) == {"t": "card", "id": "a1b2c3d4"}
    assert live.clean({"t": "card", "id": "../x"}) is None
    assert live.clean({"t": "card", "number": "4242424242424242"}) is None


# ── the engine: typing a saved card (live view only), finding usernames that aren't emails, seeing Google/Apple ──
import threading  # noqa: E402
import urllib.parse  # noqa: E402
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer  # noqa: E402

from odie.browser import find  # noqa: E402
from odie.browser.engine import Browser, BrowserError  # noqa: E402

BIN = find.installed()
chrome = pytest.mark.skipif(BIN is None, reason="no Chrome, Edge, Chromium or Brave here")
CARD = {"number": "4242424242424242", "month": 3, "year": 2029, "name": "Asha Rao"}
CVV = '<label>CVV<input name="cvv" autocomplete="cc-csc"></label>'
PAY = ('<label>Card number<input name="cardnumber" autocomplete="cc-number"></label>'
       '<label>Expiry (MM/YY)<input name="exp" autocomplete="cc-exp"></label>'
       '<label>Name on card<input name="ccname"></label>' + CVV)
SELECTS = ('<label>Debit card number<input id="card_no"></label>'
           '<label>Expiry month<select id="m"><option value="">Month</option><option value="02">02</option><option value="03">03</option></select></label>'
           '<label>Expiry year<select id="y"><option>Year</option><option>2028</option><option>2029</option></select></label>' + CVV)
PASSF = '<label>Password<input type="password" name="password"></label>'
LOGINS: list = []


def page(title, body):
    return f'<!doctype html><title>{title}</title><main><form method="post" action="/session">{body}<button type="submit">Go</button></form></main>'


@pytest.fixture
def site():
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            port = self.server.server_port
            pages = {
                "/pay": page("Pay", PAY),
                "/selects": page("Pay", SELECTS),
                "/framed": f'<!doctype html><title>Pay</title><main><p>Pay ₹499</p><iframe src="http://localhost:{port}/pay" width=600 height=400></iframe></main>',
                "/consumer": page("Login", '<label>Consumer No.<input name="consumerNo"></label>' + PASSF),
                "/plain": page("Login", '<input name="txt1"><label>Enter captcha<input name="captcha"></label>' + PASSF),
                "/social": '<!doctype html><title>Log in</title><main><button>Continue with Google</button><button>Sign in with Apple</button></main>',
                "/email-google": '<!doctype html><title>Log in</title><main><form method="post" action="/next"><label>Email<input type="email" name="email"></label><button>Continue</button></form><button>Continue with Google</button></main>',
                "/aspnet": page("Login", '<input name="txtUid" placeholder="Enter ID">' + PASSF + '<label><input type="checkbox" name="keep"> Remember login</label><input type="submit" id="btnLogin" value="Login">'),
                "/shifting": page("Pay", '<label>Card number<input name="cardnumber" autocomplete="cc-number" oninput="if (!window.shown) { window.shown = 1; '
                                  'const n = document.createElement(\'label\'); n.innerHTML = \'Card holder<input name=holder>\'; this.parentNode.after(n); }"></label>'
                                  '<label>Expiry (MM/YY)<input name="exp" autocomplete="cc-exp"></label>' + CVV),
                "/quickpay": page("View and pay your bill", '<label>Consumer No.<input name="consumerNo" value="170000000001"></label>'
                                  '<label>Enter captcha<input name="captcha"></label>'),
                "/shop": '<!doctype html><title>Shop</title><main><p>Things</p><button>Continue with Google</button></main>',
            }
            body = pages.get(self.path.split("?")[0], "<title>t</title><p>x</p>")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(body.encode())

        def do_POST(self):
            data = urllib.parse.parse_qs(self.rfile.read(int(self.headers.get("Content-Length", 0))).decode())
            LOGINS.append({k: v[0] for k, v in data.items()})
            self.send_response(303)
            self.send_header("Location", "/account")
            self.end_headers()

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


async def go_live(b, tab):
    async def nothing(*a):
        return None
    b.hold(tab, "phone-1")
    await b.live_start(tab, 390, 844, nothing, nothing)


async def values(b, tab, session=None):
    s = session or b._tabs[tab]
    return await b._eval(s, "Object.fromEntries([...document.querySelectorAll('input, select')].map(i => [i.name || i.id, i.value]))")


@chrome
async def test_a_card_is_typed_but_never_the_cvv(browser, site):
    await browser.open("chat", f"http://127.0.0.1:{site}/pay")
    await go_live(browser, "chat")
    got = await browser.fill_card("chat", CARD)
    assert got["filled"] == ["expiry", "name", "number"]
    assert await values(browser, "chat") == {"cardnumber": "4242424242424242", "exp": "03/29", "ccname": "Asha Rao", "cvv": ""}


@chrome
async def test_month_and_year_lists(browser, site):
    await browser.open("chat", f"http://127.0.0.1:{site}/selects")
    await go_live(browser, "chat")
    assert (await browser.fill_card("chat", CARD))["filled"] == ["month", "number", "year"]
    assert await values(browser, "chat") == {"card_no": "4242424242424242", "m": "03", "y": "2029", "cvv": ""}


@chrome
async def test_a_card_box_from_the_payment_gateway_frame(browser, site):
    await browser.open("chat", f"http://127.0.0.1:{site}/framed")  # the card form is another site's frame, as Razorpay's
    await go_live(browser, "chat")
    assert (await browser.fill_card("chat", CARD))["filled"] == ["expiry", "name", "number"]


@chrome
async def test_no_card_form_types_nothing(browser, site):
    await browser.open("chat", f"http://127.0.0.1:{site}/consumer")
    await go_live(browser, "chat")
    assert (await browser.fill_card("chat", CARD))["filled"] == []
    assert (await values(browser, "chat"))["consumerNo"] == ""


@chrome
async def test_only_in_the_live_view(browser, site):
    await browser.open("chat", f"http://127.0.0.1:{site}/pay")  # Odie's own turn: never
    with pytest.raises(BrowserError):
        await browser.fill_card("chat", CARD)


@chrome
async def test_plain_http_gets_no_card(tmp_path, site):
    b = Browser(tmp_path / "profile", BIN, policy=allow_all, ip_ok=lambda ip: True)  # the real setting: https only
    try:
        await b.open("chat", f"http://127.0.0.1:{site}/pay")
        await go_live(b, "chat")
        assert (await b.fill_card("chat", CARD))["filled"] == []
    finally:
        await b.close()


@chrome
async def test_a_username_that_isnt_an_email(browser, site):
    LOGINS.clear()
    assert (await browser.open("chat", f"http://127.0.0.1:{site}/consumer")).signin
    await browser.sign_in("chat", "127.0.0.1", "asha_rao7", "pw")
    assert LOGINS[-1] == {"consumerNo": "asha_rao7", "password": "pw"}


@chrome
async def test_an_unlabelled_username_box_before_the_password(browser, site):
    LOGINS.clear()
    await browser.open("chat", f"http://127.0.0.1:{site}/plain")
    await browser.sign_in("chat", "127.0.0.1", "asha_rao7", "pw")
    assert LOGINS[-1]["txt1"] == "asha_rao7" and LOGINS[-1].get("captcha", "") == ""


@chrome
async def test_google_and_apple_buttons_on_a_sign_in_page(browser, site):
    p = await browser.open("chat", f"http://127.0.0.1:{site}/social")
    assert p.social and p.signin
    assert not (await browser.open("chat", f"http://127.0.0.1:{site}/shop")).social  # a shop page's one-tap button isn't a sign-in page


@chrome
async def test_an_email_first_page_with_a_google_button_keeps_the_sign_in_box(browser, site):
    p = await browser.open("chat", f"http://127.0.0.1:{site}/email-google")
    assert p.signin and not p.social  # Odie can still fill the email: the ordinary Sign in card


@chrome
async def test_a_login_button_or_checkbox_is_never_the_username_box(browser, site):
    LOGINS.clear()
    await browser.open("chat", f"http://127.0.0.1:{site}/aspnet")
    await browser.sign_in("chat", "127.0.0.1", "asha_rao7", "pw")
    assert LOGINS[-1]["txtUid"] == "asha_rao7"


@chrome
async def test_a_form_that_grows_while_typing_still_gets_the_right_boxes(browser, site):
    await browser.open("chat", f"http://127.0.0.1:{site}/shifting")
    await go_live(browser, "chat")
    await browser.fill_card("chat", CARD)
    got = await values(browser, "chat")
    assert got["exp"] == "03/29" and got["cvv"] == "" and got["cardnumber"] == "4242424242424242"


@chrome
async def test_a_click_past_the_page_edge_lands_on_the_page(browser, site):
    """The desk's page view can send a click from a picture of the old size (right after Take control): Chrome refused
    it with "Position out of bounds". It lands at the edge instead."""
    await browser.open("chat", f"http://127.0.0.1:{site}/pay")
    await go_live(browser, "chat")
    await browser.live_input("chat", {"t": "tap", "x": 5000, "y": 5000})
    await browser.live_input("chat", {"t": "drag", "x0": 200, "y0": 700, "x1": 200, "y1": 9000})


@chrome
async def test_a_pay_page_without_a_sign_in_form_gets_nothing_typed(browser, site):
    """Found live: the Sign in box on a utility's no-login pay page typed the username into Consumer No. (no password
    box, so "failed"). A page with no sign-in form gets nothing, and the box offers the page instead."""
    await browser.open("chat", f"http://127.0.0.1:{site}/quickpay")
    assert await browser.sign_in("chat", "127.0.0.1", "asha_rao7", "pw") == {"status": "no_form"}
    assert (await values(browser, "chat"))["consumerNo"] == "170000000001"
    assert await browser.has_login_form("chat") is False
    await browser.open("chat", f"http://127.0.0.1:{site}/consumer")
    assert await browser.has_login_form("chat") is True
