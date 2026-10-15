"""The browser as tools: offered only when a browser is on the computer, each step's page read as untrusted text with a
screenshot shown to the user, a tab per chat thread, and web_fetch reading through the browser when a plain fetch
gets nothing useful."""
from types import SimpleNamespace

import httpx
import pytest

from odie import media
from odie.agent.tools import browser as btools
from odie.browser import find
from odie.browser.engine import BrowserError, Page
from odie.store.db import Store

SHOT = b"\xff\xd8\xff\xe0" + b"\x00" * 2000


class FakeBrowser:
    def __init__(self, fail: str = ""):
        self.calls = []
        self.fail = fail

    def _page(self, url="https://www.amazon.in/s?k=airpods+pro", note=""):
        if self.fail:
            raise BrowserError(self.fail)
        return Page(url=url, title="Amazon.in : airpods pro", text="AirPods Pro 3\n₹24,930\nAirPods 5\n₹17,900", shot=SHOT, note=note)

    async def open(self, tab, url, isolated=False):
        self.calls.append(("open", tab, url))
        return self._page(url, note="Blocked 1 request to this computer or the home network.")

    async def click(self, tab, text):
        self.calls.append(("click", tab, text))
        return self._page()

    async def type(self, tab, field, text, submit=True):
        self.calls.append(("type", tab, field, text, submit))
        return self._page()

    async def scroll(self, tab, down=True):
        self.calls.append(("scroll", tab, down))
        return self._page()

    async def close_tab(self, tab):
        self.calls.append(("close", tab))


@pytest.fixture
def store(isolated_settings, tmp_path):
    s = Store(tmp_path / "assistant.db")
    s.init_schema()
    return s


def ctx(sid="chat-2026-10-07"):
    return SimpleNamespace(session=SimpleNamespace(id=sid))


def tools(store, b):
    return {t.name: t for t in btools.make_browser_tools(store, browser_for=lambda: b)}


async def test_open_returns_text_and_a_screenshot(store):
    b = FakeBrowser()
    out = await tools(store, b)["browser_open"].func(url="amazon.in/s?k=airpods+pro", tool_context=ctx())
    assert b.calls == [("open", "chat-2026-10-07", "https://amazon.in/s?k=airpods+pro")]  # a bare address gets https
    assert out["result"].startswith("Amazon.in : airpods pro\nhttps://amazon.in/s?k=airpods+pro")  # the page's own address
    assert "₹24,930" in out["result"] and "Blocked 1 request" in out["result"]
    assert set(out["media"]) == {"id", "kind", "title"} and out["media"]["kind"] == "screenshot"
    path, m = media.get(out["media"]["id"])
    assert path.read_bytes() == SHOT and m["mime"] == "image/jpeg" and m["url"] == "https://amazon.in/s?k=airpods+pro"
    assert m["step"] == "Opened amazon.in" and m["title"] == "amazon.in · Amazon.in : airpods pro"


async def test_each_step_says_what_it_did(store):
    b = FakeBrowser()
    t = tools(store, b)
    await t["browser_open"].func(url="https://www.amazon.in/", tool_context=ctx())
    steps = []
    for name, args in (("browser_click", {"text": "Next"}), ("browser_type", {"field": "Search", "text": "airpods"}),
                       ("browser_scroll", {})):
        out = await t[name].func(**args, tool_context=ctx())
        steps.append(media.get(out["media"]["id"])[1]["step"])
    assert steps == ['Clicked "Next"', 'Typed "airpods"', "Scrolled down"]
    assert b.calls[2] == ("type", "chat-2026-10-07", "Search", "airpods", True)


async def test_page_text_is_fenced(store):
    out = await tools(store, FakeBrowser())["browser_open"].func(url="https://www.amazon.in/", tool_context=ctx())
    assert "<<<UNTRUSTED WEB>>>" in out["result"] and "<<<END UNTRUSTED WEB>>>" in out["result"]
    assert out["result"].index("<<<UNTRUSTED WEB>>>") < out["result"].index("₹24,930")


async def test_errors_say_what_to_do_next(store):
    b = FakeBrowser(fail='No link or button says "Buy". These do: "Add to cart", "Next".')
    out = await tools(store, b)["browser_click"].func(text="Buy", tool_context=ctx())
    assert out == {"error": 'No link or button says "Buy". These do: "Add to cart", "Next".'}


async def test_the_tab_is_the_thread(store):
    b = FakeBrowser()
    t = tools(store, b)
    await t["browser_open"].func(url="https://a.example/", tool_context=ctx("thread-1"))
    await t["browser_open"].func(url="https://b.example/", tool_context=ctx("thread-2"))
    assert [c[1] for c in b.calls] == ["thread-1", "thread-2"]


def test_tools_only_with_the_capability(store, monkeypatch):
    from odie.agent.agent import build_agent
    from odie.capabilities import detect
    monkeypatch.setattr(find, "browser_binary", lambda: None)
    names = {t.name for t in build_agent(store).tools if hasattr(t, "name")}
    assert not names & {"browser_open", "browser_click", "browser_type", "browser_scroll"} and "browser" not in detect(store=store)
    monkeypatch.setattr(find, "browser_binary", lambda: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    names = {t.name for t in build_agent(store).tools if hasattr(t, "name")}
    assert {"browser_open", "browser_click", "browser_type", "browser_scroll"} <= names and "browser" in detect(store=store)


def test_the_rule_needs_the_capability():
    from odie.agent.prompt import ALL_CAPS, Who, rules_text
    assert "browser_open" in rules_text(Who(caps=ALL_CAPS | {"browser"}), gated=True)
    assert "browser_open" not in rules_text(Who(caps=ALL_CAPS), gated=True)


async def test_web_fetch_falls_back_to_the_browser(isolated_settings):
    from odie.agent.tools.web import make_web_tools
    shell = "<html><body><div id=root></div><noscript>You need to enable JavaScript to run this app.</noscript><script>x()</script></body></html>"

    async def resolve(host):
        return ["93.184.215.14"]
    transport = httpx.MockTransport(lambda r: httpx.Response(200, text=shell, headers={"content-type": "text/html"}))
    b = FakeBrowser()
    [_, fetch] = make_web_tools(api_key="", transport=transport, resolve=resolve, browser_for=lambda: b)
    out = await fetch.func(url="https://shop.example/item")
    assert "₹24,930" in out and "<<<UNTRUSTED WEB>>>" in out
    (op, tab, url), (cl, tab2) = b.calls
    assert (op, url, cl) == ("open", "https://shop.example/item", "close") and tab.startswith("fetch-") and tab2 == tab  # its own tab, closed after
    [_, plain] = make_web_tools(api_key="", transport=transport, resolve=resolve)
    assert "₹24,930" not in await plain.func(url="https://shop.example/item")  # no browser: the plain fetch's text, as before
    good = "<html><body><main>" + "A real article. " * 40 + "</main></body></html>"
    b2 = FakeBrowser()
    [_, fetch2] = make_web_tools(api_key="", transport=httpx.MockTransport(lambda r: httpx.Response(200, text=good, headers={"content-type": "text/html"})),
                                 resolve=resolve, browser_for=lambda: b2)
    assert "A real article." in await fetch2.func(url="https://news.example/a") and b2.calls == []  # a good page needs no browser


async def test_a_page_that_stops_changing_stops_the_loop(store):
    b = FakeBrowser()
    t = tools(store, b)
    await t["browser_open"].run_async(args={"url": "amazon.in"}, tool_context=ctx())
    first = await t["browser_scroll"].run_async(args={}, tool_context=ctx())
    second = await t["browser_scroll"].run_async(args={}, tool_context=ctx())
    third = await t["browser_scroll"].run_async(args={}, tool_context=ctx())
    assert "Nothing changed" not in first.get("result", "")
    assert "Nothing changed" in second["result"]
    assert "error" in third and "hasn't changed" in third["error"]
    assert "error" not in await t["browser_click"].run_async(args={"text": "Next"}, tool_context=ctx())  # a click isn't a scroll
    assert "error" not in await t["browser_open"].run_async(args={"url": "amazon.in/s?k=other"}, tool_context=ctx())  # a new page: fine again


def test_bot_check_pages_are_known():
    from odie.browser.engine import is_bot_check
    assert is_bot_check("Just a moment...", "Performing security verification")
    assert is_bot_check("Attention Required! | Cloudflare", "")
    assert is_bot_check("Example", "Please verify you are human to continue")
    assert not is_bot_check("Dayara Bugyal Trek", "Batch dates and fees. Our security team checks every trail.")
