"""Photos through Odie's own browser, with no search key (spec: designed decks, part 3): free stock photos from Unsplash
and Pexels (for covers, backgrounds and moods), web photos from Bing Images (the actual place or thing, credited to
the site it came from), and the photos on any page the browser opens ("Images on this page"). Unsplash+ photos are
paid, so they're skipped. Only photos that actually load are offered."""
from __future__ import annotations

import asyncio
import html as _html
import json
import re
import uuid
from collections.abc import Awaitable, Callable
from html.parser import HTMLParser
from urllib.parse import quote, quote_plus, urlsplit

from odie.agent.tools.web import _fence

SOURCES = (("unsplash", "Unsplash", "free"), ("pexels", "Pexels", "free"), ("bing", "Bing", "web"))
Loads = Callable[[list[str]], Awaitable[set[str]]]
# Stock-photo sites whose pictures in a search are watermarked previews (the full picture is sold): a Bing result from
# one is never offered (a live Sikkim film once used a Dreamstime preview). A name counts when it is a whole part of
# the host, so thumbs.dreamstime.com and gettyimages.co.uk match; ftcdn.net is where Adobe Stock keeps its previews.
STOCK_PREVIEW_SITES = frozenset({"dreamstime", "shutterstock", "alamy", "istockphoto", "gettyimages", "123rf",
                                 "depositphotos", "adobestock", "bigstock", "bigstockphoto", "vectorstock",
                                 "canstockphoto", "ftcdn"})
ADOBE_STOCK = "stock.adobe.com"


def site_name(url: str) -> str:
    host = (urlsplit(url or "").hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def is_stock_preview(url: str) -> bool:
    """Decides whether a picture's address is on a stock-photo site that shows only watermarked previews, so a Bing
    result there is dropped: "https://thumbs.dreamstime.com/b/gangtok.jpg" -> True; "https://stock.adobe.com/in/x"
    -> True; "https://static.toiimg.com/photo/1.cms" -> False; "https://notalamy.com/a.jpg" -> False (only a whole
    part of the host counts); "https://www.adobe.com/x.jpg" -> False."""
    host = (urlsplit(url or "").hostname or "").lower()
    if host == ADOBE_STOCK or host.endswith("." + ADOBE_STOCK):
        return True
    for part in host.split("."):
        if part in STOCK_PREVIEW_SITES:
            return True
    return False


def search_url(key: str, query: str) -> str:
    q = " ".join(query.split())
    if key == "unsplash":
        return f"https://unsplash.com/s/photos/{quote(q.replace(' ', '-'))}"
    if key == "pexels":
        return f"https://www.pexels.com/search/{quote(q)}/"
    return f"https://www.bing.com/images/search?q={quote_plus(q)}&form=HDRSC2"


def _photo(url: str, kind: str, credit: str, page: str, title: str, width: int = 0, height: int = 0) -> dict:
    return {"url": url, "kind": kind, "credit": credit, "page": page, "title": " ".join(title.split())[:140], "width": width, "height": height}


class _Unsplash(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: list[dict] = []
        self.cur: dict | None = None
        self.naming = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "figure" and a.get("data-testid") == "asset-grid-masonry-figure":
            self.cur = {"page": "", "src": "", "alt": "", "name": "", "w": 0, "h": 0}
        elif self.cur is not None:
            href = a.get("href") or ""
            if tag == "a" and href.startswith("/photos/") and not self.cur["page"]:
                self.cur["page"] = "https://unsplash.com" + href
            elif tag == "a" and href.startswith("/@") and not self.cur["name"]:
                self.naming = True
            elif tag == "img" and not self.cur["src"]:
                srcset = a.get("srcset") or ""
                first = srcset.split(",")[0].strip().split(" ")[0] if srcset else (a.get("src") or "")
                self.cur["src"] = first.split("?")[0]
                self.cur["alt"] = a.get("alt") or ""
                self.cur["w"], self.cur["h"] = int(a.get("width") or 0), int(a.get("height") or 0)

    def handle_data(self, data):
        if self.naming and self.cur is not None:
            self.cur["name"] += data

    def handle_endtag(self, tag):
        if tag == "a" and self.naming:
            self.naming = False
            self.cur["name"] = " ".join(self.cur["name"].split())
        elif tag == "figure" and self.cur is not None:
            c, self.cur = self.cur, None
            if c["src"].startswith("https://images.unsplash.com/"):  # plus.unsplash.com is Unsplash+: paid
                credit = f"Photo by {c['name']} on Unsplash" if c["name"] else "Unsplash"
                self.out.append(_photo(c["src"] + "?w=2000&q=80&fm=jpg&fit=max", "free", credit, c["page"], c["alt"], c["w"], c["h"]))


def unsplash(page_html: str) -> list[dict]:
    p = _Unsplash()
    p.feed(page_html or "")
    return p.out


_PEXELS_USER = re.compile(r'"id":"(\d+)","type":"photo","attributes":\{(.{0,4000}?)"user":\{(.{0,600}?)\}', re.S)


def pexels(page_html: str) -> list[dict]:
    meta: dict[str, tuple[str, int, int]] = {}
    for m in _PEXELS_USER.finditer(page_html or ""):
        first = re.search(r'"first_name":"([^"]*)"', m[3])
        last = re.search(r'"last_name":"([^"]*)"', m[3])
        name = " ".join(x for x in ((first[1] if first else ""), (last[1] if last else "")) if x)
        w, h = re.search(r'"width":(\d+)', m[2]), re.search(r'"height":(\d+)', m[2])
        meta[m[1]] = (name, int(w[1]) if w else 0, int(h[1]) if h else 0)
    out, seen = [], set()
    for art in re.findall(r"<article\b.*?</article>", page_html or "", re.S):
        src = re.search(r'src="https://images\.pexels\.com/photos/(\d+)/', art)
        if not src or src[1] in seen:
            continue
        pid = src[1]
        seen.add(pid)
        alt = _html.unescape((re.search(r'alt="([^"]*)"', art) or [None, ""])[1])
        title = re.sub(r"^Free\s+", "", re.sub(r"\s+Stock Photo$", "", alt.strip()))
        href = re.search(r'href="(/photo/[^"]+)"', art)
        name, w, h = meta.get(pid, ("", 0, 0))
        out.append(_photo(f"https://images.pexels.com/photos/{pid}/pexels-photo-{pid}.jpeg?auto=compress&cs=tinysrgb&w=2000", "free",
                          f"Photo by {name} on Pexels" if name else "Pexels", f"https://www.pexels.com{href[1]}" if href else "", title, w, h))
    return out


class _Bing(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: list[dict] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag != "a" or "iusc" not in (a.get("class") or "").split() or not a.get("m"):
            return
        try:
            m = json.loads(a["m"])
        except ValueError:
            return
        url, page = str(m.get("murl") or ""), str(m.get("purl") or "")
        if not url.startswith("https://"):
            return
        if is_stock_preview(url) or is_stock_preview(page):  # a watermarked preview, wherever Bing found it
            return
        self.out.append(_photo(url, "web", site_name(page or url), page, _html.unescape(str(m.get("t") or ""))))


def bing(page_html: str) -> list[dict]:
    p = _Bing()
    p.feed(page_html or "")
    return p.out


PARSERS = {"unsplash": unsplash, "pexels": pexels, "bing": bing}


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]{3,}", (text or "").lower())}


def _about(title: str, query: str) -> bool:
    """A web photo's title shares a word with the ask (Bing sometimes mixes in pictures of something else)."""
    return bool(_words(title) & _words(query))


async def _default_loads(urls: list[str]) -> set[str]:
    import httpx

    from odie.agent.tools.web import _loads
    async with httpx.AsyncClient() as c:
        ok = await asyncio.gather(*(_loads(c, u) for u in urls))
    return {u for u, good in zip(urls, ok) if good}


async def find(browser, query: str, count: int = 8, loads: Loads | None = None) -> dict:
    """{"free": [...], "web": [...], "failed": ["Pexels: why", ...]}: the three sources read at once, each in a tab of
    its own (closed after), and only photos that load kept, up to `count` in each group."""
    run = uuid.uuid4().hex[:8]  # this search's own tabs: two searches at once (chat and the watch) never share one

    async def one(key: str, label: str) -> tuple[str, list[dict], str]:
        tab = f"images:{key}:{run}"
        try:
            await browser.open(tab, search_url(key, query), isolated=True)  # a photo search never needs a session
            await browser.scroll(tab)  # lazy tiles load as they come into view
            return key, PARSERS[key](await browser.html(tab)), ""
        except Exception as e:  # noqa: BLE001 (one source down never stops the others)
            return key, [], f"{label}: {e}"
        finally:
            try:
                await browser.close_tab(tab)
            except Exception:  # noqa: BLE001
                pass
    got = await asyncio.gather(*(one(k, label) for k, label, _ in SOURCES))
    by = {k: photos[: count + 4] for k, photos, _ in got}
    candidates = [p["url"] for photos in by.values() for p in photos]
    ok = await (loads or _default_loads)(candidates) if candidates else set()
    free = [p for k in ("unsplash", "pexels") for p in by[k] if p["url"] in ok][:count]
    web = [p for p in by["bing"] if p["url"] in ok and _about(p["title"], query)][:count]
    return {"free": free, "web": web, "failed": [why for _, _, why in got if why]}


def find_text(got: dict) -> str:
    lines = []
    if got["free"]:
        lines.append("Free photos (Unsplash, Pexels: free to use; for covers, backgrounds and moods; they may not show the exact place):")
        lines += [f"- {p['url']} | {p['title']} | credit: {p['credit']}" for p in got["free"]]
    else:
        lines.append("No free photos found.")
    if got["web"]:
        lines.append("Web photos (the actual place or thing: pick one whose title matches, and credit the site):")
        lines += [f"- {p['url']} | {p['title']} | credit: {p['credit']}" for p in got["web"]]
    else:
        lines.append("No web photos found.")
    if got.get("failed"):
        lines.append("Not reached: " + "; ".join(got["failed"]))
    lines.append("Use these addresses and credits exactly as given.")
    return _fence("\n".join(lines))


def page_images_text(images: list[dict], page_url: str) -> str:
    if not images:
        return ""
    lines = [f"Images on this page (real photo addresses; credit: {site_name(page_url)}):"]
    lines += [f"- {i['url']}" + (f" | {i['label']}" if i.get("label") else "") for i in images]
    return "\n".join(lines)


# The photos on the page as it is (nothing scrolled): og:image, then the big pictures, largest first, each labelled by
# its alt text or the title of the card it sits in; logos, icons, promos, small ones and thin strips skipped.
PAGE_IMAGES_JS = r"""(() => {
  const junk = /logo|icon|sprite|avatar|promo|banner|badge/i;
  const out = [], seen = new Set();
  const og = document.querySelector('meta[property="og:image"]');
  if (og && og.content) { try { const u = new URL(og.content, location.href).href; out.push({url: u, label: document.title.slice(0, 80), area: 1e12}); seen.add(u); } catch (e) {} }
  const label = (img) => {
    if ((img.alt || '').trim()) return img.alt.trim();
    let el = img.parentElement;
    for (let i = 0; i < 6 && el; i++, el = el.parentElement) {
      const h = el.querySelector('h1,h2,h3,h4,[data-testid*="title"]');
      if (h && (h.innerText || '').trim()) return h.innerText.trim();
      const a = el.closest('a[aria-label]');
      if (a) return a.getAttribute('aria-label');
    }
    return '';
  };
  for (const img of document.images) {
    const w = img.naturalWidth, h = img.naturalHeight, src = img.currentSrc || img.src;
    if (!src || !/^https?:/.test(src) || w < 300 || h < 200 || w / h > 2.5 || w / h < 0.4) continue;
    if (junk.test(img.alt || '') || junk.test(src)) continue;
    if (seen.has(src)) continue;
    seen.add(src);
    out.push({url: src, label: label(img).replace(/\s+/g, ' ').slice(0, 80), area: w * h});
  }
  out.sort((a, b) => b.area - a.area);
  return out.slice(0, 9).map(({url, label}) => ({url, label}));
})()"""
