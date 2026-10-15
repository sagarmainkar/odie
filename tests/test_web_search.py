import httpx
import pytest

from odie.agent.tools import web
from odie.agent.tools.web import ddg_results, html_text, make_web_tools, public_url


async def _public(host):
    return {"local.example": ["192.168.1.10"], "loop.example": ["127.0.0.1"]}.get(host, ["93.184.216.34"])


def _tools(handler, keys, store=None):
    return {t.name: t for t in make_web_tools(transport=httpx.MockTransport(handler), keys=lambda: keys, store=store, resolve=_public)}


class Store:
    def __init__(self):
        self.s = {}

    def set_setting(self, k, v):
        self.s[k] = v


async def test_brave_results_read_as_numbered_results():
    def handler(req):
        assert req.url.host == "api.search.brave.com" and req.headers["x-subscription-token"] == "bk" and req.url.params["q"] == "goa hotels"
        return httpx.Response(200, json={"web": {"results": [{"title": "Taj <strong>Goa</strong>", "url": "https://t.example", "description": "Beach &amp; spa"}]}})
    out = await _tools(handler, [("brave", "bk")])["web_search"].func(query="goa hotels")
    assert "1. Taj Goa (https://t.example)" in out and "Beach & spa" in out


async def test_ollama_search_and_fetch():
    def handler(req):
        assert req.headers["authorization"] == "Bearer ok"
        if req.url.path == "/api/web_search":
            return httpx.Response(200, json={"results": [{"title": "O", "url": "https://o.example", "content": "ollama text"}]})
        return httpx.Response(200, json={"title": "Page", "content": "page body"})
    t = _tools(handler, [("ollama", "ok")])
    assert "O (https://o.example)" in await t["web_search"].func(query="q")
    page = await t["web_fetch"].func(url="https://o.example")
    assert "Page" in page and "page body" in page


async def test_a_failing_key_hands_over_to_the_next_and_settings_hears_which():
    def handler(req):
        if req.url.host == "api.tavily.com":
            return httpx.Response(432, json={"detail": "quota"})
        return httpx.Response(200, json={"web": {"results": [{"title": "B", "url": "https://b.example", "description": "brave"}]}})
    store = Store()
    out = await _tools(handler, [("tavily", "tk"), ("brave", "bk")], store)["web_search"].func(query="q")
    assert "B (https://b.example)" in out
    assert store.s["search.last"]["provider"] == "brave" and "Tavily quota used up" in store.s["search.last"]["failed"][0]


async def test_no_working_key_falls_back_to_duckduckgo():
    html = ('<a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fpune.example%2Fx&amp;rut=1">Pune <b>hotels</b></a>'
            '<a class="result__snippet" href="#">Nice &amp; quiet</a>')

    def handler(req):
        if req.url.host == "api.tavily.com":
            return httpx.Response(401)
        assert req.url.host == "html.duckduckgo.com" and b"q=pune" in req.content
        return httpx.Response(200, text=html)
    store = Store()
    out = await _tools(handler, [("tavily", "expired")], store)["web_search"].func(query="pune")
    assert "1. Pune hotels (https://pune.example/x)" in out and "Nice & quiet" in out
    assert "free fallback" in out and store.s["search.last"]["provider"] == "free"


def test_duckduckgo_ads_are_skipped():
    html = ('<a class="result__a" href="https://duckduckgo.com/y.js?ad=1">Ad</a>'
            '<a class="result__a" href="https://real.example/">Real</a>')
    assert [r["url"] for r in ddg_results(html, 5)] == ["https://real.example/"]


async def test_fetch_without_a_page_reader_reads_the_page_directly():
    def handler(req):
        if req.url.host == "start.example":
            return httpx.Response(302, headers={"location": "https://end.example/article"})
        assert req.url.host == "end.example"
        return httpx.Response(200, headers={"content-type": "text/html; charset=utf-8"},
                              text="<html><head><title>x</title><script>evil()</script></head><body><h1>Title</h1><p>Hello &amp; welcome</p></body></html>")
    page = await _tools(handler, [("brave", "bk")])["web_fetch"].func(url="https://start.example/")
    assert "Title\nHello & welcome" in page and "evil" not in page and page.startswith("<<<UNTRUSTED WEB>>>")


@pytest.mark.parametrize("url", ["http://127.0.0.1:8000/api/approvals", "http://localhost.example", "https://local.example/admin",
                                 "https://loop.example/", "http://[::1]/", "file:///etc/passwd", "http://169.254.169.254/latest"])
async def test_direct_reads_never_reach_this_mac_or_the_home_network(url):
    def handler(req):
        raise AssertionError(f"must not request {req.url}")
    if url == "http://localhost.example":
        url = "https://loop.example/x"
    out = await _tools(handler, [])["web_fetch"].func(url=url)
    assert out.startswith("Could not read")


async def test_a_redirect_to_a_local_address_is_refused():
    def handler(req):
        assert req.url.host == "public.example", f"followed into {req.url}"
        return httpx.Response(302, headers={"location": "http://192.168.1.1/"})
    out = await _tools(handler, [])["web_fetch"].func(url="https://public.example/")
    assert out.startswith("Could not read") and "local network" in out


async def test_public_url_allows_ordinary_sites():
    assert await public_url("https://en.wikipedia.org/wiki/Pune", _public) is None


def test_html_text_keeps_paragraphs():
    assert html_text("<div>a</div><p>b <b>c</b></p><style>x{}</style>") == "a\nb c"


@pytest.fixture
def no_real_keys(monkeypatch, tmp_path):
    for p in web.PROVIDERS:
        monkeypatch.delenv(p.env, raising=False)
    return tmp_path


async def test_search_settings_routes(isolated_settings, no_real_keys, monkeypatch, tmp_path):
    from odie.app.main import create_app
    from odie.secrets import env_file
    from odie.store.db import Store as RealStore
    assert str(env_file()).startswith(str(tmp_path))  # writes go to the test's config dir, never ~/.odie
    env_file().parent.mkdir(parents=True, exist_ok=True)
    env_file().write_text("OLLAMA_API_KEY=from-settings\n")
    checked = []

    async def fake_check(pid, key, transport=None):
        checked.append((pid, key))
        return None if key == "good" else "Brave key was refused (401)"
    monkeypatch.setattr(web, "check_search_key", fake_check)
    s = RealStore(tmp_path / "a.db")
    s.init_schema()

    from tests.test_approvals import FakeRunner
    app = create_app(runner=FakeRunner(), store=s)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c, app.router.lifespan_context(app):
        d = (await c.get("/api/search")).json()
        assert {p["id"]: p["source"] for p in d["providers"]} == {"tavily": None, "brave": None, "ollama": "settings"} and d["next"] == "ollama"
        r = await c.put("/api/search/brave/key", json={"api_key": "bad"})
        assert r.status_code == 422 and "refused" in r.json()["detail"]
        assert (await c.put("/api/search/brave/key", json={"api_key": "good"})).status_code == 200
        d = (await c.get("/api/search")).json()
        assert d["next"] == "brave" and next(p for p in d["providers"] if p["id"] == "brave")["source"] == "settings"
        assert "BRAVE_API_KEY=good" in env_file().read_text()
        r = (await c.delete("/api/search/brave/key")).json()
        assert r["removed"] and r["still_set"] is None
        assert (await c.put("/api/search/nope/key", json={"api_key": "good"})).status_code == 404
    assert checked == [("brave", "bad"), ("brave", "good")]
