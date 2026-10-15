"""Where Today's news comes from: public RSS feeds, one or two per topic, chosen by the region this computer is set
to. Swap an outlet by editing these lists."""

FeedList = list[tuple[str, str, str]]  # (topic, source, url)

INDIA_TOPICS = ["India", "World", "Markets", "Sports", "Tech"]
INDIA: FeedList = [
    ("India", "The Hindu", "https://www.thehindu.com/news/national/feeder/default.rss"),
    ("India", "Indian Express", "https://indianexpress.com/section/india/feed/"),
    ("World", "BBC", "https://feeds.bbci.co.uk/news/world/rss.xml"),
    ("Markets", "Mint", "https://www.livemint.com/rss/markets"),
    ("Markets", "ET Markets", "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms"),
    ("Sports", "ESPNcricinfo", "https://www.espncricinfo.com/rss/content/story/feeds/0.xml"),
    ("Sports", "Indian Express", "https://indianexpress.com/section/sports/feed/"),
    ("Sports", "BBC Sport", "https://feeds.bbci.co.uk/sport/rss.xml"),
    ("Tech", "The Verge", "https://www.theverge.com/rss/index.xml"),
]

WORLD_TOPICS = ["World", "Markets", "Sports", "Tech"]
WORLD: FeedList = [
    ("World", "BBC", "https://feeds.bbci.co.uk/news/world/rss.xml"),
    ("World", "The Guardian", "https://www.theguardian.com/world/rss"),
    ("Markets", "CNBC", "https://www.cnbc.com/id/15839069/device/rss/rss.html"),
    ("Markets", "MarketWatch", "https://feeds.content.dowjones.io/public/rss/mw_topstories"),
    ("Sports", "BBC Sport", "https://feeds.bbci.co.uk/sport/rss.xml"),
    ("Sports", "ESPN", "https://www.espn.com/espn/rss/news"),
    ("Tech", "The Verge", "https://www.theverge.com/rss/index.xml"),
    ("Tech", "Ars Technica", "https://feeds.arstechnica.com/arstechnica/index"),
]

PRESETS: dict[str, tuple[list[str], FeedList]] = {"IN": (INDIA_TOPICS, INDIA)}


def for_country(country: str) -> tuple[list[str], FeedList]:
    """The topics and feeds for a region; the world set when there's none for it."""
    return PRESETS.get(country, (WORLD_TOPICS, WORLD))
