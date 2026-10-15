"""Reading deck Markdown: every line kind, the automatic layouts case by case, forced layouts, limits with their
messages, a stock deck with no photos, and today's Markdown unchanged."""
import pytest

from odie.decks.model import DeckError, inline, parse

MEGHALAYA = """# MEGHALAYA
kicker: The complete trip guide · October 2026
image: https://ex.com/laitlum.jpg (credit: Chalo Hoppo)
The abode of clouds. Seven days, plotted to the kilometre.

# October is the sweet spot
kicker: Why go now
image: https://ex.com/pools.jpg
- **Post-monsoon green** — hills at their emerald best
- **Clear skies** — the mist lifts
> Dawki is clearest from November

# The classic 7-day circuit
kicker: The plan
1. Umiam → Shillong — lake stop on the drive up
2. Shillong — Iewduh market, Shillong Peak
3. Laitlum → Sohra — canyon rim, Nohkalikai

# Where to stay
## Ri Kynjai
image: https://ex.com/rk.jpg (credit: Ri Kynjai)
meta: Umiam Lake · Resort
45 acres on the water; **balconies over the lake**.
## Polo Towers
meta: Shillong · 4★ Hotel
Police Bazaar location; **from ~₹4,200**.

# Budget
stat: ₹3.5–4.5k — Cab per day
stat: ₹60–80k — 7 days for two
- **Flights** — Pune–Guwahati return, ₹6–10k pp

# Spend by day
```chart
{"type": "bar", "x": ["Day 1", "Day 2"], "series": [{"name": "₹", "data": [9000, 7000]}]}
```

# Dawki
image: https://ex.com/dawki1.jpg (credit: Random Voyager)
caption: The levitating boats
image: https://ex.com/dawki2.jpg

# Day 5 · the trek
layout: split
image: https://ex.com/bridge.jpg
- **3,500 steps** down from Tyrna

# Thanks
"""

STOCK = """# Nvidia, Q2 FY27
kicker: Quarterly review · October 2026
Data centre still carries the quarter

# The quarter in numbers
stat: $46.7B — Revenue, up 56% y/y
stat: 72.4% — Gross margin
stat: $1.05 — EPS, ahead by 4%

# Revenue by segment
```chart
{"type": "bar", "x": ["Data centre", "Gaming", "Pro viz", "Auto"], "series": [{"name": "Q2", "data": [41.1, 4.3, 0.6, 0.6]}], "unit": "$B"}
```

# What moved the stock
- **Blackwell ramp** — supply caught up with orders
- **China** — H20 sales paused, guided out
- **Buybacks** — $60B added to the programme

# Bull and bear
## The bull case
Sovereign AI and inference demand broaden the buyers.
## The bear case
Customer concentration: four clouds are half of revenue.

# Timeline
1. Aug 27 — results
2. Sep 10 — investor day
3. Nov 19 — Q3 results

# Questions
"""


def test_a_full_deck_reads_into_its_layouts():
    d = parse(MEGHALAYA)
    assert [s.layout for s in d.slides] == ["cover", "photo", "steps", "cards", "stats", "chart", "gallery", "split", "closing"]
    cover, photo, steps, cards, stats, chart, gallery, split, _ = d.slides
    assert cover.kicker.startswith("The complete") and cover.image == "https://ex.com/laitlum.jpg" and cover.credit == "Chalo Hoppo"
    assert cover.subtitle.startswith("The abode of clouds")
    assert photo.items[0].lead == "Post-monsoon green" and photo.items[0].text == "hills at their emerald best"
    assert photo.notes == ["Dawki is clearest from November"]
    assert steps.steps[0].title == "Umiam → Shillong" and steps.steps[0].detail == "lake stop on the drive up"
    assert cards.cards[0].meta == "Umiam Lake · Resort" and cards.cards[0].image == "https://ex.com/rk.jpg" and cards.cards[1].image == ""
    assert cards.cards[0].lines == ["45 acres on the water; **balconies over the lake**."]
    assert stats.stats[1].value == "₹60–80k" and stats.stats[1].label == "7 days for two" and stats.items[0].lead == "Flights"
    assert chart.chart["x"] == ["Day 1", "Day 2"]
    assert gallery.gallery[0] == ("https://ex.com/dawki1.jpg", "Random Voyager", "The levitating boats")
    assert gallery.gallery[1] == ("https://ex.com/dawki2.jpg", "", "")
    assert split.image == "https://ex.com/bridge.jpg"
    assert d.title == "MEGHALAYA"
    assert ("https://ex.com/rk.jpg", "Ri Kynjai") in d.photo_refs() and len(d.photo_refs()) == 6


def test_a_stock_deck_with_no_photos_reads_into_its_layouts():
    d = parse(STOCK)
    assert [s.layout for s in d.slides] == ["cover", "stats", "chart", "points", "cards", "steps", "closing"]
    assert d.photo_refs() == [] and d.slides[2].chart["unit"] == "$B"
    assert d.slides[5].steps[2].title == "Nov 19" and d.slides[5].steps[2].detail == "Q3 results"


def test_old_markdown_still_reads():
    d = parse("# Home servers\nWhat a home server can do\n\n# Why now\n- Hardware is cheap\n  - A home server is enough\n> Mention 32 GB\n\n"
              "# Plans\n| Plan | Price |\n| --- | --- |\n| Mini | ₹60k |\n")
    assert [s.layout for s in d.slides] == ["cover", "points", "table"]
    assert d.slides[1].items[0].sub == ["A home server is enough"] and d.slides[1].notes == ["Mention 32 GB"]
    assert d.slides[2].table == [["Plan", "Price"], ["Mini", "₹60k"]]
    assert d.title == "Home servers" and parse("# A\n", "Given").title == "Given"


@pytest.mark.parametrize("md,expected", [
    ("# A\n\n# Big idea\nOne line under it\n", "section"),
    ("# A\n\n# Q\nquote: \"Grown, not built\" — Khasi saying\n", "quote"),
    ("# A\n\n# Only one step\n1. Go — now\n", "points"),
    ("# A\n\n# One stat\nstat: 5 — things\n", "points"),
    ("# A\n\n# Forced\nlayout: points\nimage: https://ex.com/a.jpg\n- x\n", "points"),
    ("# A\n\n# Thanks\n\n# Not last\n- x\n", "section"),
])
def test_layout_choices(md, expected):
    assert parse(md).slides[1].layout == expected


def test_a_quote_and_small_counts_become_bullets():
    d = parse("# A\n\n# Q\nquote: \"Grown, not built\" — Khasi saying\n\n# S\n1. Go — now\nstat: 5 — things\n")
    assert d.slides[1].quote == "Grown, not built" and d.slides[1].quote_by == "Khasi saying"
    assert [(i.lead, i.text) for i in d.slides[2].items] == [("Go", "now"), ("5", "things")]


@pytest.mark.parametrize("md,message", [
    ("# A\n\n# Long\n" + "".join(f"- point {i}\n" for i in range(9)), "Slide 2 has 9 bullets; keep 6 or split it."),
    ("# A\n" + "".join(f"\n# S{i}\n- x\n" for i in range(31)), "32 slides"),
    ("# A\n\n# B\nlayout: hologram\n- x\n", "Slide 2: there's no layout called hologram"),
    ("# A\n\n# C\n```chart\n{\"type\": \"pie\"}\n```\n", "Slide 2: the chart needs x and series"),
    ("# A\n\n# C\n```chart\nnot json\n```\n", "Slide 2: the chart needs x and series"),
    ("# " + "x" * 90 + "\n", "Slide 1's title is over 80 characters"),
    ("# A\n\n# B\n- " + "y" * 170 + "\n", "Slide 2 has a bullet over 160 characters"),
    ("# A\n\n# Cards\n" + "".join(f"## C{i}\nx\n" for i in range(5)), "Slide 2 has 5 cards; keep 4"),
    ("", "Start each slide with"),
    ("no heading here\n- x\n", "Start each slide with"),
])
def test_limits_say_what_to_cut(md, message):
    with pytest.raises(DeckError) as e:
        parse(md)
    assert message in str(e.value)


def test_inline_bold():
    assert inline("from **₹4,200** incl. taxes") == [("from ", False), ("₹4,200", True), (" incl. taxes", False)]
    assert inline("plain") == [("plain", False)]
    assert inline("**all**") == [("all", True)]


def test_old_shapes_still_read():
    d = parse("# Setup\n- Install it\n```bash\n# install it\n- not a bullet\nbrew install uv\n```\n- Done\n---\n# Two\nsub\n")
    assert len(d.slides) == 2
    assert [i.text for i in d.slides[0].items] == ["Install it", "# install it", "- not a bullet", "brew install uv", "Done"]
    for sep in ("|-|-|", "| :-: | :-: |", "|:--|--:|"):
        assert parse(f"# T\n| A | B |\n{sep}\n| 1 | 2 |\n").slides[0].table == [["A", "B"], ["1", "2"]], sep
    rows = "\n".join(f"| item {i} | {i} |" for i in range(20))
    assert len(parse(f"# A\n\n# Table\n| A | B |\n| --- | --- |\n{rows}\n").slides[1].table) == 21  # up to 20 rows fit
    with pytest.raises(DeckError, match="table rows"):
        parse("# A\n\n# T\n| A |\n| --- |\n" + "\n".join(f"| {i} |" for i in range(21)))


@pytest.mark.parametrize("md,message", [
    ("# A\n\n# S\nlayout: stats\n- x\n", "Slide 2: layout stats needs"),
    ("# A\n\n# T\nlayout: table\n- x\n", "Slide 2: layout table needs"),
    ("# A\n\n# C\nlayout: chart\n- x\n", "Slide 2: layout chart needs"),
    ("# A\n\n# S\nlayout: steps\n- x\n", "Slide 2: layout steps needs"),
    ("# A\n\n# C\nlayout: cards\n- x\n", "Slide 2: layout cards needs"),
    ("# A\n\n# G\nlayout: gallery\n- x\n", "Slide 2: layout gallery needs"),
    ("# A\n\n# P\nlayout: photo\n- x\n", "Slide 2: layout photo needs"),
    ("# A\n\n# P\nlayout: split\n- x\n", "Slide 2: layout split needs"),
    ("# A\n\n# Q\nlayout: quote\n- x\n", "Slide 2: layout quote needs"),
])
def test_a_forced_layout_without_its_content_says_so(md, message):
    with pytest.raises(DeckError) as e:
        parse(md)
    assert message in str(e.value)


@pytest.mark.parametrize("md,message", [
    ("# A\n\n# Chart\n```chart\n{\"x\": [\"a\"], \"series\": [{\"name\": \"s\", \"data\": [1]}]}\n```\n- a bullet\n", "Slide 2 has a chart and 1 bullet"),
    ("# A\n\n# T\n| a | b |\n| 1 | 2 |\n- a bullet\n", "Slide 2 has a table and 1 bullet"),
    ("# A\n\n# C\n- a bullet\n## One\nx\n## Two\ny\n", "Slide 2 has cards and 1 bullet"),
    ("# Cover\nlayout: cover\n- one\n", "Slide 1 is the cover"),
    ("# A\n\n# S\n1. a — b\n2. c — d\n3. e — f\n- a bullet\n", "Slide 2 has steps and 1 bullet"),
    ("# A\n\n# Q\nquote: \"x\" — y\n- a bullet\n", "Slide 2 has a quote and 1 bullet"),
    ("# A\n\n# P\nimage: https://ex.com/1.jpg\nimage: https://ex.com/2.jpg\n- a bullet\n", "Slide 2 has 2 photos and bullets"),
])
def test_content_a_layout_would_drop_is_refused(md, message):
    with pytest.raises(DeckError) as e:
        parse(md)
    assert message in str(e.value)


def test_a_quote_with_a_colon_keeps_its_words():
    s = parse('# A\n\n# Q\nquote: "He said: go now" — Someone Wise\n').slides[1]
    assert s.quote == "He said: go now" and s.quote_by == "Someone Wise"
    t = parse('# A\n\n# Q\nquote: "Just the words"\n').slides[1]
    assert t.quote == "Just the words" and t.quote_by == ""


def test_a_first_slide_with_content_is_not_a_cover():
    d = parse("# Setup steps\n- Install it\n- Run it\n\n# B\n- x\n")
    assert d.slides[0].layout == "points" and [i.text for i in d.slides[0].items] == ["Install it", "Run it"]


def test_steps_stats_and_sections_keep_their_photo():
    d = parse("# A\n\n# Day 1\nimage: https://ex.com/d1.jpg (credit: X)\n1. a — b\n2. c — d\n3. e — f\n\n"
              "# Budget\nimage: https://ex.com/b.jpg\nstat: 1 — one\nstat: 2 — two\n\n# Part two\nimage: https://ex.com/s.jpg\nA line\n")
    assert [s.layout for s in d.slides[1:]] == ["steps", "stats", "section"]
    assert [s.image for s in d.slides[1:]] == ["https://ex.com/d1.jpg", "https://ex.com/b.jpg", "https://ex.com/s.jpg"]


@pytest.mark.parametrize("md,message", [
    ("# A\n\n# C\nimage: https://ex.com/x.jpg\n```chart\n{\"x\": [\"a\"], \"series\": [{\"name\": \"s\", \"data\": [1]}]}\n```\n", "Slide 2: a chart slide can't hold a photo"),
    ("# A\n\n# T\nimage: https://ex.com/x.jpg\n| a | b |\n| 1 | 2 |\n", "Slide 2: a table slide can't hold a photo"),
])
def test_a_photo_a_layout_would_drop_is_refused(md, message):
    with pytest.raises(DeckError) as e:
        parse(md)
    assert message in str(e.value)
