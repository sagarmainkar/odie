"""The HTML deck (spec part 4): one 1920x1080 <section> per slide, laid out by Odie's templates in the deck's theme.
Every layout fills the slide's width (the content box is the slide less 120 px each side). Photos are inside the file
as data URIs and a CSP refuses everything else, so rendering it reaches nothing on the network; all text is escaped.
Rendered by Odie's own browser into the PDF and the slide previews (odie.browser.engine.Browser.render)."""
from __future__ import annotations

import html as _html
import math
import re
from dataclasses import dataclass

from odie.decks.model import Deck, Item, Slide, inline
from odie.decks.photos import Photo
from odie.decks.themes import Theme

W, H = 1920, 1080
CSP = "default-src 'none'; img-src data:; style-src 'unsafe-inline'"


def e(text: str) -> str:
    return _html.escape(text or "", quote=True)


def rich(text: str) -> str:
    """Text with its **bold** kept, everything else escaped."""
    return "".join(f"<b>{e(t)}</b>" if bold else e(t) for t, bold in inline(text))


def _rgba(value: str) -> tuple[int, int, int, float]:
    m = re.match(r"rgba?\(([\d.]+),\s*([\d.]+),\s*([\d.]+)(?:,\s*([\d.]+))?\)", value)
    if m:
        return int(float(m[1])), int(float(m[2])), int(float(m[3])), float(m[4] or 1)
    h = value.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 1.0


def _mid(a: str, b: str, at: float = 0.55) -> str:
    ra, rb = _rgba(a), _rgba(b)
    r, g, bl, al = (ra[i] + (rb[i] - ra[i]) * at for i in range(4))
    return f"rgba({int(r)},{int(g)},{int(bl)},{al:.2f})"


def _css(t: Theme) -> str:
    return f"""
:root{{--bg:{t.bg};--bg2:{t.bg2};--paper:{t.paper};--ink:{t.ink};--muted:{t.muted};--accent:{t.accent};--card:{t.card};
--line:{t.card_line};--card-ink:{t.card_ink};--card-muted:{t.card_muted};--veil-a:{t.veil_a};--veil-m:{_mid(t.veil_a, t.veil_b)};
--veil-b:{t.veil_b};--head:{t.head_font};--body:{t.body_font};--head-w:{t.head_weight};--pad-x:120px;--pad-y:100px}}
@page{{size:1920px 1080px;margin:0}}
*{{margin:0;padding:0;box-sizing:border-box;-webkit-print-color-adjust:exact;print-color-adjust:exact}}
html,body{{background:var(--bg);width:1920px}}
body{{font-family:var(--body);color:var(--ink);-webkit-font-smoothing:antialiased}}
.slide{{position:relative;width:1920px;height:1080px;overflow:hidden;break-after:page;page-break-after:always;
background:linear-gradient(135deg,var(--bg) 0%,var(--bg2) 100%);color:var(--ink)}}
.slide.has-photo{{--ink:#ffffff;--muted:rgba(255,255,255,0.84);color:#fff;background:#111}}
.bg{{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;display:block}}
.veil{{position:absolute;inset:0}}
.veil.left{{background:linear-gradient(100deg,var(--veil-a) 0%,var(--veil-m) 46%,var(--veil-b) 100%)}}
.veil.bottom{{background:linear-gradient(180deg,var(--veil-b) 0%,var(--veil-m) 50%,var(--veil-a) 100%)}}
.veil.full{{background:var(--veil-a)}}
.glow{{position:absolute;right:-260px;top:-260px;width:900px;height:900px;border-radius:50%;
background:radial-gradient(circle,var(--accent) 0%,transparent 68%);opacity:.13}}
.inner{{position:absolute;top:var(--pad-y);bottom:var(--pad-y);left:var(--pad-x);right:var(--pad-x);display:flex;flex-direction:column}}
.kicker{{font-size:22px;letter-spacing:.32em;text-transform:uppercase;color:var(--accent);font-weight:700;margin-bottom:26px}}
h1,h2,.num,.value,.quote{{font-family:var(--head);font-weight:var(--head-w)}}
h1{{line-height:.96;letter-spacing:-.01em}}
h2{{line-height:1.04;letter-spacing:-.005em}}
.rule{{width:96px;height:4px;background:var(--accent);margin:40px 0 36px}}
.lede{{font-size:30px;line-height:1.5;color:var(--muted);margin-top:22px;max-width:1400px}}
.body{{flex:1;display:flex;flex-direction:column;justify-content:center;min-height:0;margin-top:44px}}
ul.pts{{list-style:none;display:grid;column-gap:72px}}
ul.pts.two{{grid-template-columns:1fr 1fr}}
ul.pts>li{{position:relative;padding:22px 0 22px 44px;border-bottom:1px solid var(--line);line-height:1.45;color:var(--muted)}}
.has-photo ul.pts>li{{border-bottom-color:rgba(255,255,255,0.18)}}
ul.pts>li::before{{content:"";position:absolute;left:0;top:calc(22px + .48em);width:14px;height:14px;border-radius:50%;background:var(--accent)}}
ul.pts>li b{{color:var(--ink);font-weight:700}}
ul.pts>li .lead{{color:var(--ink);font-weight:700}}
ul.sub{{list-style:none;margin-top:8px;font-size:.82em}}
ul.sub li::before{{content:"– ";color:var(--accent)}}
.pageno{{position:absolute;right:56px;bottom:40px;font-size:17px;letter-spacing:.28em;opacity:.6}}
.credit{{position:absolute;left:56px;bottom:40px;font-size:15px;letter-spacing:.2em;text-transform:uppercase;opacity:.6;max-width:1300px;
white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.l-cover .inner{{justify-content:flex-end;padding-bottom:40px}}
.l-cover .lede{{font-size:32px;color:var(--ink);opacity:.92;max-width:1250px;margin-top:0}}
.l-section .inner,.l-closing .inner{{justify-content:center}}
.big-index{{position:absolute;right:110px;bottom:40px;font-family:var(--head);font-weight:var(--head-w);font-size:420px;line-height:1;
color:var(--accent);opacity:.08}}
.l-closing .inner{{align-items:center;text-align:center}}
.l-closing .rule{{margin:40px auto 34px}}
.l-photo .col{{width:58%;height:100%;display:flex;flex-direction:column}}
.split{{display:grid;grid-template-columns:1fr 1fr;gap:88px;height:100%}}
.split .col{{display:flex;flex-direction:column;min-height:0}}
.frame{{position:relative;border-radius:26px;overflow:hidden;box-shadow:0 30px 70px rgba(0,0,0,.35);height:100%}}
.frame img{{width:100%;height:100%;object-fit:cover;display:block}}
.frame .cap{{position:absolute;left:0;right:0;bottom:0;padding:22px 28px;font-size:20px;color:#fff;letter-spacing:.04em;
background:linear-gradient(180deg,transparent,rgba(0,0,0,.72))}}
.grid{{display:grid;gap:32px}}
.card{{border-radius:24px;overflow:hidden;display:flex;flex-direction:column;background:var(--card);border:1px solid var(--line);color:var(--ink)}}
.card.with-photo{{background:var(--paper);color:var(--card-ink);border:0;box-shadow:0 26px 60px rgba(0,0,0,.28)}}
.card img{{width:100%;height:340px;object-fit:cover;display:block}}
.card .pad{{padding:34px 36px 38px;display:flex;flex-direction:column;gap:12px}}
.card .bar{{height:8px;background:var(--accent)}}
.card .name{{font-family:var(--head);font-weight:var(--head-w);line-height:1.15}}
.card .meta{{font-size:18px;letter-spacing:.14em;text-transform:uppercase;color:var(--muted)}}
.card.with-photo .meta{{color:var(--card-muted)}}
.card .line{{line-height:1.5;color:var(--muted)}}
.card.with-photo .line{{color:var(--card-ink)}}
.card.with-photo .line b{{color:var(--accent)}}
.card .line b{{color:var(--ink)}}
.tile{{border-radius:22px;background:var(--card);border:1px solid var(--line);padding:40px 34px;display:flex;flex-direction:column;gap:14px}}
.num{{font-size:76px;line-height:1;color:var(--accent)}}
.tile .t{{font-size:27px;font-weight:700;line-height:1.25;color:var(--ink)}}
.tile .d{{font-size:21px;line-height:1.5;color:var(--muted)}}
.value{{line-height:1;color:var(--accent);letter-spacing:-.01em}}
.tile .l{{font-size:25px;line-height:1.4;color:var(--muted)}}
.value{{white-space:nowrap}}
ul.pts.big>li{{padding:30px 0 30px 48px}}
ul.pts.big>li::before{{top:calc(30px + .5em)}}
.lead-big{{font-family:var(--head);font-weight:var(--head-w);color:var(--ink);font-size:46px;line-height:1.15;margin-bottom:10px}}
table.t{{width:100%;border-collapse:collapse;font-size:28px}}
table.t th{{text-align:left;font-size:18px;letter-spacing:.16em;text-transform:uppercase;color:var(--accent);padding:0 26px 20px;
border-bottom:2px solid var(--accent)}}
table.t td{{padding:var(--td,22px) 26px;border-bottom:1px solid var(--line);color:var(--ink)}}
table.t tr:nth-child(even) td{{background:var(--card)}}
.l-quote .inner{{justify-content:center;align-items:center;text-align:center}}
.mark{{font-family:var(--head);font-size:240px;line-height:.6;color:var(--accent);height:110px}}
.quote{{font-style:italic;font-size:76px;line-height:1.18;max-width:1500px}}
.by{{margin-top:44px;font-size:30px;letter-spacing:.12em;text-transform:uppercase;color:var(--accent)}}
.gal{{display:grid;gap:28px;height:100%}}
.has-photo .tile{{background:rgba(255,255,255,0.09);border-color:rgba(255,255,255,0.22)}}
.has-photo .big-index{{opacity:.14}}
"""


@dataclass
class _Ctx:
    photos: dict[str, Photo]
    credits: list[str]

    def photo(self, ref: str) -> Photo | None:
        p = self.photos.get(ref) if ref else None
        if p is not None and p.credit and p.credit not in self.credits:
            self.credits.append(p.credit)
        return p


def _size(text: str, sizes: tuple[tuple[int, int], ...]) -> int:
    n = len(text or "")
    for limit, px in sizes:
        if n <= limit:
            return px
    return sizes[-1][1]


def _head(s: Slide, size: tuple[tuple[int, int], ...] = ((28, 76), (44, 64), (80, 54))) -> str:
    k = f'<div class="kicker">{e(s.kicker)}</div>' if s.kicker else ""
    return f'{k}<h2 style="font-size:{_size(s.title, size)}px">{rich(s.title)}</h2>'


def _lede(s: Slide, cls: str = "lede") -> str:
    return f'<p class="{cls}">{rich(s.subtitle)}</p>' if s.subtitle else ""


def _bullets(items: list[Item], two_ok: bool = True, big: bool = False) -> str:
    if not items:
        return ""
    if big and len(items) <= 3 and all(it.lead and not it.sub for it in items):  # a few statements: each lead as a heading
        lis = "".join(f'<li><div class="lead-big">{rich(it.lead)}</div>{rich(it.text)}</li>' for it in items)
        return f'<ul class="pts big" style="font-size:30px">{lis}</ul>'
    two = two_ok and len(items) > 4
    size = 34 if big and len(items) <= 3 else 30 if len(items) <= 4 else 26
    lis = []
    for it in items:
        lead = f'<span class="lead">{rich(it.lead)}</span>' + (" — " if it.text else "") if it.lead else ""
        sub = "".join(f"<li>{rich(x)}</li>" for x in it.sub)
        lis.append(f"<li>{lead}{rich(it.text)}{f'<ul class=sub>{sub}</ul>' if sub else ''}</li>")
    return f'<ul class="pts{" two" if two else ""}" style="font-size:{size}px">{"".join(lis)}</ul>'


def _bg(p: Photo | None, veil: str) -> str:
    return f'<img class="bg" alt="" src="{p.data_uri()}"><div class="veil {veil}"></div>' if p else ""


def _cover(s: Slide, ctx: _Ctx) -> tuple[str, str]:
    p = ctx.photo(s.image)
    h1 = _size(s.title, ((12, 168), (20, 140), (32, 112), (52, 92), (80, 78)))
    k = f'<div class="kicker">{e(s.kicker)}</div>' if s.kicker else ""
    glow = "" if p else '<div class="glow"></div>'
    inner = (f'{k}<h1 style="font-size:{h1}px">{rich(s.title)}</h1><div class="rule"></div>{_lede(s)}')
    return _bg(p, "bottom") + glow + f'<div class="inner">{inner}</div>', "has-photo" if p else ("no-photo" if s.image else "")


def _section(s: Slide, i: int) -> str:
    size = _size(s.title, ((24, 120), (44, 96), (80, 76)))
    k = f'<div class="kicker">{e(s.kicker)}</div>' if s.kicker else ""
    return (f'<div class="big-index">{i + 1:02d}</div><div class="inner">{k}<h2 style="font-size:{size}px">{rich(s.title)}</h2>'
            f'<div class="rule"></div>{_lede(s)}</div>')


def _points(s: Slide) -> str:
    return f'<div class="inner">{_head(s)}{_lede(s)}<div class="body">{_bullets(s.items, big=True)}</div></div>'


def _photo(s: Slide, p: Photo) -> str:
    return (_bg(p, "left") + f'<div class="inner"><div class="col">{_head(s)}{_lede(s)}'
            f'<div class="body">{_bullets(s.items, two_ok=False)}</div></div></div>')


def _split(s: Slide, p: Photo) -> str:
    cap = f'<div class="cap">{rich(s.caption)}</div>' if s.caption else ""
    return (f'<div class="inner"><div class="split"><div class="col">{_head(s)}{_lede(s)}'
            f'<div class="body">{_bullets(s.items, two_ok=False)}</div></div>'
            f'<div class="frame"><img alt="" src="{p.data_uri()}">{cap}</div></div></div>')


def _cards(s: Slide, ctx: _Ctx) -> str:
    n = len(s.cards)
    out = []
    any_photo = any(ctx.photos.get(c.image) for c in s.cards)
    if any_photo:
        name_px, line_px, tall = {2: 40, 3: 34, 4: 30}.get(n, 30), {2: 26, 3: 23, 4: 21}.get(n, 21), ""
    else:  # text only: bigger type and taller cards, so the slide doesn't float
        name_px, line_px, tall = {2: 52, 3: 42, 4: 36}.get(n, 36), {2: 32, 3: 27, 4: 24}.get(n, 24), "min-height:520px;"
    for c in s.cards:
        p = ctx.photo(c.image)
        top = f'<img alt="" src="{p.data_uri()}">' if p else ("" if any_photo else '<div class="bar"></div>')
        if not p and any_photo:
            top = '<div class="bar"></div>'
        meta = f'<div class="meta">{e(c.meta)}</div>' if c.meta else ""
        lines = "".join(f'<div class="line" style="font-size:{line_px}px">{rich(x)}</div>' for x in c.lines)
        out.append(f'<div class="card{" with-photo" if p else ""}" style="{tall}">{top}<div class="pad" style="padding:{44 if tall else 34}px">'
                   f'<div class="name" style="font-size:{name_px}px">'
                   f'{rich(c.title)}</div>{meta}{lines}</div></div>')
    return (f'<div class="inner">{_head(s)}{_lede(s)}<div class="body"><div class="grid" style="grid-template-columns:repeat({n},1fr);'
            f'align-items:stretch">{"".join(out)}</div></div></div>')


def _steps(s: Slide) -> str:
    n = len(s.steps)
    num, t, d, tall = (110, 36, 28, 460) if n <= 3 else (92, 31, 24, 460) if n <= 5 else (80, 28, 22, 480)
    tiles = "".join(f'<div class="tile" style="min-height:{tall}px"><div class="num" style="font-size:{num}px">{k}</div>'
                    f'<div class="t" style="font-size:{t}px">{rich(st.title)}</div>'
                    f'{f"<div class=d style=font-size:{d}px>{rich(st.detail)}</div>" if st.detail else ""}</div>'
                    for k, st in enumerate(s.steps, 1))
    gap = 32 if n <= 4 else 22
    return (f'<div class="inner">{_head(s)}{_lede(s)}<div class="body"><div class="grid" style="grid-template-columns:repeat({n},1fr);'
            f'gap:{gap}px">{tiles}</div></div></div>')


def _stats(s: Slide) -> str:
    n = len(s.stats)
    longest = max(len(st.value) for st in s.stats)
    inner = (1680 - 32 * (n - 1)) / n - 80
    px = max(48, min(120, int(inner / (0.62 * longest))))
    tiles = "".join(f'<div class="tile" style="padding:56px 40px;min-height:340px;justify-content:center">'
                    f'<div class="value" style="font-size:{px}px">{e(st.value)}</div>'
                    f'<div class="l">{rich(st.label)}</div></div>' for st in s.stats)
    extra = ""
    if s.items:
        cols = min(len(s.items), 3)
        extra = (f'<ul class="pts" style="font-size:24px;margin-top:44px;grid-template-columns:repeat({cols},1fr)">'
                 + "".join(f'<li>{f"<span class=lead>{rich(it.lead)}</span> — " if it.lead else ""}{rich(it.text)}</li>' for it in s.items)
                 + "</ul>")
    return (f'<div class="inner">{_head(s)}{_lede(s)}<div class="body"><div class="grid" style="grid-template-columns:repeat({n},1fr)">'
            f'{tiles}</div>{extra}</div></div>')


def _table(s: Slide) -> str:
    head, *rows = s.table
    th = "".join(f"<th>{rich(c)}</th>" for c in head)
    trs = "".join("<tr>" + "".join(f"<td>{rich(c)}</td>" for c in r) + "</tr>" for r in rows)
    size = 28 if len(rows) <= 5 else 24 if len(rows) <= 8 else 20 if len(rows) <= 12 else 15
    pad = 22 if len(rows) <= 8 else 12 if len(rows) <= 12 else 7
    return (f'<div class="inner">{_head(s)}{_lede(s)}<div class="body"><table class="t" style="font-size:{size}px;--td:{pad}px"><thead><tr>{th}</tr>'
            f'</thead><tbody>{trs}</tbody></table></div></div>')


def _nice(top: float) -> tuple[float, float]:
    """A round axis maximum and its step (four gridlines)."""
    if top <= 0:
        return 1.0, 0.25
    raw = top / 4
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
    return step * 4, step


def fmt(v: float, unit: str = "") -> str:
    """A chart value with its unit: $41.1B, ₹9,000, 72%."""
    num = f"{v:,.0f}" if abs(v - round(v)) < 1e-9 or abs(v) >= 100 else f"{v:,.1f}".rstrip("0").rstrip(".")
    if not unit:
        return num
    if unit in ("%", "x", "×") or unit[0].isalpha():
        return f"{num}{unit}" if unit in ("%", "x", "×") else f"{num} {unit}"
    return f"{unit[0]}{num}{unit[1:]}"


def chart_svg(chart: dict, t: Theme, w: int = 1680, h: int = 640) -> str:
    left, right, top, bottom = 120, 30, 40, 80
    pw, ph = w - left - right, h - top - bottom
    series, xs, unit = chart["series"], chart["x"], chart.get("unit", "")
    peak = max(max(s["data"]) for s in series)
    ymax, step = _nice(peak * 1.08)
    colors = [t.accent, t.muted, t.ink]
    y = lambda v: top + ph - (max(v, 0) / ymax) * ph  # noqa: E731
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" font-family="{e(t.body_font)}">']
    for k in range(5):
        v = step * k
        yy = y(v)
        parts.append(f'<line x1="{left}" y1="{yy:.1f}" x2="{w - right}" y2="{yy:.1f}" stroke="{t.card_line}" stroke-width="{2 if k == 0 else 1}"/>')
        parts.append(f'<text x="{left - 18}" y="{yy + 8:.1f}" text-anchor="end" font-size="22" fill="{t.muted}">{e(fmt(v, unit))}</text>')
    n = len(xs)
    group = pw / n
    for i, label in enumerate(xs):
        cx = left + group * (i + 0.5)
        size = 22 if n <= 8 else 18
        parts.append(f'<text x="{cx:.1f}" y="{h - bottom + 44}" text-anchor="middle" font-size="{size}" fill="{t.muted}">{e(label)}</text>')
    if chart["type"] == "line":
        for si, s in enumerate(series):
            pts = " ".join(f"{left + group * (i + 0.5):.1f},{y(v):.1f}" for i, v in enumerate(s["data"]))
            c = colors[si % len(colors)]
            parts.append(f'<polyline points="{pts}" fill="none" stroke="{c}" stroke-width="6" stroke-linejoin="round" stroke-linecap="round"/>')
            for i, v in enumerate(s["data"]):
                parts.append(f'<circle cx="{left + group * (i + 0.5):.1f}" cy="{y(v):.1f}" r="9" fill="{c}"/>')
    else:
        k = len(series)
        bw = group * 0.62 / k
        for si, s in enumerate(series):
            c = colors[si % len(colors)]
            for i, v in enumerate(s["data"]):
                x0 = left + group * i + group * 0.19 + bw * si
                y0 = y(v)
                parts.append(f'<rect x="{x0:.1f}" y="{y0:.1f}" width="{bw:.1f}" height="{top + ph - y0:.1f}" rx="8" fill="{c}"/>')
                if k == 1 and n <= 12:
                    parts.append(f'<text x="{x0 + bw / 2:.1f}" y="{y0 - 16:.1f}" text-anchor="middle" font-size="24" font-weight="700" '
                                 f'fill="{t.ink}">{e(fmt(v, unit))}</text>')
    if len(series) > 1:
        lx = left
        for si, s in enumerate(series):
            parts.append(f'<rect x="{lx}" y="4" width="22" height="22" rx="5" fill="{colors[si % len(colors)]}"/>'
                         f'<text x="{lx + 32}" y="22" font-size="22" fill="{t.muted}">{e(s["name"])}</text>')
            lx += 60 + 14 * len(s["name"])
    parts.append("</svg>")
    return "".join(parts)


def _chart(s: Slide, t: Theme) -> str:
    return f'<div class="inner">{_head(s)}{_lede(s)}<div class="body">{chart_svg(s.chart, t)}</div></div>'


def _gallery(s: Slide, ctx: _Ctx) -> str:
    frames = []
    for ref, _, cap in s.gallery:
        p = ctx.photo(ref)
        if p:
            c = f'<div class="cap">{rich(cap)}</div>' if cap else ""
            frames.append(f'<div class="frame"><img alt="" src="{p.data_uri()}">{c}</div>')
    if not frames:
        return _points(s)
    return (f'<div class="inner">{_head(s)}<div class="body"><div class="gal" style="grid-template-columns:repeat({len(frames)},1fr)">'
            f'{"".join(frames)}</div></div></div>')


def _quote(s: Slide, ctx: _Ctx) -> tuple[str, str]:
    p = ctx.photo(s.image)
    size = _size(s.quote, ((80, 80), (140, 64), (400, 52)))
    by = f'<div class="by">— {rich(s.quote_by)}</div>' if s.quote_by else ""
    return (_bg(p, "full") + f'<div class="inner"><div class="mark">“</div><div class="quote" style="font-size:{size}px">{rich(s.quote)}</div>'
            f'{by}</div>'), "has-photo" if p else ""


def _closing(s: Slide, ctx: _Ctx) -> tuple[str, str]:
    p = ctx.photo(s.image)
    size = _size(s.title, ((16, 150), (30, 116), (80, 88)))
    glow = "" if p else '<div class="glow"></div>'
    return (_bg(p, "full") + glow + f'<div class="inner"><h1 style="font-size:{size}px">{rich(s.title)}</h1><div class="rule"></div>'
            f'{_lede(s)}</div>'), "has-photo" if p else ""


def _slide(s: Slide, i: int, n: int, t: Theme, photos: dict[str, Photo]) -> str:
    ctx = _Ctx(photos, [])
    layout, extra = s.layout, ""
    if layout == "cover":
        body, extra = _cover(s, ctx)
    elif layout in ("photo", "split"):
        p = ctx.photo(s.image)
        if p is None:
            body, extra = _points(s), "no-photo"
        else:
            body = _photo(s, p) if layout == "photo" else _split(s, p)
            extra = "has-photo" if layout == "photo" else ""
    elif layout in ("section", "steps", "stats"):  # these wear their photo as a background, behind a full veil
        p = ctx.photo(s.image)
        body = {"section": lambda: _section(s, i), "steps": lambda: _steps(s), "stats": lambda: _stats(s)}[layout]()
        if p:
            body, extra = _bg(p, "full") + body, "has-photo"
    elif layout == "cards":
        body = _cards(s, ctx)
    elif layout == "table":
        body = _table(s)
    elif layout == "chart":
        body = _chart(s, t)
    elif layout == "gallery":
        body = _gallery(s, ctx)
    elif layout == "quote":
        body, extra = _quote(s, ctx)
    elif layout == "closing":
        body, extra = _closing(s, ctx)
    else:
        body = _points(s)
    credit = f'<div class="credit">photo: {e(" · ".join(ctx.credits))}</div>' if ctx.credits else ""
    cls = f"slide l-{layout}" + (f" {extra}" if extra else "")
    return f'<section class="{cls}">{body}{credit}<div class="pageno">{i + 1:02d} / {n:02d}</div></section>'


def render_html(deck: Deck, theme: Theme, photos: dict[str, Photo]) -> str:
    n = len(deck.slides)
    slides = "\n".join(_slide(s, i, n, theme, photos) for i, s in enumerate(deck.slides))
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="{CSP}">'
            f"<title>{e(deck.title)}</title><style>{_css(theme)}</style></head><body>\n{slides}\n</body></html>")
