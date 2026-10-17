"""Web search and page reading. Whichever search key is set is used, in this order: Tavily, Brave, Ollama. One that
fails (expired key, quota, outage) hands over to the next; with no working key the tool falls back to DuckDuckGo's
plain HTML page and reads pages directly. Keys come from the environment or the settings .env and are read on
every call, so a key added in Settings works at once.
Everything that comes back is third-party text and is fenced like email: the model may read it, never obey it."""
from __future__ import annotations

import asyncio
import ipaddress
import os
import re
import uuid
import socket
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, unquote, urljoin, urlparse

import httpx
from google.adk.tools import FunctionTool

from odie.signin import guard

OPEN, CLOSE = "<<<UNTRUSTED WEB>>>", "<<<END UNTRUSTED WEB>>>"
SEARCH_URL = "https://api.tavily.com/search"
EXTRACT_URL = "https://api.tavily.com/extract"
BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"
OLLAMA_SEARCH_URL = "https://ollama.com/api/web_search"
OLLAMA_FETCH_URL = "https://ollama.com/api/web_fetch"
DDG_URL = "https://html.duckduckgo.com/html/"
PAGE_CAP = 12000
PAGE_BYTES = 2_000_000
BROWSER_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 15_0) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15"


@dataclass(frozen=True)
class SearchProvider:
    id: str
    name: str
    env: str
    key_page: str


PROVIDERS = [
    SearchProvider("tavily", "Tavily", "TAVILY_API_KEY", "https://app.tavily.com"),
    SearchProvider("brave", "Brave", "BRAVE_API_KEY", "https://api-dashboard.search.brave.com"),
    SearchProvider("ollama", "Ollama", "OLLAMA_API_KEY", "https://ollama.com/settings/keys"),
]
PROVIDER_BY_ID = {p.id: p for p in PROVIDERS}
FREE = "free"  # DuckDuckGo + direct page reads


def _key_in(name: str, files: list[Path]) -> str | None:
    pattern = re.compile(rf"\s*(?:export\s+)?{re.escape(name)}\s*=\s*['\"]?([^'\"\s#]+)")
    for f in files:
        try:
            for line in f.read_text().splitlines():
                m = pattern.match(line)
                if m:
                    return m.group(1)
        except OSError:
            continue
    return None


def load_tavily_key(env_files: list[Path] | None = None) -> str | None:
    from odie.secrets import env_file
    return os.environ.get("TAVILY_API_KEY") or _key_in("TAVILY_API_KEY", env_files or [env_file()])


def key_source(p: SearchProvider) -> tuple[str | None, str | None]:
    """(key, where it came from: "env" | "settings"), read now. Settings means the assistant's own .env."""
    from odie.secrets import env_file
    if os.environ.get(p.env):
        return os.environ[p.env], "env"
    if k := _key_in(p.env, [env_file()]):
        return k, "settings"
    return None, None


def configured_keys() -> list[tuple[str, str]]:
    """[(provider id, key)] for every search key set, in the order they are tried."""
    return [(p.id, k) for p in PROVIDERS if (k := key_source(p)[0])]


def _fence(text: str) -> str:
    body = text.replace(CLOSE, "[marker removed]").replace(OPEN, "[marker removed]")
    return f"{OPEN}\n{body}\n{CLOSE}"


def search_results_text(data: dict) -> str:
    lines = []
    if data.get("answer"):
        lines.append(f"Summary: {data['answer']}")
    for i, r in enumerate(data.get("results") or [], 1):
        lines.append(f"{i}. {r.get('title', '')} ({r.get('url', '')})\n   {str(r.get('content', ''))[:600]}")
    imgs = [im if isinstance(im, dict) else {"url": im} for im in (data.get("images") or [])][:6]
    if imgs:
        lines.append("Images found (real URLs; the only image URLs you may show):")
        for im in imgs:
            desc = str(im.get("description") or im.get("title") or "")[:140]
            lines.append(f"- {im.get('url', '')}" + (f" | {desc}" if desc else ""))
    return _fence("\n".join(lines) if lines else "No results.")


NOT_IMAGES = ("lookaside.fbsbx.com", "lookaside.instagram.com")  # social "crawler" links: a web page, not a picture


async def _loads(c: httpx.AsyncClient, url: str) -> bool:
    """Does this URL give an image the way the app will load it (no referrer)? Reads the headers only."""
    if not url.startswith("https://") or any(h in url for h in NOT_IMAGES):
        return False
    try:
        async with c.stream("GET", url, headers={"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) Safari/604.1"},
                            timeout=4, follow_redirects=True) as r:
            return r.status_code == 200 and r.headers.get("content-type", "").startswith("image/")
    except (httpx.HTTPError, ValueError):
        return False


async def usable_images(c: httpx.AsyncClient, images: list) -> list:
    """Only the images that actually load: search engines list web pages, crawler links and hotlink-blocked files too."""
    imgs = [im if isinstance(im, dict) else {"url": im} for im in images][:8]
    ok = await asyncio.gather(*(_loads(c, str(im.get("url") or "")) for im in imgs))
    return [im for im, good in zip(imgs, ok) if good]


class Failed(Exception):
    """A provider couldn't answer (bad key, quota, outage): try the next one."""


def _check(r: httpx.Response, name: str) -> None:
    if r.status_code in (401, 403):
        raise Failed(f"{name} key was refused ({r.status_code})")
    if r.status_code == 429 or r.status_code == 432:
        raise Failed(f"{name} quota used up ({r.status_code})")
    if r.status_code >= 400:
        raise Failed(f"{name} failed ({r.status_code})")


_TAGS = re.compile(r"<[^>]+>")


def _plain(html: str) -> str:
    return re.sub(r"\s+", " ", unescape(_TAGS.sub("", html or ""))).strip()


async def tavily_search(c: httpx.AsyncClient, key: str, query: str, n: int) -> dict:
    r = await c.post(SEARCH_URL, headers={"Authorization": f"Bearer {key}"},
                     json={"query": query, "max_results": n, "include_answer": True, "search_depth": "basic",
                           "include_images": True, "include_image_descriptions": True})
    _check(r, "Tavily")
    data = r.json()
    if data.get("images"):
        data["images"] = await usable_images(c, data["images"])
    return data


async def brave_search(c: httpx.AsyncClient, key: str, query: str, n: int) -> dict:
    r = await c.get(BRAVE_URL, params={"q": query, "count": n}, headers={"X-Subscription-Token": key, "Accept": "application/json"})
    _check(r, "Brave")
    results = ((r.json().get("web") or {}).get("results")) or []
    return {"results": [{"title": _plain(x.get("title", "")), "url": x.get("url", ""),
                         "content": _plain(" ".join([x.get("description", ""), *(x.get("extra_snippets") or [])]))} for x in results[:n]]}


async def ollama_search(c: httpx.AsyncClient, key: str, query: str, n: int) -> dict:
    r = await c.post(OLLAMA_SEARCH_URL, headers={"Authorization": f"Bearer {key}"}, json={"query": query, "max_results": n})
    _check(r, "Ollama")
    return {"results": [{"title": x.get("title", ""), "url": x.get("url", ""), "content": str(x.get("content", ""))} for x in (r.json().get("results") or [])[:n]]}


SEARCHES = {"tavily": tavily_search, "brave": brave_search, "ollama": ollama_search}

_DDG_LINK = re.compile(r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.S)
_DDG_SNIPPET = re.compile(r'<a[^>]*class="result__snippet"[^>]*>(.*?)</a>', re.S)


def ddg_results(html: str, n: int) -> list[dict]:
    """Results from DuckDuckGo's HTML page: its links go through /l/?uddg=<the real URL>."""
    out = []
    snippets = _DDG_SNIPPET.findall(html)
    for i, (href, title) in enumerate(_DDG_LINK.findall(html)):
        url = unescape(href)
        if "uddg=" in url:
            url = unquote(parse_qs(urlparse(url).query).get("uddg", [""])[0])
        if url.startswith("//"):
            url = "https:" + url
        if not url.startswith("http") or "duckduckgo.com/y.js" in url:  # ads
            continue
        out.append({"title": _plain(title), "url": url, "content": _plain(snippets[i]) if i < len(snippets) else ""})
        if len(out) >= n:
            break
    return out


async def free_search(c: httpx.AsyncClient, query: str, n: int) -> dict:
    r = await c.post(DDG_URL, data={"q": query}, headers={"User-Agent": BROWSER_UA})
    _check(r, "DuckDuckGo")
    return {"results": ddg_results(r.text, n)}


class _Text(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "head", "template"}
    BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "header", "footer"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def html_text(html: str) -> str:
    p = _Text()
    p.feed(html)
    lines = (re.sub(r"[ \t\r\f\v]+", " ", ln).strip() for ln in "".join(p.parts).split("\n"))
    return "\n".join(ln for ln in lines if ln)


Resolver = Callable[[str], Awaitable[list[str]]]


async def resolve_host(host: str) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return [i[4][0] for i in infos]


async def public_url(url: str, resolve: Resolver) -> str | None:
    """None if the URL may be read from this computer; else why not. Only public web addresses: never this machine, the
    home network or link-local ranges (a page or a mail could ask for http://127.0.0.1:8000/...)."""
    u = urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        return "only http(s) web addresses can be read"
    try:
        ips = [ipaddress.ip_address(u.hostname)]
    except ValueError:
        try:
            ips = [ipaddress.ip_address(a.split("%")[0]) for a in await resolve(u.hostname)]
        except (OSError, ValueError):
            return f"{u.hostname} could not be found"
    if not ips or any(not ip.is_global or ip.is_multicast for ip in ips):
        return "that address is on this computer or the local network, which web_fetch never reads"
    return None


async def direct_fetch(c: httpx.AsyncClient, url: str, resolve: Resolver) -> str:
    """Read a page straight from the site, following up to 5 redirects and checking each hop."""
    for _ in range(6):
        if problem := await public_url(url, resolve):
            raise Failed(problem)
        async with c.stream("GET", url, headers={"User-Agent": BROWSER_UA, "Accept": "text/html,text/plain;q=0.9,*/*;q=0.5"},
                            follow_redirects=False) as r:
            if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("location"):
                url = urljoin(url, r.headers["location"])
                continue
            _check(r, "The site")
            kind = r.headers.get("content-type", "")
            if not any(t in kind for t in ("text/", "html", "xml", "json")) and kind:
                raise Failed(f"not a page ({kind.split(';')[0]})")
            body = b""
            async for chunk in r.aiter_bytes():
                body += chunk
                if len(body) > PAGE_BYTES:
                    break
            text = body.decode(r.encoding or "utf-8", errors="replace")
            return html_text(text) if "html" in kind or text.lstrip()[:1] == "<" else text
    raise Failed("too many redirects")


async def tavily_fetch(c: httpx.AsyncClient, key: str, url: str) -> str:
    r = await c.post(EXTRACT_URL, headers={"Authorization": f"Bearer {key}"}, json={"urls": [url]})
    _check(r, "Tavily")
    results = r.json().get("results") or []
    return str(results[0].get("raw_content") or "") if results else ""


async def ollama_fetch(c: httpx.AsyncClient, key: str, url: str) -> str:
    r = await c.post(OLLAMA_FETCH_URL, headers={"Authorization": f"Bearer {key}"}, json={"url": url})
    _check(r, "Ollama")
    d = r.json()
    return "\n\n".join(x for x in (str(d.get("title") or ""), str(d.get("content") or "")) if x)


FETCHES = {"tavily": tavily_fetch, "ollama": ollama_fetch}  # Brave has no page reader: those go direct


_SCRIPT_SHELL = re.compile(r"enable javascript|javascript is (disabled|required|turned off)|turn on javascript", re.I)


def needs_browser(text: str) -> bool:
    """A page a plain fetch can't read: next to nothing, or a "turn on JavaScript" shell."""
    t = text.strip()
    return len(t) < 300 or bool(_SCRIPT_SHELL.search(t[:2000]))


def make_web_tools(api_key: str | None = None, transport: httpx.AsyncBaseTransport | None = None, store=None,
                   keys: Callable[[], list[tuple[str, str]]] | None = None, resolve: Resolver | None = None,
                   browser_for: Callable[[], object] | None = None, ask_first: bool = True) -> list[FunctionTool]:
    """api_key pins Tavily with that key ("" = no keys at all), keys replaces the key lookup (tests); store records
    which provider answered last, for Settings. ask_first=False builds both tools without the private chat's approval
    card: for a focused background turn (the research writer), which has no chat to show one in and is only started
    outside a private chat."""
    if keys is None:
        keys = (lambda: [("tavily", api_key)] if api_key else []) if api_key is not None else configured_keys
    resolve = resolve or resolve_host

    def remember(used: str, failed: list[str]) -> None:
        if store is not None:
            store.set_setting("search.last", {"provider": used, "failed": failed, "at": datetime.now(UTC).isoformat()})

    async def web_search(query: str, max_results: int = 5) -> str:
        """Search the web for current information: news, prices, weather, facts you are unsure of, anything after your training data. Returns numbered results with URLs (cite them) and real image URLs you can show."""
        n = max(1, min(int(max_results), 10))
        failed: list[str] = []
        async with httpx.AsyncClient(timeout=30, transport=transport) as c:
            for pid, key in keys():
                try:
                    data = await SEARCHES[pid](c, key, query, n)
                except (Failed, httpx.HTTPError, ValueError) as e:
                    failed.append(str(e) if isinstance(e, Failed) else f"{PROVIDER_BY_ID[pid].name} failed ({type(e).__name__})")
                    continue
                remember(pid, failed)
                return search_results_text(data)
            try:
                data = await free_search(c, query, n)
            except (Failed, httpx.HTTPError) as e:
                remember(FREE, failed + [str(e) if isinstance(e, Failed) else f"DuckDuckGo failed ({type(e).__name__})"])
                return "Web search failed: " + "; ".join(failed + ["the free fallback did not answer either"]) + "."
            remember(FREE, failed)
            note = (" (" + "; ".join(failed) + ", so this came from the free fallback)") if failed else ""
            return search_results_text(data) + note

    async def web_fetch(url: str) -> str:
        """Read one web page (article, docs, listing) as text. Use after web_search when the snippet is not enough."""
        failed: list[str] = []
        async with httpx.AsyncClient(timeout=45, transport=transport) as c:
            text = ""
            for pid, key in keys():
                if pid not in FETCHES:
                    continue
                try:
                    text = await FETCHES[pid](c, key, url)
                    break
                except (Failed, httpx.HTTPError, ValueError) as e:
                    failed.append(str(e) if isinstance(e, Failed) else f"{PROVIDER_BY_ID[pid].name} failed")
            error = ""
            if not text:
                try:
                    text = await direct_fetch(c, url, resolve)
                except (Failed, httpx.HTTPError) as e:
                    error = f"Could not read {url}: {e if isinstance(e, Failed) else type(e).__name__}."
        if browser_for and (error or needs_browser(text)):  # shops and script-built pages: read them in the browser
            from odie.browser.engine import BrowserError
            b, tab = browser_for(), f"fetch-{uuid.uuid4().hex[:8]}"
            try:
                page = await b.open(tab, url, isolated=True)  # a plain read: never a signed-in session (that's browser_open)
                if page.text.strip():
                    text, error = page.text, ""
            except BrowserError:
                pass
            finally:
                await b.close_tab(tab)
        if error:
            return error
        if not text.strip():
            return f"Nothing readable at {url}."
        return _fence(text[:PAGE_CAP] + ("…" if len(text) > PAGE_CAP else ""))

    if browser_for:  # shops and prices go to the browser (its rule says so); search stays for quick facts
        web_search.__doc__ = web_search.__doc__.replace("news, prices, weather", "news, weather, quick facts")
    if not ask_first:
        return [FunctionTool(web_search), FunctionTool(web_fetch)]
    return [FunctionTool(web_search, require_confirmation=guard.for_query(store)),
            FunctionTool(web_fetch, require_confirmation=guard.for_fetch(store))]  # a private chat asks first: a fetch service sees the address


async def check_search_key(pid: str, key: str, transport: httpx.AsyncBaseTransport | None = None) -> str | None:
    """None if one real search works with this key, else what went wrong (shown in Settings)."""
    try:
        async with httpx.AsyncClient(timeout=20, transport=transport) as c:
            data = await SEARCHES[pid](c, key, "weather today", 1)
    except Failed as e:
        return str(e)
    except (httpx.HTTPError, ValueError) as e:
        return f"Couldn't reach {PROVIDER_BY_ID[pid].name} ({type(e).__name__})"
    return None if isinstance(data, dict) else "Unexpected answer"
