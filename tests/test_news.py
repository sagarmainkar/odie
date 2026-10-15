from datetime import UTC, datetime

import httpx

from odie.news.feeds import INDIA as FEEDS
from odie.news.fetch import clean, fetch_news, is_stale, news_batch, parse_feed, refresh_news
from odie.store.db import Store

RSS = """<?xml version="1.0"?><rss xmlns:media="http://search.yahoo.com/mrss/"><channel>
<item><title><![CDATA[Rates held &amp; markets rise]]></title><link>https://a.com/1</link>
<pubDate>Mon, 05 Oct 2026 03:10:00 +0530</pubDate><media:content url="https://img/1.jpg" medium="image"/></item>
<item><title>Second</title><link>https://a.com/2</link><pubDate>Mon, 05 Oct 2026 02:00:00 GMT</pubDate>
<enclosure url="https://img/2.jpg" type="image/jpeg"/></item>
<item><title>Third</title><link>https://a.com/3</link><pubDate>Mon, 05 Oct 2026 01:00:00 GMT</pubDate>
<description>&lt;p&gt;&lt;img src="https://img/3.jpg"&gt;text&lt;/p&gt;</description></item>
<item><title>No date</title><link>https://a.com/4</link></item>
<item><title></title><link>https://a.com/5</link><pubDate>Mon, 05 Oct 2026 01:00:00 GMT</pubDate></item>
</channel></rss>"""

ATOM = """<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">
<entry><title>Gadget launched</title><link rel="alternate" href="https://v.com/x"/><updated>2026-10-05T01:30:00-04:00</updated>
<content type="html">&lt;figure&gt;&lt;img src="https://img/v.jpg" /&gt;&lt;/figure&gt;</content></entry>
</feed>"""

BBC = """<rss xmlns:media="http://search.yahoo.com/mrss/"><channel><item><title>World item</title>
<link>https://b.com/w</link><pubDate>Mon, 05 Oct 2026 00:00:00 GMT</pubDate><media:thumbnail url="https://img/b.jpg"/></item></channel></rss>"""


def test_parse_rss_titles_times_and_pictures():
    items = parse_feed(RSS, "The Hindu", "India")
    first = items[0]
    assert first == {"title": "Rates held & markets rise", "link": "https://a.com/1", "source": "The Hindu", "topic": "India",
                     "published": "2026-10-04T21:40:00Z", "image": "https://img/1.jpg"}
    assert items[1]["image"] == "https://img/2.jpg"
    assert items[2]["image"] == "https://img/3.jpg"
    assert items[3]["published"] is None and items[3]["image"] is None
    assert all(i["title"] for i in items)  # the empty-title item is dropped


def test_parse_atom_and_media_thumbnail():
    v = parse_feed(ATOM, "The Verge", "Tech")
    assert v == [{"title": "Gadget launched", "link": "https://v.com/x", "source": "The Verge", "topic": "Tech",
                  "published": "2026-10-05T05:30:00Z", "image": "https://img/v.jpg"}]
    assert parse_feed(BBC, "BBC", "World")[0]["image"] == "https://img/b.jpg"


def test_parse_garbage_is_empty():
    assert parse_feed("<html>not a feed", "X", "India") == []


def test_clean_dedupes_ages_caps_and_sorts():
    now = datetime(2026, 10, 5, 6, 0, tzinfo=UTC)
    def it(n, link, title, hours_ago, topic="India"):
        ts = datetime(2026, 10, 5, 6, 0, tzinfo=UTC).timestamp() - hours_ago * 3600
        return {"title": title, "link": link, "source": f"S{n % 2}" if topic == "Markets" else "S", "topic": topic, "image": None,
                "published": datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")}
    items = [it(1, "l1", "A", 3), it(2, "l1", "A again", 2), it(3, "l3", "a", 1), it(4, "l4", "Old", 49),
             {"title": "Undated", "link": "l5", "source": "S", "topic": "India", "image": None, "published": None}]
    items += [it(10 + k, f"m{k}", f"M{k}", k / 10, "Markets") for k in range(12)]
    out = clean(items, now)
    india = [i["title"] for i in out if i["topic"] == "India"]
    assert india == ["a", "A again"]  # newest first; same link once, same title once; old and undated dropped
    assert len([i for i in out if i["topic"] == "Markets"]) == 8


NOW = datetime(2026, 10, 5, 6, 0, tzinfo=UTC)


def _transport(fail: set[str] | None = None, body: str = BBC):
    def handler(req: httpx.Request) -> httpx.Response:
        if fail and str(req.url) in fail:
            return httpx.Response(500)
        feed = f"{req.url.host}{req.url.path}"  # one site can have several feeds
        return httpx.Response(200, text=body.replace("https://b.com/w", f"https://b.com/{feed}").replace("World item", f"Story from {feed}"))
    return httpx.MockTransport(handler)


async def test_one_feed_down_the_rest_still_arrive():
    down = {FEEDS[0][2]}
    items = await fetch_news(transport=_transport(down), now=NOW)
    assert len(items) == len(FEEDS) - 1


async def test_refresh_keeps_the_last_batch_when_everything_fails(tmp_path):
    s = Store(tmp_path / "a.db")
    s.init_schema()
    first = await refresh_news(s, transport=_transport(), now=NOW)
    assert first["items"] and first["topics"] == ["India", "World", "Markets", "Sports", "Tech"]
    again = await refresh_news(s, transport=_transport({u for _, _, u in FEEDS}), now=NOW)
    assert again == first and news_batch(s) == first


def test_news_batch_empty(tmp_path):
    s = Store(tmp_path / "a.db")
    s.init_schema()
    assert news_batch(s) == {"fetched_at": None, "topics": ["India", "World", "Markets", "Sports", "Tech"], "items": []}


def test_is_stale_after_four_hours_or_when_missing():
    assert is_stale({"fetched_at": None}, NOW)
    assert is_stale({"fetched_at": "2026-10-05T01:59:00Z"}, NOW)
    assert not is_stale({"fetched_at": "2026-10-05T02:30:00Z"}, NOW)


def test_picture_links_are_unescaped():
    feed = """<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>T</title><link href="https://v.com/y"/>
<updated>2026-10-05T01:00:00Z</updated><content type="html">&lt;img src="https://img/a.jpg?q=90&amp;#038;strip=all" /&gt;</content></entry></feed>"""
    assert parse_feed(feed, "The Verge", "Tech")[0]["image"] == "https://img/a.jpg?q=90&strip=all"


def _story(link, title, published, source="S", topic="India"):
    return {"title": title, "link": link, "source": source, "topic": topic, "image": None, "published": published}


def test_clean_drops_stories_dated_in_the_future():
    out = clean([_story("f", "Future", "2026-10-05T11:30:00Z"), _story("n", "Now-ish", "2026-10-05T05:50:00Z"),
                 _story("s", "Slight clock skew", "2026-10-05T06:05:00Z")], NOW)
    assert [i["title"] for i in out] == ["Slight clock skew", "Now-ish"]


def test_naive_dates_are_dropped():
    feed = """<rss><channel><item><title>Naive</title><link>https://n.com/1</link>
<pubDate>2026-10-05T05:00:00</pubDate></item></channel></rss>"""
    assert parse_feed(feed, "X", "India")[0]["published"] is None


def test_one_outlet_cannot_fill_a_topic():
    hindu = [_story(f"h{k}", f"H{k}", f"2026-10-05T05:{50 - k:02d}:00Z", "The Hindu") for k in range(8)]
    express = [_story(f"e{k}", f"E{k}", f"2026-10-05T04:{50 - k:02d}:00Z", "Indian Express") for k in range(8)]
    out = clean(hindu + express, NOW)
    by = [i["source"] for i in out]
    assert len(out) == 8 and by.count("The Hindu") == 5 and by.count("Indian Express") == 3


def test_a_single_outlet_topic_still_fills_up():
    bbc = [_story(f"b{k}", f"B{k}", f"2026-10-05T05:{50 - k:02d}:00Z", "BBC", "World") for k in range(10)]
    assert len(clean(bbc, NOW)) == 8


def test_india_set_is_exactly_the_previous_list():
    from odie.news.feeds import for_country
    topics, feeds = for_country("IN")
    assert topics == ["India", "World", "Markets", "Sports", "Tech"]
    assert [s for _, s, _ in feeds] == ["The Hindu", "Indian Express", "BBC", "Mint", "ET Markets", "ESPNcricinfo",
                                        "Indian Express", "BBC Sport", "The Verge"]


def test_other_regions_get_the_world_set():
    from odie.news.feeds import WORLD, WORLD_TOPICS, for_country
    assert for_country("DE") == (WORLD_TOPICS, WORLD) == for_country("")
    assert "India" not in WORLD_TOPICS and all(t in WORLD_TOPICS for t, _, _ in WORLD)
