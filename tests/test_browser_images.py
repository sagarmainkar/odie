"""Images through the browser: the three result-page readers (Unsplash+ skipped, photographers credited), find()
filling free and web photos and saying what failed, the text the model reads, and the tool."""
from pathlib import Path

from odie.browser import images

FIX = Path(__file__).parent / "fixtures" / "browser_site"


def page(name: str) -> str:
    return (FIX / f"imgsearch-{name}.html").read_text()


def test_unsplash_skips_paid_photos_and_credits_the_photographer():
    got = images.unsplash(page("unsplash"))
    assert len(got) == 1 and got[0]["kind"] == "free"
    assert got[0]["url"] == "https://images.unsplash.com/photo-1625826415766-001bd75aaf52?w=2000&q=80&fm=jpg&fit=max"
    assert got[0]["credit"] == "Photo by Iftekhar Nibir on Unsplash" and got[0]["title"] == "waterfalls near green trees during daytime"
    assert got[0]["page"] == "https://unsplash.com/photos/waterfalls-near-green-trees-during-daytime-XKCFg-wJx8M"
    assert (got[0]["width"], got[0]["height"]) == (3000, 4000)


def test_pexels_credits_from_the_page_data():
    got = images.pexels(page("pexels"))
    assert [g["url"] for g in got] == ["https://images.pexels.com/photos/28051279/pexels-photo-28051279.jpeg?auto=compress&cs=tinysrgb&w=2000",
                                       "https://images.pexels.com/photos/1234567/pexels-photo-1234567.jpeg?auto=compress&cs=tinysrgb&w=2000"]
    assert got[0]["credit"] == "Photo by S Roy on Pexels" and got[1]["credit"] == "Pexels"
    assert got[0]["title"] == "A breathtaking view of a towering waterfall in Meghalaya, India." and got[1]["title"] == "Root bridge"
    assert got[0]["page"] == "https://www.pexels.com/photo/waterfall-28051279/" and (got[0]["width"], got[0]["height"]) == (4160, 6240)


def test_bing_keeps_originals_with_their_sites():
    got = images.bing(page("bing"))
    assert got[0] == {"url": "https://static.toiimg.com/photo/51287966.cms", "kind": "web", "credit": "timesofindia.indiatimes.com",
                      "page": "https://timesofindia.indiatimes.com/travel/x", "title": "Jadoh, Meghalaya", "width": 0, "height": 0}
    # http:// dropped, and the Dreamstime result too: a stock site's watermarked preview
    assert [g["credit"] for g in got] == ["timesofindia.indiatimes.com", "reifytravels.com", "tecbikepartsusa.com"]
    assert got[1]["title"] == "Doh Khleh & Jadoh"


def test_stock_sites_previews_are_known_by_their_host():
    stock = ["https://thumbs.dreamstime.com/b/gangtok.jpg", "https://www.shutterstock.com/image-photo/x-260nw-1.jpg",
             "https://c8.alamy.com/comp/X/x.jpg", "https://media.istockphoto.com/id/1/photo/x.jpg",
             "https://media.gettyimages.com/id/1/photo/x.jpg", "https://www.gettyimages.co.uk/detail/1",
             "https://us.123rf.com/450wm/x.jpg", "https://st.depositphotos.com/1/x.jpg",
             "https://stock.adobe.com/in/images/x/1", "https://t3.ftcdn.net/jpg/01/x.jpg",
             "https://www.adobestock.com/x.jpg", "https://static.bigstockphoto.com/x.jpg",
             "https://cdn.vectorstock.com/i/x.jpg", "https://comps.canstockphoto.com/x.jpg"]
    for url in stock:
        assert images.is_stock_preview(url), url
    free = ["https://static.toiimg.com/photo/51287966.cms", "https://images.unsplash.com/photo-1.jpg",
            "https://notalamy.com/a.jpg", "https://www.adobe.com/x.jpg", "not an address", ""]
    for url in free:
        assert not images.is_stock_preview(url), url


class FakeBrowser:
    def __init__(self, fail=()):
        self.fail, self.closed, self.opened = set(fail), [], []

    async def open(self, tab, url, isolated=False):
        self.opened.append(url)
        if any(f in url for f in self.fail):
            from odie.browser.engine import BrowserError
            raise BrowserError("The page didn't open: it couldn't be reached.")

    async def scroll(self, tab, down=True):
        pass

    async def html(self, tab):
        return page(tab.split(":")[1])

    async def close_tab(self, tab):
        self.closed.append(tab)


async def test_find_fills_both_groups_and_says_what_failed():
    async def all_load(urls):
        return set(urls)
    b = FakeBrowser(fail=["pexels.com"])
    got = await images.find(b, "jadoh meghalaya", count=4, loads=all_load)
    assert [p["kind"] for p in got["free"]] == ["free"] and [p["kind"] for p in got["web"]] == ["web", "web"]
    assert all("Shock" not in p["title"] for p in got["web"])  # a web photo must share a word with the ask
    assert got["failed"] == ["Pexels: The page didn't open: it couldn't be reached."]
    assert sorted(t.rsplit(":", 1)[0] for t in b.closed) == ["images:bing", "images:pexels", "images:unsplash"]
    assert any("q=jadoh+meghalaya" in u or "jadoh-meghalaya" in u for u in b.opened)

    async def none_load(urls):
        return set()
    nothing = await images.find(FakeBrowser(), "meghalaya", loads=none_load)
    assert nothing["free"] == [] and nothing["web"] == []


def test_the_text_says_which_photos_to_use_where():
    t = images.find_text({"free": [{"url": "https://images.unsplash.com/a", "title": "hills", "credit": "Photo by A on Unsplash"}],
                          "web": [], "failed": []})
    assert "Free photos" in t and "covers" in t and "Photo by A on Unsplash" in t and "No web photos" in t
    assert "UNTRUSTED" in t  # titles come from other people's pages


def test_images_on_this_page_text():
    t = images.page_images_text([{"url": "https://ex.com/a.jpg", "label": "Orchidale Homestay"}], "https://www.airbnb.co.in/s/x")
    assert "Images on this page" in t and "credit: airbnb.co.in" in t and "Orchidale Homestay" in t
    assert images.page_images_text([], "https://ex.com") == ""


def test_the_images_rule_follows_the_browser():
    from odie.agent.prompt import ALL_CAPS, Who, rules_text
    with_browser = rules_text(Who(caps=ALL_CAPS | {"browser"}), gated=True, extra=[])
    without = rules_text(Who(caps=ALL_CAPS), gated=True, extra=[])
    assert "find_images" in with_browser and "Images on this page" in with_browser and "odie-images" in with_browser
    assert "find_images" not in without and "web_search lists them under 'Images found'" in without
    assert with_browser.count("- Images:") == 1 and without.count("- Images:") == 1


async def test_two_searches_at_once_never_share_a_tab():
    import asyncio

    class Recording(FakeBrowser):
        async def open(self, tab, url, isolated=False):
            self.opened.append(tab)
            await asyncio.sleep(0.01)

    async def all_load(urls):
        return set(urls)
    b = Recording()
    await asyncio.gather(images.find(b, "meghalaya", loads=all_load), images.find(b, "nvidia", loads=all_load))
    assert len(b.opened) == 6 and len(set(b.opened)) == 6  # each search reads its own three tabs
    assert sorted(b.closed) == sorted(b.opened)
