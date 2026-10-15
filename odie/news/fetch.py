"""Today's news: parse RSS/Atom feeds and keep a small, fresh, de-duplicated batch. No model involved."""
import asyncio
import html
import logging
import re
import xml.etree.ElementTree as ET
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime

import httpx

from odie.news.feeds import FeedList, for_country

MAX_AGE = timedelta(hours=48)
PER_TOPIC = 8
PER_SOURCE = 5  # so a busy outlet can't fill a topic on its own
AHEAD = timedelta(minutes=15)  # small clock skew is fine; hours ahead is a mislabelled zone
_IMG = re.compile(r"<img[^>]+src=[\"']([^\"']+)")


def _preset() -> tuple[list[str], FeedList]:
    """The topics and feeds for the region this computer is set to."""
    from odie import config
    return for_country(config.settings.country)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child(el: ET.Element, name: str) -> ET.Element | None:
    return next((c for c in el if _local(c.tag) == name), None)


def _text(el: ET.Element, name: str) -> str:
    c = _child(el, name)
    return (c.text or "").strip() if c is not None else ""


def _when(raw: str) -> str | None:
    if not raw:
        return None
    try:
        d = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        try:
            d = datetime.fromisoformat(raw)
        except ValueError:
            return None
    if d.tzinfo is None:
        return None  # no zone: can't place it in time, so don't pretend it's fresh
    return d.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _image(item: ET.Element) -> str | None:
    for c in item:
        name = _local(c.tag)
        if name in ("content", "thumbnail") and c.get("url") and c.get("medium", "image") == "image":
            return c.get("url")
    for c in item:
        if _local(c.tag) == "enclosure" and (c.get("type") or "").startswith("image") and c.get("url"):
            return c.get("url")
    for name in ("encoded", "content", "description", "summary"):
        c = _child(item, name)
        if c is not None and c.text:
            m = _IMG.search(html.unescape(c.text) if "&lt;" in c.text else c.text)
            if m:
                return html.unescape(m.group(1))
    return None


def parse_feed(xml: str, source: str, topic: str) -> list[dict]:
    """Items from an RSS 2.0 or Atom document; [] if it isn't one."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return []
    entries = [e for e in root.iter() if _local(e.tag) in ("item", "entry")]
    out = []
    for e in entries:
        title = html.unescape(_text(e, "title"))
        link = _text(e, "link")
        if not link:
            ln = next((c for c in e if _local(c.tag) == "link" and c.get("href") and c.get("rel", "alternate") == "alternate"), None)
            link = ln.get("href") if ln is not None else ""
        if not title or not link:
            continue
        published = _when(_text(e, "pubDate") or _text(e, "published") or _text(e, "updated") or _text(e, "date"))
        out.append({"title": title, "link": link, "source": source, "topic": topic, "published": published, "image": _image(e)})
    return out


def clean(items: list[dict], now: datetime) -> list[dict]:
    """Newest first, at most PER_TOPIC per topic and PER_SOURCE per outlet, nothing undated, older than MAX_AGE or
    dated in the future (a feed that labels local time as GMT), each story once."""
    cutoff = (now - MAX_AGE).strftime("%Y-%m-%dT%H:%M:%SZ")
    ahead = (now + AHEAD).strftime("%Y-%m-%dT%H:%M:%SZ")
    fresh = sorted((i for i in items if i.get("published") and cutoff <= i["published"] <= ahead), key=lambda i: i["published"], reverse=True)
    seen_links: set[str] = set()
    seen_titles: set[str] = set()
    unique = []
    for i in fresh:
        t = i["title"].strip().lower()
        if i["link"] in seen_links or t in seen_titles:
            continue
        seen_links.add(i["link"])
        seen_titles.add(t)
        unique.append(i)
    # First pass mixes outlets (PER_SOURCE each); the second fills any free slots, so a one-outlet topic still fills up.
    per: dict[str, int] = {}
    per_source: dict[tuple[str, str], int] = {}
    picked: list[dict] = []
    for capped in (True, False):
        for i in unique:
            src = (i["topic"], i["source"])
            if any(i is p for p in picked) or per.get(i["topic"], 0) >= PER_TOPIC or (capped and per_source.get(src, 0) >= PER_SOURCE):
                continue
            picked.append(i)
            per[i["topic"]] = per.get(i["topic"], 0) + 1
            per_source[src] = per_source.get(src, 0) + 1
    return sorted(picked, key=lambda i: i["published"], reverse=True)


HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"}
log = logging.getLogger("odie.news")


async def fetch_news(transport: httpx.AsyncBaseTransport | None = None, now: datetime | None = None,
                     feeds: FeedList | None = None) -> list[dict]:
    """Every feed at once; one that fails or times out is skipped."""
    async with httpx.AsyncClient(timeout=10, headers=HEADERS, follow_redirects=True, transport=transport) as c:
        async def one(topic: str, source: str, url: str) -> list[dict]:
            try:
                r = await c.get(url)
                r.raise_for_status()
                return parse_feed(r.text, source, topic)
            except Exception as e:  # noqa: BLE001
                log.warning("news feed %s failed: %s", source, type(e).__name__)
                return []
        lists = await asyncio.gather(*(one(*f) for f in (feeds if feeds is not None else _preset()[1])))
    return clean([i for lst in lists for i in lst], now or datetime.now(UTC))


def news_batch(store) -> dict:
    return store.get_setting("news") or {"fetched_at": None, "topics": _preset()[0], "items": []}


async def refresh_news(store, transport: httpx.AsyncBaseTransport | None = None, now: datetime | None = None,
                       feeds: FeedList | None = None) -> dict:
    """Fetch and store a new batch; if nothing at all came back, keep the last one."""
    items = await fetch_news(transport=transport, now=now, feeds=feeds)
    if not items:
        return news_batch(store)
    batch = {"fetched_at": (now or datetime.now(UTC)).strftime("%Y-%m-%dT%H:%M:%SZ"), "topics": _preset()[0], "items": items}
    store.set_setting("news", batch)
    return batch


def is_stale(batch: dict, now: datetime, hours: int = 4) -> bool:
    return not batch.get("fetched_at") or batch["fetched_at"] < (now - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
