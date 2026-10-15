"""The HTML deck: every layout in every theme renders one 1920x1080 section; text is escaped; photos are inline and
nothing remote is left; a deck without photos is finished; layouts use the full width; credits and page numbers."""
import re

import pytest
from PIL import Image

from odie.decks.html import render_html
from odie.decks.model import parse
from odie.decks.photos import Photo
from odie.decks.themes import THEMES, theme
from tests.test_decks_model import MEGHALAYA, STOCK


@pytest.fixture
def photos(tmp_path):
    p = tmp_path / "x.jpg"
    Image.new("RGB", (64, 36), (10, 80, 50)).save(p, "JPEG")
    return {r: Photo(r, p, 64, 36, c or "ex.com") for r, c in parse(MEGHALAYA).photo_refs()}


@pytest.mark.parametrize("name", list(THEMES))
def test_every_layout_renders_in_every_theme(name, photos):
    deck = parse(MEGHALAYA)
    html = render_html(deck, theme(name), photos)
    assert html.count('<section class="slide') == len(deck.slides)
    for layout in ("cover", "photo", "steps", "cards", "stats", "chart", "gallery", "split", "closing"):
        assert f"l-{layout}" in html
    assert "<svg" in html  # the chart
    assert "01 / 09" in html and "photo: Chalo Hoppo" in html
    assert html.count("data:image/jpeg;base64,") >= 6


@pytest.mark.parametrize("name", list(THEMES))
def test_a_deck_without_photos_is_finished(name):
    html = render_html(parse(STOCK), theme(name), {})
    assert "data:image" not in html and "<svg" in html and html.count('<section class="slide') == 7
    assert "photo:" not in html  # no credits without photos
    for layout in ("cover", "stats", "chart", "points", "cards", "steps", "closing"):
        assert f"l-{layout}" in html


def test_section_quote_and_table_render(photos):
    md = ("# A\n\n# Big idea\nOne line under it\n\n# Q\nquote: \"Grown, not built\" — Khasi saying\n\n"
          "# Plans\n| Plan | Price |\n| --- | --- |\n| Mini | ₹60k |\n")
    html = render_html(parse(md), theme("minimal"), {})
    assert "l-section" in html and "l-quote" in html and "l-table" in html and "<table" in html and "Khasi saying" in html


def test_text_is_escaped_and_nothing_remote_is_left(photos):
    md = ('# <img src=x onerror=alert(1)>\n\n# </style><script>alert(1)</script>\n- url(http://evil.com/x) **<b>**\n'
          "image: https://ex.com/missing.jpg\n")
    html = render_html(parse(md), theme("editorial"), photos)
    assert "<script>" not in html and "<img src=x" not in html
    assert "&lt;/style&gt;" in html and "&lt;img src=x onerror=alert(1)&gt;" in html
    body = html.split("</head>", 1)[1]
    assert not re.search(r"""(src|href)\s*=\s*["']?https?:""", body)
    assert "url(http://evil.com/x)" in body and "url(http" not in body.replace("url(http://evil.com/x)", "")
    assert "Content-Security-Policy" in html and "default-src 'none'" in html


def test_a_missing_photo_uses_the_no_photo_version():
    md = "# Cover\nimage: https://ex.com/gone.jpg\n\n# Two\nimage: https://ex.com/gone.jpg\n- a\n"
    html = render_html(parse(md), theme("editorial"), {})
    assert "data:image/jpeg" not in html and "l-cover" in html and "no-photo" in html


def test_layouts_use_the_full_width(photos):
    html = render_html(parse(MEGHALAYA), theme("editorial"), photos)
    widths = [int(w) for w in re.findall(r"max-width:\s*(\d+)px", html)]
    assert all(w <= 1600 for w in widths)
    assert "--pad-x:120px" in html  # 1680 of 1920 px is content: 87.5%
    assert "@page{size:1920px 1080px;margin:0}" in html


def test_unknown_theme_is_editorial():
    assert theme("neon").name == "editorial" and theme(None).name == "editorial" and theme("Warm").name == "warm"


def test_stat_values_fit_their_tiles():
    md = "# A\n\n# Budget\n" + "".join(f"stat: ₹3.5–4.5k — label {i}\n" for i in range(4))
    html = render_html(parse(md), theme("editorial"), {})
    px = int(re.search(r'class="value" style="font-size:(\d+)px', html)[1])
    tile = (1680 - 32 * 3) / 4 - 80
    assert px * 0.62 * len("₹3.5–4.5k") <= tile and "white-space:nowrap" in html


def test_few_items_get_bigger_type():
    md = ("# A\n\n# Moves\n- **Blackwell ramp** — supply caught up\n- **China** — paused\n\n"
          "# When\n1. Aug 27 — results\n2. Sep 10 — investor day\n3. Nov 19 — Q3\n\n"
          "# Cases\n## Bull\nDemand broadens.\n## Bear\nConcentration.\n")
    html = render_html(parse(md), theme("minimal"), {})
    assert 'class="lead-big"' in html  # two or three bullets read as statements
    assert re.search(r'class="num" style="font-size:(\d+)px', html)[1] == "110"
    assert re.search(r'class="name" style="font-size:(\d+)px', html)[1] == "52"


def test_a_full_week_and_four_text_cards_fill_the_slide():
    md = ("# A\n\n# Week\n" + "".join(f"{i}. Day {i} — a long-ish description of what happens on this day\n" for i in range(1, 8))
          + "\n# Stays\n" + "".join(f"## Stay {i}\nmeta: Somewhere · Homestay\nA short line about it.\n" for i in range(4)))
    html = render_html(parse(md), theme("editorial"), {})
    tile = int(re.search(r'class="tile" style="min-height:(\d+)px', html)[1])
    detail = int(re.search(r'class=d style=font-size:(\d+)px', html)[1])
    card = int(re.search(r'class="card" style="min-height:(\d+)px', html)[1])
    assert tile >= 470 and detail >= 22 and card >= 500


def test_steps_stats_and_sections_wear_their_photo(photos, tmp_path):
    md = ("# A\n\n# Day 1\nimage: https://ex.com/d1.jpg (credit: Day photo)\n1. a — b\n2. c — d\n3. e — f\n\n"
          "# Budget\nimage: https://ex.com/b.jpg\nstat: 1 — one\nstat: 2 — two\n\n# Part two\nimage: https://ex.com/s.jpg\nA line\n")
    p = tmp_path / "y.jpg"
    Image.new("RGB", (64, 36), (10, 80, 50)).save(p, "JPEG")
    pics = {r: Photo(r, p, 64, 36, c or "ex.com") for r, c in parse(md).photo_refs()}
    html = render_html(parse(md), theme("minimal"), pics)
    for layout in ("steps", "stats", "section"):
        section = re.search(rf'<section class="slide l-{layout}[^"]*">.*?</section>', html, re.S)[0]
        assert "has-photo" in section.split(">", 1)[0] and "data:image/jpeg" in section, layout
    assert "photo: Day photo" in html
