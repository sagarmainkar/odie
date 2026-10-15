"""Deck Markdown (spec part 1): today's make_slides Markdown ("# " a slide, "- " bullets, "> " notes, "| a | b |"
tables) plus a few lines that carry design: kicker, image (with credit), caption, layout, "## " cards with meta, numbered
steps, stats, a chart block, a quote. Code picks each slide's layout from what it holds; the limits are checked before
anything is built, and each says which slide and what to cut."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

LAYOUTS = ("cover", "section", "points", "photo", "split", "cards", "steps", "stats", "table", "chart", "gallery", "quote", "closing")
CLOSINGS = {"thanks", "thank you", "questions", "q&a", "the end", "thank you all"}
MAX_SLIDES, MAX_TITLE, MAX_BULLETS, MAX_TEXT, MAX_ITEMS, MAX_STEPS, MAX_CARD_LINES = 30, 80, 6, 160, 4, 7, 3
MAX_ROWS, MAX_COLS, MAX_X = 20, 5, 24  # a long table shrinks to fit, as the old builder's did

_IMAGE = re.compile(r"^image:\s*(\S+)(?:\s*\(credit:\s*([^)]*)\))?\s*$", re.I)
_KEY = re.compile(r"^(kicker|caption|layout|meta|quote|stat):\s*(.*)$", re.I)
_STEP = re.compile(r"^(\d{1,2})[.)]\s+(.+)$")
_BULLET = re.compile(r"^(\s*)[-*]\s+(.+)$")
_LEAD = re.compile(r"^\*\*(.+?)\*\*\s*(?:[—–-]\s*|:\s*)?(.*)$")
_SEP = re.compile(r"\s+[—–]\s+|\s+-\s+|\s+\|\s+|:\s+")
_CELL_RULE = re.compile(r"^:?-+:?$")
_HR = re.compile(r"^(-{3,}|\*{3,}|_{3,})$")


class DeckError(ValueError):
    """What to change, in a sentence the model can act on."""


@dataclass
class Item:
    lead: str
    text: str
    sub: list[str] = field(default_factory=list)


@dataclass
class Card:
    title: str
    meta: str = ""
    lines: list[str] = field(default_factory=list)
    image: str = ""
    credit: str = ""


@dataclass
class Step:
    title: str
    detail: str


@dataclass
class Stat:
    value: str
    label: str


@dataclass
class Slide:
    title: str
    layout: str = ""
    kicker: str = ""
    subtitle: str = ""
    image: str = ""
    credit: str = ""
    caption: str = ""
    items: list[Item] = field(default_factory=list)
    cards: list[Card] = field(default_factory=list)
    steps: list[Step] = field(default_factory=list)
    stats: list[Stat] = field(default_factory=list)
    table: list[list[str]] = field(default_factory=list)
    chart: dict | None = None
    quote: str = ""
    quote_by: str = ""
    gallery: list[tuple[str, str, str]] = field(default_factory=list)  # (ref, credit, caption)
    notes: list[str] = field(default_factory=list)


@dataclass
class Deck:
    title: str
    slides: list[Slide]

    def photo_refs(self) -> list[tuple[str, str]]:
        refs: list[tuple[str, str]] = []
        for s in self.slides:
            refs += [(ref, credit) for ref, credit, _ in s.gallery]
            refs += [(c.image, c.credit) for c in s.cards if c.image]
        return list(dict.fromkeys(refs))


def inline(text: str) -> list[tuple[str, bool]]:
    """Text with **bold** as (piece, bold) pairs."""
    parts = re.split(r"\*\*(.+?)\*\*", text or "")
    return [(p, i % 2 == 1) for i, p in enumerate(parts) if p]


def _split(text: str) -> tuple[str, str]:
    m = _SEP.search(text)
    return (text[:m.start()].strip(), text[m.end():].strip()) if m else (text.strip(), "")


def _split_last(text: str) -> tuple[str, str]:
    """A quote and its author: split on the last dash only (a colon belongs to the quote)."""
    found = list(re.finditer(r"\s+[—–]\s+|\s+-\s+", text))
    if not found:
        return text.strip(), ""
    m = found[-1]
    return text[:m.start()].strip(), text[m.end():].strip()


def _item(text: str) -> Item:
    m = _LEAD.match(text.strip())
    return Item(m[1].strip(), m[2].strip()) if m else Item("", text.strip())


def _chart(lines: list[str], n: int) -> dict:
    bad = DeckError(f'Slide {n}: the chart needs x and series, like {{"type": "bar", "x": ["A", "B"], '
                    f'"series": [{{"name": "Sales", "data": [3, 5]}}]}}.')
    try:
        c = json.loads("\n".join(lines))
    except ValueError:
        raise bad from None
    if not isinstance(c, dict) or not isinstance(c.get("x"), list) or not c["x"]:
        raise bad
    if not isinstance(c.get("series"), list) or not c["series"]:
        raise bad
    x = [str(v)[:40] for v in c["x"]]
    series = []
    for s in c["series"][:4]:
        if not isinstance(s, dict) or not isinstance(s.get("data"), list) or len(s["data"]) != len(x):
            raise bad
        try:
            data = [float(v) for v in s["data"]]
        except (TypeError, ValueError):
            raise bad from None
        series.append({"name": str(s.get("name") or "")[:40], "data": data})
    if len(x) > MAX_X:
        raise DeckError(f"Slide {n}: the chart has {len(x)} labels; keep {MAX_X}.")
    return {"type": "line" if c.get("type") == "line" else "bar", "x": x, "series": series, "unit": str(c.get("unit") or "")[:6],
            "title": str(c.get("title") or "")[:80]}


def choose(s: Slide, i: int, n: int) -> str:
    if s.layout:
        return s.layout
    plain = not (s.items or s.cards or s.steps or s.stats)
    if i == 0 and plain and not (s.table or s.chart or s.quote or len(s.gallery) > 1):
        return "cover"  # a first slide that holds content gets that content's layout instead
    if i == n - 1 and plain and s.title.strip().lower().rstrip("!.?") in CLOSINGS:
        return "closing"
    if s.chart:
        return "chart"
    if s.table:
        return "table"
    if len(s.cards) >= 2:
        return "cards"
    if len(s.steps) >= 3:
        return "steps"
    if len(s.stats) >= 2:
        return "stats"
    if len(s.gallery) >= 2 and not s.items:
        return "gallery"
    if s.quote:
        return "quote"
    if s.items and s.image:
        return "photo"
    if plain:
        return "section"
    return "points"


def _settle(s: Slide) -> None:
    """What the chosen layout doesn't show as itself becomes bullets: a lone step or stat, a single card."""
    if s.layout != "steps" and s.steps:
        s.items += [Item(st.title, st.detail) for st in s.steps]
        s.steps = []
    if s.layout != "stats" and s.stats:
        s.items += [Item(st.value, st.label) for st in s.stats]
        s.stats = []
    if s.layout != "cards" and s.cards:
        s.items += [Item(c.title, " ".join(c.lines)) for c in s.cards]
        s.cards = []


NEEDS = {"stats": ("stat: lines", lambda s: s.stats), "table": ("a table (| a | b | rows)", lambda s: s.table),
         "chart": ("a ```chart block", lambda s: s.chart), "steps": ("numbered steps (1. …)", lambda s: s.steps),
         "cards": ("## cards", lambda s: s.cards), "gallery": ("image: lines", lambda s: s.gallery),
         "photo": ("an image: line", lambda s: s.image), "split": ("an image: line", lambda s: s.image),
         "quote": ("a quote: line", lambda s: s.quote)}
HOLDS = {"chart": "a chart", "table": "a table", "cards": "cards", "steps": "steps", "quote": "a quote"}


def _whole(s: Slide, n: int) -> None:
    """Nothing the model wrote is dropped without a word: a layout gets what it draws, and only what it draws."""
    if s.layout in NEEDS and not NEEDS[s.layout][1](s):
        raise DeckError(f"Slide {n}: layout {s.layout} needs {NEEDS[s.layout][0]}; add it, or drop the layout: line.")
    k = len(s.items)
    bullets = f"{k} bullet{'s' if k != 1 else ''}"
    if k and s.layout in ("cover", "section", "closing"):
        what = "the cover" if s.layout == "cover" else f"a {s.layout} slide"
        raise DeckError(f"Slide {n} is {what}: it shows the title, one line and a photo. Move its {bullets} to a new slide.")
    if k and s.layout in HOLDS:
        raise DeckError(f"Slide {n} has {HOLDS[s.layout]} and {bullets}; keep one, or split it into two slides.")
    if s.image and s.layout in ("chart", "table", "cards"):
        where = "put it on a card (an image: line under its ## name)" if s.layout == "cards" else "give the photo a slide of its own"
        raise DeckError(f"Slide {n}: a {s.layout} slide can't hold a photo; {where}.")
    if len(s.gallery) > 1 and s.layout != "gallery":
        if k:
            raise DeckError(f"Slide {n} has {len(s.gallery)} photos and bullets; keep one photo, or put the photos on a slide of their own.")
        raise DeckError(f"Slide {n} can show one photo here, not {len(s.gallery)}; keep one, or make it a gallery slide.")


def _check(s: Slide, n: int) -> None:
    _whole(s, n)

    def too_many(what: str, k: int, keep: int) -> None:
        if k > keep:
            raise DeckError(f"Slide {n} has {k} {what}; keep {keep} or split it.")
    if len(s.title) > MAX_TITLE:
        raise DeckError(f"Slide {n}'s title is over {MAX_TITLE} characters; shorten it.")
    too_many("bullets", len(s.items), MAX_BULLETS)
    too_many("cards", len(s.cards), MAX_ITEMS)
    too_many("stats", len(s.stats), MAX_ITEMS)
    too_many("steps", len(s.steps), MAX_STEPS)
    too_many("photos", len(s.gallery) if s.layout == "gallery" else 0, MAX_ITEMS)
    too_many("table rows", max(0, len(s.table) - 1), MAX_ROWS)
    if any(len(r) > MAX_COLS for r in s.table):
        raise DeckError(f"Slide {n}'s table has more than {MAX_COLS} columns; keep {MAX_COLS}.")
    texts = [f"{i.lead} {i.text}" for i in s.items] + [st.detail for st in s.steps]
    if any(len(t.strip()) > MAX_TEXT for t in texts):
        raise DeckError(f"Slide {n} has a bullet over {MAX_TEXT} characters; shorten it.")
    for c in s.cards:
        if len(c.lines) > MAX_CARD_LINES or any(len(x) > MAX_TEXT for x in c.lines):
            raise DeckError(f"Slide {n}'s card {c.title!r} is too long; keep {MAX_CARD_LINES} short lines.")


def parse(markdown: str, title: str = "") -> Deck:
    slides: list[Slide] = []
    s: Slide | None = None
    card: Card | None = None
    chart: list[str] | None = None
    code = False  # inside a ``` block that isn't a chart: its lines are kept as they are, as bullets
    last_image: list | None = None  # the gallery entry a caption: line belongs to
    for raw in (markdown or "").splitlines():
        line = raw.rstrip()
        if code:
            if line.strip().startswith("```"):
                code = False
            elif line.strip() and s is not None:
                s.items.append(Item("", line.strip()))
            continue
        if chart is not None:
            if line.strip().startswith("```"):
                s.chart = _chart(chart, len(slides))
                chart = None
            else:
                chart.append(line)
            continue
        stripped = line.strip()
        if not stripped or _HR.match(stripped):
            continue
        if stripped.startswith("# "):
            s = Slide(stripped[2:].strip())
            slides.append(s)
            card, last_image = None, None
            continue
        if s is None:
            raise DeckError('Start each slide with "# " and its title.')
        n = len(slides)
        if stripped.startswith("```chart"):
            chart = []
            continue
        if stripped.startswith("```"):
            code = True
            continue
        if stripped.startswith("## "):
            card = Card(stripped[3:].strip())
            s.cards.append(card)
            continue
        if stripped.startswith(">"):
            s.notes.append(stripped.lstrip(">").strip())
            continue
        if m := _IMAGE.match(stripped):
            ref, credit = m[1], (m[2] or "").strip()
            if card is not None:
                card.image, card.credit = ref, credit
            else:
                entry = [ref, credit, ""]
                s.gallery.append(entry)
                last_image = entry
            continue
        if m := _KEY.match(stripped):
            key, value = m[1].lower(), m[2].strip()
            if key == "kicker":
                s.kicker = value
            elif key == "caption":
                if last_image is not None:
                    last_image[2] = value
                else:
                    s.caption = value
            elif key == "layout":
                if value.lower() not in LAYOUTS:
                    raise DeckError(f"Slide {n}: there's no layout called {value} (use one of: {', '.join(LAYOUTS)}).")
                s.layout = value.lower()
            elif key == "meta" and card is not None:
                card.meta = value
            elif key == "quote":
                q, by = _split_last(value)
                s.quote, s.quote_by = q.strip("\"“”' "), by
            elif key == "stat":
                v, label = _split(value)
                s.stats.append(Stat(v, label))
            else:
                s.subtitle = f"{s.subtitle} {stripped}".strip()
            continue
        if stripped.startswith("|"):
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            if not all(_CELL_RULE.match(c) for c in cells):
                s.table.append(cells)
            continue
        if m := _STEP.match(stripped):
            t, d = _split(m[2])
            s.steps.append(Step(t, d))
            continue
        if m := _BULLET.match(line):
            text = m[2].strip()
            if card is not None:
                card.lines.append(text)
            elif len(m[1]) >= 2 and s.items:
                s.items[-1].sub.append(text)
            else:
                s.items.append(_item(text))
            continue
        if card is not None:
            card.lines.append(stripped)
        else:
            s.subtitle = f"{s.subtitle} {stripped}".strip()
    if chart is not None and s is not None:
        s.chart = _chart(chart, len(slides))
    if not slides:
        raise DeckError('Start each slide with "# " and its title.')
    if len(slides) > MAX_SLIDES:
        raise DeckError(f"That's {len(slides)} slides; keep {MAX_SLIDES} or split the deck.")
    for i, sl in enumerate(slides):
        sl.gallery = [tuple(g) for g in sl.gallery]
        if sl.gallery:
            sl.image, sl.credit = sl.gallery[0][0], sl.gallery[0][1]
            sl.caption = sl.caption or sl.gallery[0][2]
        sl.layout = choose(sl, i, len(slides))
        _settle(sl)
        _check(sl, i + 1)
    return Deck((title or "").strip() or slides[0].title, slides)
