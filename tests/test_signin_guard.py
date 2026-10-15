"""The private-turn guard (spec Part 3): after a signed-in page is read, anything that would leave for another site asks
first (code-written cards show what would leave); consequential clicks and submits on a signed-in site always ask;
nothing asks while the switch is off; private turns never feed the memory review, and their typed text isn't audited."""
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from odie.agent import turn
from odie.signin import guard, sites, state
from odie.store.db import Store

NOW = datetime(2026, 10, 8, 9, 0, tzinfo=ZoneInfo("Asia/Kolkata"))


@pytest.fixture
def store(isolated_settings, tmp_path):
    s = Store(tmp_path / "a.db")
    s.init_schema()
    state.turn_on(s, accepted=True, version=state.VERSION, now=NOW)
    sites.record(s, "amazon.in", NOW)
    return s


@pytest.fixture
def private():
    token = turn.PRIVATE.set(set())
    yield turn.PRIVATE.get()
    turn.PRIVATE.reset(token)


def test_a_private_turn_asks_before_anything_leaves(store, private):
    assert not guard.query_needs_tap(store) and not guard.url_needs_tap(store, "https://evil.example/x?d=1")
    private.add("amazon.in")  # a signed-in page was read this turn
    assert guard.query_needs_tap(store)
    assert guard.url_needs_tap(store, "https://evil.example/x?orders=402-77")
    assert not guard.url_needs_tap(store, "https://www.amazon.in/gp/your-orders")  # the same site stays free
    state.turn_off(store)
    assert not guard.query_needs_tap(store)  # nothing is signed in while it's off


def test_outside_a_chat_turn_nothing_is_private(store):
    assert turn.PRIVATE.get() is None and not guard.query_needs_tap(store)


@pytest.mark.parametrize("words,asks", [
    ("Place order", True), ("Place your order", True), ("Pay ₹499", True), ("Book now", True), ("Proceed to Pay", True),
    ("Confirm booking", True), ("Send", True), ("Delete address", True), ("Cancel order", True),
    ("See all buying options", False), ("Next", False), ("Add to cart", False), ("Paytm offers", False),
])
def test_consequential_clicks_ask_on_signed_in_sites(store, words, asks):
    guard.LAST_URL["chat-1"] = "https://www.amazon.in/cart"
    assert guard.click_needs_tap(store, "chat-1", words) is asks
    guard.LAST_URL["chat-1"] = "https://www.flipkart.com/cart"  # not signed in there
    assert guard.click_needs_tap(store, "chat-1", words) is False


def test_submitting_on_a_signed_in_checkout_asks(store):
    guard.LAST_URL["chat-1"] = "https://www.amazon.in/checkout/pay"
    assert guard.type_needs_tap(store, "chat-1", "UPI ID", submit=True)
    assert not guard.type_needs_tap(store, "chat-1", "UPI ID", submit=False)
    guard.LAST_URL["chat-1"] = "https://www.amazon.in/s?k=airpods"
    assert not guard.type_needs_tap(store, "chat-1", "Search Amazon", submit=True)


def test_the_tools_carry_the_guard(store, private):
    from odie.agent.tools.browser import make_browser_tools
    from odie.agent.tools.web import make_web_tools
    web = {t.name: t for t in make_web_tools(store=store)}
    br = {t.name: t for t in make_browser_tools(store, browser_for=lambda: None)}
    for name in ("web_search", "web_fetch"):
        assert callable(web[name]._require_confirmation), name
    for name in ("browser_open", "browser_click", "browser_type", "find_images"):
        assert callable(br[name]._require_confirmation), name
    private.add("amazon.in")
    assert web["web_search"]._require_confirmation(query="order 402-77 tracking") is True
    assert web["web_fetch"]._require_confirmation(url="https://www.amazon.in/x") is True  # a fetch service, and redirects
    assert br["browser_open"]._require_confirmation(url="https://www.amazon.in/x") is False  # the signed-in site stays free


def test_a_cloud_voice_asks_in_a_private_turn(store, private, monkeypatch):
    from odie import voice
    from odie.agent.tools.media import make_media_tools
    speak = make_media_tools(store)[0]
    private.add("amazon.in")
    monkeypatch.setattr(voice, "get_tts", lambda st: ("kokoro", "af_heart"))
    assert speak._require_confirmation(script="Your order ships today.") is False  # Odie's own voice sends nothing
    monkeypatch.setattr(voice, "get_tts", lambda st: ("openai", "alloy"))
    assert speak._require_confirmation(script="Your order ships today.") is True
    private.clear()
    assert speak._require_confirmation(script="Your order ships today.") is False


def _fc(tool, args):
    return SimpleNamespace(id="adk-1", args={"originalFunctionCall": {"name": tool, "args": args}})


def test_cards_say_what_would_leave(store):
    from odie.app.runner import approval_from_confirmation
    guard.LAST_URL["chat-1"] = "https://www.amazon.in/cart"
    guard.LAST_SHOT["chat-1"] = "0123456789abcdef"
    cases = [("web_search", {"query": "order 402-77 tracking"}, "Search the web for: order 402-77 tracking"),
             ("web_fetch", {"url": "https://evil.example/x?d=1"}, "Open https://evil.example/x?d=1"),
             ("browser_open", {"url": "https://evil.example/x"}, "Open https://evil.example/x"),
             ("find_images", {"query": "my order"}, "Search for photos of: my order"),
             ("browser_click", {"text": "Place order"}, 'Click "Place order" on amazon.in'),
             ("speak", {"script": "Your order ships today."}, "Read aloud with OpenAI's voice: Your order ships today.")]
    for tool, args, summary in cases:
        a = approval_from_confirmation(_fc(tool, args), "inv", "chat-1", store)
        assert a["summary"] == summary, tool
    click = approval_from_confirmation(_fc("browser_click", {"text": "Place order"}), "inv", "chat-1", store)
    assert click["detail"]["shot"] == "0123456789abcdef"


async def test_private_turns_skip_the_memory_review(store, isolated_settings, tmp_path):
    from google.adk.events import Event
    from google.genai import types

    from odie.app.runner import OdieRunner
    r = OdieRunner(store)
    r.review_every = 1

    async def fake_run(**kw):
        turn.PRIVATE.get().add("amazon.in")  # a signed-in page read during the turn
        yield Event(author="odie", invocation_id="i", content=types.Content(role="model", parts=[types.Part(text="Your order ships today.")]))
    r.runner.run_async = fake_run
    [e async for e in r.chat("where is my order", session_id="t-1")]
    assert r._turns == [] and r._review_task is None
    await r.close()


async def test_private_typing_isnt_audited(store, private):
    from odie.agent.callbacks import OdiePlugin
    private.add("amazon.in")
    await OdiePlugin(store).after_tool_callback(tool=SimpleNamespace(name="browser_type"), tool_args={"field": "UPI ID", "text": "ashaa@okaxis"},
                                                tool_context=SimpleNamespace(), result={"result": "ok"})
    row = store.one("select args_json from audit_log where tool='browser_type' order by id desc limit 1")
    assert "okaxis" not in row["args_json"] and "12 characters" in row["args_json"]


async def test_a_resumed_turn_stays_private(store, isolated_settings):
    """A tap resumes the same turn: it keeps the turn's signed-in sites (saved with the card, so a restart keeps them
    too) and the user's words, so the next step that would leave still asks, and the browser stays signed in."""
    from google.adk.events import Event
    from google.genai import types

    from odie import config
    from odie.app.runner import OdieRunner, approval_from_confirmation
    r = OdieRunner(store)
    s = config.settings
    sid = await r._ensure_session("chat-2026-10-08")
    sess = await r.session_service.get_session(app_name=s.app_name, user_id=s.user_id, session_id=sid)
    await r.session_service.append_event(sess, Event(author="user", invocation_id="inv-1", content=types.Content(
        role="user", parts=[types.Part(text="where is my order")])))
    token = turn.PRIVATE.set({"amazon.in"})
    a = approval_from_confirmation(_fc("web_search", {"query": "order 402-77"}), "inv-1", sid, store)
    turn.PRIVATE.reset(token)
    assert a["detail"]["private"] == ["amazon.in"]
    aid = store.create_approval(sid, "inv-1", "adk-1", "web_search", {"query": "order 402-77"}, a["summary"], a["detail"], [])
    seen = {}

    async def fake_run(**kw):
        seen["private"], seen["words"] = turn.private_sites(), turn.USER_TEXT.get()
        yield SimpleNamespace(author="odie", partial=False, invocation_id="inv-1", content=types.Content(role="model", parts=[types.Part(text="Done.")]))
    r.runner.run_async = fake_run
    await r.resume_approval(aid, True)
    assert seen == {"private": {"amazon.in"}, "words": "where is my order"}
    assert turn.PRIVATE.get() is None and turn.USER_TEXT.get() is None  # only for that run
    await r.close()


async def test_signed_in_pages_are_labelled_and_offer_the_upi_id(store, private):
    """A signed-in page says whose it is; at a signed-in checkout that offers UPI, the saved UPI ID is given for a
    collect request. Neither appears on other pages."""
    from odie.agent.tools import browser as btools
    from odie.browser.engine import Page
    from tests.test_browser_tools import SHOT, FakeBrowser

    class Shop(FakeBrowser):
        def _page(self, url="", note=""):
            return Page(url=url, title="Select a payment method", text="Pay by UPI ID\nCredit or debit card", shot=SHOT, note=note)
    tools = {t.name: t for t in btools.make_browser_tools(store, browser_for=lambda: Shop())}
    ctx = SimpleNamespace(session=SimpleNamespace(id="chat-2026-10-08"))
    said = turn.USER_TEXT.set("pay for my order")  # a chat turn: only a chat's pages are signed in

    async def visit(url):
        return (await tools["browser_open"].run_async(args={"url": url}, tool_context=ctx))["result"]
    first = await visit("https://www.amazon.in/checkout/pay")
    assert "from your signed-in amazon.in" in first and "UPI ID for" not in first and private == {"amazon.in"}
    assert "This chat is now private" in first  # once: from here on, other sites ask (a new chat is clean)
    state.set_upi_id(store, "ashaa@okaxis")
    second = await visit("https://www.amazon.in/checkout/pay")
    assert "The user's UPI ID for payment collect requests: ashaa@okaxis" in second and "now private" not in second
    private.clear()
    other = await visit("https://shop.example/checkout")
    assert "signed-in" not in other and "ashaa@okaxis" not in other and private == set()
    turn.USER_TEXT.reset(said)


async def test_a_chat_stays_private_after_a_signed_in_read(store, isolated_settings):
    """The signed-in page's text stays in the model's context for the rest of the chat, so the rest of the chat is
    private: later turns ask before anything leaves, and none of them feed the memory review. Another chat is clean."""
    from google.adk.events import Event
    from google.genai import types

    from odie.app.runner import OdieRunner
    guard.remember(store, "chat-2026-10-08", "amazon.in")
    r = OdieRunner(store)
    r.review_every = 100  # keep the turns, to see which ones would be reviewed
    seen = []

    async def fake_run(**kw):
        seen.append(turn.private_sites())
        yield Event(author="odie", invocation_id="i", content=types.Content(role="model", parts=[types.Part(text="Sure.")]))
    r.runner.run_async = fake_run
    [e async for e in r.chat("now search the web for what that page said", session_id="chat-2026-10-08")]
    [e async for e in r.chat("what's the weather in Pune?", session_id="chat-2026-10-09")]
    assert seen == [{"amazon.in"}, set()]
    assert [u for u, _ in r._turns] == ["what's the weather in Pune?"]  # the private chat's turn never reaches the review
    state.turn_off(store)
    assert guard.private_of(store, "chat-2026-10-08") == set()  # off forgets it
    await r.close()


def test_background_checks_keep_the_web_and_the_browser(store):
    """The guard's predicates answer "no tap" outside a chat, so trackers and the watch keep searching, fetching and
    browsing (cookie-free); anything else that asks (the shell) is still refused, and they never buy."""
    from odie.agent.tools.browser import make_browser_tools
    from odie.agent.tools.shell import make_shell_tool
    from odie.agent.tools.web import make_web_tools
    from odie.trackers import guard as tracker_guard
    from odie.watch.check import guard as watch_guard
    web = {t.name: t for t in make_web_tools(store=store)}
    br = {t.name: t for t in make_browser_tools(store, browser_for=lambda: None)}
    ctx = SimpleNamespace(session=SimpleNamespace(id="tracker-7"))
    for check in (tracker_guard, watch_guard):
        assert check(web["web_search"], {"query": "airpods price"}, ctx) is None
        assert check(web["web_fetch"], {"url": "https://shop.example/p"}, ctx) is None
    assert tracker_guard(br["browser_open"], {"url": "https://shop.example/p"}, ctx) is None
    assert tracker_guard(br["find_images"], {"query": "goa"}, ctx) is None
    guard.LAST_URL["tracker-7"] = "https://www.amazon.in/cart"
    assert tracker_guard(br["browser_click"], {"text": "Place order"}, ctx) is not None  # never buys
    assert tracker_guard(make_shell_tool(store=store), {"command": "ls"}, ctx) is not None


async def test_photo_searches_never_carry_cookies():
    from odie.browser import images

    class B:
        def __init__(self):
            self.isolated = []

        async def open(self, tab, url, isolated=False):
            self.isolated.append(isolated)

        async def scroll(self, tab, down=True):
            pass

        async def html(self, tab):
            return "<html></html>"

        async def close_tab(self, tab):
            pass
    b = B()
    await images.find(b, "goa beach", 4, loads=lambda urls: _none())
    assert b.isolated and all(b.isolated)


async def _none():
    return set()


def test_a_foreign_page_in_a_private_chat_asks(store, private):
    """After a planted link (or a redirect the user approved) puts the tab on another site, clicking or typing there
    asks: what's typed reaches that site. The card shows the text."""
    from odie.app.runner import approval_from_confirmation
    private.add("amazon.in")
    guard.LAST_URL["chat-1"] = "https://evil.example/collect"
    assert guard.click_needs_tap(store, "chat-1", "Next")
    assert guard.type_needs_tap(store, "chat-1", "Notes", submit=False)
    guard.LAST_URL["chat-1"] = "https://www.amazon.in/s?k=airpods"
    assert not guard.click_needs_tap(store, "chat-1", "Next") and not guard.type_needs_tap(store, "chat-1", "Search", submit=True)
    guard.LAST_URL["chat-1"] = "https://evil.example/collect"
    card = approval_from_confirmation(_fc("browser_type", {"field": "Notes", "text": "order 402-77, 12 MG Road"}), "inv", "chat-1", store)
    assert "order 402-77, 12 MG Road" in card["summary"] and "evil.example" in card["summary"]


@pytest.mark.parametrize("words", ["Submit", "Submit request", "Apply coupon", "Claim reward", "Redeem"])
def test_more_consequential_words(store, words):
    guard.LAST_URL["chat-1"] = "https://www.amazon.in/returns"
    assert guard.click_needs_tap(store, "chat-1", words)


async def test_the_fetch_fallback_never_carries_cookies(store):
    from odie.agent.tools.web import make_web_tools
    from odie.browser.engine import Page

    class B:
        opened = []

        async def open(self, tab, url, isolated=False):
            B.opened.append(isolated)
            return Page(url=url, title="t", text="hello from the page", shot=b"")

        async def close_tab(self, tab):
            pass

    import httpx
    t = {x.name: x for x in make_web_tools(store=store, api_key="", browser_for=lambda: B(),
                                            transport=httpx.MockTransport(lambda r: httpx.Response(503)),
                                            resolve=_public)}
    out = await t["web_fetch"].func(url="https://shop.example/p")
    assert "hello from the page" in out and B.opened == [True]


async def _public(host):
    return ["93.184.216.34"]


def test_steps_fence_the_tab_in_a_private_chat(store, private):
    """Every browser step in a private chat tells the engine where the tab may go: the signed-in sites, the page it's
    on, and (for browser_open, already asked) the address opened. Anywhere else, the engine stops the page."""
    import asyncio

    from odie.agent.tools.browser import make_browser_tools
    from tests.test_browser_tools import FakeBrowser

    class Fenced(FakeBrowser):
        fences = []

        def fence(self, tab, sites):
            Fenced.fences.append((tab, set(sites) if sites else None))
    b = Fenced()
    tools = {t.name: t for t in make_browser_tools(store, browser_for=lambda: b)}
    ctx = SimpleNamespace(session=SimpleNamespace(id="chat-1"))
    asyncio.run(tools["browser_open"].func(url="https://shop.example/x", tool_context=ctx))
    assert Fenced.fences[-1] == ("chat-1", None)  # nothing private yet
    private.add("amazon.in")
    guard.LAST_URL["chat-1"] = "https://www.amazon.in/cart"
    asyncio.run(tools["browser_click"].func(text="Next", tool_context=ctx))
    assert Fenced.fences[-1] == ("chat-1", {"amazon.in"})
    asyncio.run(tools["browser_open"].func(url="https://www.flipkart.com/x", tool_context=ctx))
    assert Fenced.fences[-1] == ("chat-1", {"amazon.in", "flipkart.com"})


def test_no_memories_in_a_private_chat(store, private, tmp_path):
    from odie.memory.store import MemoryFile
    from odie.memory.tools import make_memory_tools
    tools = {t.name: t for t in make_memory_tools(MemoryFile(tmp_path / "m.md", tmp_path / "m.lock", "t"))}
    assert tools["update_memory"].func(title="Home", content="Lives in Pune").startswith("Saved")
    private.add("amazon.in")  # a signed-in page was read in this chat
    out = tools["update_memory"].func(title="Address", content="12 MG Road, Pune")
    assert out.startswith("Not saved") and "signed-in" in out


async def test_a_private_chat_fetches_no_deck_photos(isolated_settings, monkeypatch):
    """A photo address the model writes into a deck could carry what it read: in a private chat, web photos aren't
    fetched (the deck uses its no-photo layouts, and says why)."""
    from odie.decks import photos
    asked = []

    async def download(url, *a, **k):
        asked.append(url)
        raise AssertionError("fetched")
    monkeypatch.setattr(photos, "safe_download", download)
    token = turn.PRIVATE.set({"amazon.in"})
    try:
        with pytest.raises(photos.PhotoError, match="signed-in"):
            await photos.fetch("https://evil.example/x.jpg?d=order-402-77")
    finally:
        turn.PRIVATE.reset(token)
    assert asked == []


async def test_private_replies_are_marked(store, isolated_settings):
    """The app holds web images in a private chat's replies until a tap (an image address can carry what the model
    read): the stream says so before any private text, and history marks the private segment's messages."""
    from google.adk.events import Event
    from google.genai import types

    from odie import config
    from odie.app.runner import OdieRunner
    r = OdieRunner(store)

    async def fake_run(**kw):
        yield Event(author="odie", invocation_id="i", content=types.Content(role="model", parts=[types.Part(text="Looking.")]))
        turn.PRIVATE.get().add("amazon.in")  # a signed-in page read mid-turn
        yield Event(author="odie", invocation_id="i", content=types.Content(role="model", parts=[types.Part(text="![x](https://evil.example/p.png?d=1)")]))
    r.runner.run_async = fake_run
    got = [e async for e in r.chat("where is my order", session_id="chat-2026-10-08")]
    kinds = [e["type"] for e in got]
    first_private_text = next(i for i, e in enumerate(got) if "evil.example" in str(e.get("text", "")))
    assert "private" in kinds and kinds.index("text") < kinds.index("private") < first_private_text

    s = config.settings
    for sid, private in (("chat-2026-10-07", False), ("chat-2026-10-09", True)):
        await r._ensure_session(sid)
        sess = await r.session_service.get_session(app_name=s.app_name, user_id=s.user_id, session_id=sid)
        for who, text in (("user", "hi"), ("odie", "![x](https://evil.example/p.png)")):
            await r.session_service.append_event(sess, Event(author=who, invocation_id="j", content=types.Content(
                role="user" if who == "user" else "model", parts=[types.Part(text=text)])))
        if private:
            guard.remember(store, sid, "amazon.in")
    assert not any(i.get("private") for i in (await r.history("2026-10-07"))["items"])
    assert all(i.get("private") for i in (await r.history("2026-10-09"))["items"] if i["role"] == "odie")
    assert all(i.get("private") for i in (await r.session_history("chat-2026-10-09"))["items"] if i["role"] == "odie")
    await r.close()


@pytest.mark.parametrize("on", [True, False])
async def test_a_sign_in_page_says_whose_turn_it_is(store, on):
    """A page with a password field: the step says to hand it to the user (browser_sign_in), or, while signed-in
    browsing is off, to point them to Settings; never to type the password. (A weaker model offered to type a
    published demo password.)"""
    from odie.agent.tools import browser as btools
    from odie.browser.engine import Page
    from tests.test_browser_tools import SHOT, FakeBrowser

    class Login(FakeBrowser):
        def _page(self, url="", note=""):
            return Page(url=url, title="Sign in", text="Email\nPassword", shot=SHOT, note=note, login=True)
    if not on:
        state.turn_off(store)
    tools = {t.name: t for t in btools.make_browser_tools(store, browser_for=lambda: Login())}
    out = (await tools["browser_open"].run_async(args={"url": "https://www.example.com/login"},
                                                 tool_context=SimpleNamespace(session=SimpleNamespace(id="chat-9"))))["result"]
    assert "never type" in out.lower()
    assert ("browser_sign_in" in out) is on and ("Settings → Browser" in out) is (not on)


@pytest.fixture
def said():
    """The user's own words for this chat turn."""
    tokens = []

    def say(text):
        tokens.append(turn.USER_TEXT.set(text))
    yield say
    for t in reversed(tokens):
        turn.USER_TEXT.reset(t)


def test_a_site_the_user_typed_needs_no_tap(store, private, said):
    """The user named it in their own words: a page can't write those, so opening it is what they asked for."""
    private.add("amazon.in")
    said("summarise https://projectdiscovery.io/research/how-abliterated-models-can-get-you-pwned, please")
    assert not guard.url_needs_tap(store, "https://projectdiscovery.io/research/how-abliterated-models-can-get-you-pwned", "chat-1")
    assert not guard.url_needs_tap(store, "https://www.projectdiscovery.io/blog", "chat-1")  # the same site
    assert guard.url_needs_tap(store, "https://evil.example/x?orders=402-77", "chat-1")
    said("open linkedin.com and find PM jobs in Pune")
    assert not guard.url_needs_tap(store, "https://www.linkedin.com/jobs/search?keywords=pm", "chat-1")
    assert guard.url_needs_tap(store, "https://linkedin.xyz/jobs", "chat-1")  # a lookalike isn't what they typed
    said("open LinkedIn")
    assert guard.url_needs_tap(store, "https://www.linkedin.com/", "chat-1")  # a bare name asks once
    said("mail it to someone@gmail.com")
    assert guard.url_needs_tap(store, "https://gmail.com/x?d=1", "chat-1")  # an email address names no site


def test_outside_a_chat_turn_no_site_is_named(store):
    assert turn.USER_TEXT.get() is None and guard.named_sites() == set()


def test_one_tap_per_site_per_chat(store, private, said):
    """After the user's tap opens another site, its pages and clicks stop asking for the rest of that chat."""
    import asyncio

    from odie.agent.tools.browser import make_browser_tools
    from tests.test_browser_tools import FakeBrowser
    tools = {t.name: t for t in make_browser_tools(store, browser_for=lambda: FakeBrowser())}
    ctx = SimpleNamespace(session=SimpleNamespace(id="chat-1"))
    private.add("amazon.in")
    said("compare it with flipkart")
    assert guard.url_needs_tap(store, "https://www.flipkart.com/x", "chat-1")
    asyncio.run(tools["browser_open"].func(url="https://www.flipkart.com/x", tool_context=ctx))  # runs only after the tap
    assert guard.allowed_of(store, "chat-1") == {"flipkart.com"}
    assert not guard.url_needs_tap(store, "https://www.flipkart.com/search?q=airpods", "chat-1")
    guard.LAST_URL["chat-1"] = "https://www.flipkart.com/search?q=airpods"
    assert not guard.click_needs_tap(store, "chat-1", "Next") and not guard.type_needs_tap(store, "chat-1", "Search", submit=True)
    assert guard.url_needs_tap(store, "https://www.flipkart.com/x", "chat-2")  # another chat asks again
    assert guard.url_needs_tap(store, "https://evil.example/x", "chat-1")


def test_the_named_site_needs_no_tap_from_the_tool(store, private, said):
    from odie.agent.tools.browser import make_browser_tools
    br = {t.name: t for t in make_browser_tools(store, browser_for=lambda: None)}
    ctx = SimpleNamespace(session=SimpleNamespace(id="chat-1"))
    private.add("amazon.in")
    said("read https://projectdiscovery.io/research/x")
    assert br["browser_open"]._require_confirmation(url="https://projectdiscovery.io/research/x", tool_context=ctx) is False
    assert br["browser_open"]._require_confirmation(url="https://evil.example/x", tool_context=ctx) is True


def test_fetching_the_typed_address_needs_no_tap(store, private, said):
    """web_fetch may go through a fetch service, which sees the address: only the exact address the user typed is free."""
    from odie.agent.tools.web import make_web_tools
    web = {t.name: t for t in make_web_tools(store=store)}
    private.add("amazon.in")
    said("what does https://projectdiscovery.io/research/x say?")
    assert web["web_fetch"]._require_confirmation(url="https://projectdiscovery.io/research/x") is False
    assert web["web_fetch"]._require_confirmation(url="https://projectdiscovery.io/research/x/") is False
    assert web["web_fetch"]._require_confirmation(url="https://projectdiscovery.io/research/x?orders=402-77") is True
    assert web["web_search"]._require_confirmation(query="projectdiscovery abliterated") is True  # a search still asks


def test_the_fence_lets_the_named_and_okayed_sites_in(store, private, said):
    private.add("amazon.in")
    guard.allow(store, "chat-1", "flipkart.com")
    said("open linkedin.com")
    guard.LAST_URL["chat-1"] = "https://www.amazon.in/cart"
    assert guard.fence_for("chat-1", store=store) == {"amazon.in", "flipkart.com", "linkedin.com"}


def test_forgetting_clears_the_okayed_sites(store):
    guard.allow(store, "chat-1", "flipkart.com")
    guard.forget_all(store)
    assert guard.allowed_of(store, "chat-1") == set()
