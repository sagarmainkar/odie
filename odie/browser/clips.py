"""Short stock clips through Odie's own browser, with no search key (spec: video pictures, part 1): free video clips
from Pexels and Pixabay, for the mood or the place in a film (waves, snow, a busy street). Each search page carries
all a clip needs (its file, length, size and maker), so one page per site is read; the file is the smallest rendition
that is still HD, since a film uses at most 15 s of a clip at 1280 x 720."""
from __future__ import annotations

import asyncio
import html as _html
import json
import re
import unicodedata
import uuid
from urllib.parse import quote

from odie.agent.tools.web import _fence

SOURCES = (("pexels", "Pexels", "free"), ("pixabay", "Pixabay", "free"))
HD = 1280  # a rendition is HD when its long side is at least this (1280 x 720, 720 x 1280, an ultra-wide 1366 x 570)


def search_url(key: str, query: str) -> str:
    q = quote(" ".join(query.split()))
    if key == "pexels":
        return f"https://www.pexels.com/search/videos/{q}/"
    return f"https://pixabay.com/videos/search/{q}/"


NAME_MAX = 60  # a maker's name is free text a stranger chose, and it's copied into make_video's lines and credits


def _clip(address: str, page: str, seconds: float | None, credit: str, width: int, height: int, title: str,
          tags: str, approx: bool) -> dict:
    """One clip. `tags` (its description and keywords) is only for the relevance check, never shown; `approx` says the
    size was worked out (Pixabay) rather than read from the page (Pexels)."""
    return {"address": address, "page": page, "seconds": seconds, "credit": credit, "width": width, "height": height,
            "title": " ".join(title.split())[:140], "tags": tags, "approx": approx}


def _name(text: str) -> str:
    """A maker's name as the page has it, with invisible marks dropped, spaces tidied and at most 60 characters.
    Example: "Ahmed" with an invisible Arabic letter mark after it (Pexels has one) -> "Ahmed"."""
    visible = "".join(ch for ch in text if unicodedata.category(ch) != "Cf")
    tidy = " ".join(visible.split())
    return tidy[:NAME_MAX].strip()


# ── Pexels: the page's own data (Next.js __NEXT_DATA__): props.pageProps.initialData.data, one entry per video ──

_NEXT_DATA = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)


def _long_side(file: dict) -> int:
    width = int(file.get("width") or 0)
    height = int(file.get("height") or 0)
    return max(width, height)


def _smallest_hd(files: list[dict]) -> dict | None:
    """The rendition to fetch: the smallest MP4 that is still HD (long side 1280 or more), else the biggest there is.
    Example: 240x426, 360x640, 720x1280, 1080x1920 -> 720x1280; an ultra-wide 1366x570 counts as HD; only 640x360 and
    960x540 -> 960x540; no MP4 -> None."""
    mp4s = [f for f in files if f.get("file_type") == "video/mp4" and f.get("link")]
    if not mp4s:
        return None
    by_size = sorted(mp4s, key=_long_side)
    for f in by_size:
        if _long_side(f) >= HD:
            return f
    return by_size[-1]


def pexels(page_html: str) -> list[dict]:
    found = _NEXT_DATA.search(page_html or "")
    if not found:
        return []
    try:
        data = json.loads(found[1])
        videos = data["props"]["pageProps"]["initialData"]["data"]
    except (ValueError, KeyError, TypeError):
        return []
    out = []
    for v in videos:
        if v.get("type") != "video":
            continue
        a = v.get("attributes") or {}
        video = a.get("video") or {}
        f = _smallest_hd(video.get("video_files") or [])
        if not f:
            continue
        user = a.get("user") or {}
        name = _name(f"{user.get('first_name') or ''} {user.get('last_name') or ''}")
        credit = f"Video by {name} on Pexels" if name else "Pexels"
        page = f"https://www.pexels.com/video/{a.get('slug')}-{a.get('id')}/"
        seconds = float(a["duration"]) if a.get("duration") else None
        tag_names = ", ".join(str(t.get("name") or "") for t in a.get("tags") or [])
        tags = f"{a.get('description') or ''} {tag_names}"
        out.append(_clip(f["link"], page, seconds, credit, int(f.get("width") or 0), int(f.get("height") or 0),
                         str(a.get("title") or ""), tags, approx=False))
    return out


# ── Pixabay: each result card holds a schema.org VideoObject (JSON-LD) with the file, length and words; the card's
# markup before it has the original size (inline max-width/max-height) and the maker (the /users/ link) ──

_LD = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)
_SIZE = re.compile(r"max-width:\s*(\d+)px;\s*max-height:\s*(\d+)px")
_MAKER = re.compile(r'<a\b[^>]*href="/users/[^"]*"[^>]*>([^<]+)</a>')
_UPLOADED = re.compile(r"/video/(\d{4})/")
# Pixabay's renditions, each about this share of the original's size (uploads from 2017 on)
_SHARE = (("tiny", 1 / 3), ("small", 1 / 2), ("medium", 2 / 3))


def _even(n: float) -> int:
    return int(round(n / 2)) * 2


def _pixabay_rendition(year: int, width: int, height: int) -> tuple[str, int, int]:
    """Which of Pixabay's renditions to fetch, and its size: the smallest that is still HD (long side 1280 or more).
    Since 2017 tiny, small and medium are about a third, a half and two thirds of the original; uploads from 2016 and
    before have fixed smaller ones, so those (and a card with no size) take medium, which is always HD, size unknown.
    Example: a 2026 upload at 3840x2160 -> ("tiny", 1280, 720); 2160x3840 -> ("tiny", 720, 1280); 1920x1080 ->
    ("medium", 1280, 720); a 2016 upload at 3840x2160 -> ("medium", 0, 0); a 2020 one at 1280x720 ->
    ("medium", 854, 480), the best there is."""
    if year <= 2016 or not width or not height:
        return "medium", 0, 0
    for name, share in _SHARE:
        if max(width, height) * share >= HD:
            return name, _even(width * share), _even(height * share)
    return "medium", _even(width * 2 / 3), _even(height * 2 / 3)


def _seconds(duration: str) -> float | None:
    """A schema.org length as Pixabay writes it, in seconds.
    Example: "T0M40S" -> 40.0; "PT1H2M3S" -> 3723.0; "" -> None."""
    m = re.search(r"T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?", duration or "")
    if not m or not any(m.groups()):
        return None
    hours, minutes, secs = (float(x or 0) for x in m.groups())
    return hours * 3600 + minutes * 60 + secs


def pixabay(page_html: str) -> list[dict]:
    text = page_html or ""
    out = []
    for block in _LD.finditer(text):
        try:
            v = json.loads(block[1])
        except ValueError:
            continue
        if not isinstance(v, dict) or v.get("@type") != "VideoObject":
            continue
        address, path = str(v.get("contentUrl") or ""), str(v.get("acquireLicensePage") or "")
        if not address.endswith("_tiny.mp4") or not path.startswith("/videos/"):
            continue
        card_start = text.rfind(f'href="{path}"', 0, block.start())  # the card's link, just before its data
        card = text[card_start:block.start()] if card_start >= 0 else ""
        size = _SIZE.search(card)
        width, height = (int(size[1]), int(size[2])) if size else (0, 0)
        maker = _MAKER.search(card)
        name = _name(_html.unescape(maker[1])) if maker else ""
        uploaded = _UPLOADED.search(address)
        year = int(uploaded[1]) if uploaded else 0
        rendition, w, h = _pixabay_rendition(year, width, height)
        file = address.removesuffix("_tiny.mp4") + f"_{rendition}.mp4"
        credit = f"Video by {name} on Pixabay" if name else "Pixabay"
        tags = f"{v.get('name') or ''}, {v.get('description') or ''}"
        out.append(_clip(file, "https://pixabay.com" + path, _seconds(str(v.get("duration") or "")), credit, w, h,
                         str(v.get("name") or ""), tags, approx=True))
    return out


PARSERS = {"pexels": pexels, "pixabay": pixabay}


def _words(text: str) -> set[str]:
    """The words of a text, singular and plural alike. Example: "Ocean Waves, Sea" -> {"ocean", "wave", "sea"}."""
    words = set()
    for w in re.findall(r"[a-z0-9]{3,}", (text or "").lower()):
        if len(w) > 3 and w.endswith("s"):
            w = w[:-1]
        words.add(w)
    return words


def is_about(clip: dict, query: str) -> bool:
    """Does the clip's title, description or keywords share a word with the ask? A thin search fills up with near
    misses.
    Example: "ocean waves" and a clip tagged "Wave, Rock, Splash" -> True; one tagged "Skate, Sport, Water" -> False."""
    return bool(_words(f"{clip['title']} {clip['tags']}") & _words(query))


def _take_turns(groups: list[list[dict]], count: int) -> list[dict]:
    """One from each site in turn, up to count: Pexels [a, b], Pixabay [x, y], count 3 -> a, x, b."""
    out = []
    for i in range(max((len(g) for g in groups), default=0)):
        for g in groups:
            if i < len(g) and len(out) < count:
                out.append(g[i])
    return out


async def find(browser, query: str, count: int = 4) -> dict:
    """{"clips": [...], "failed": ["Pexels: why", ...]}: both sites read at once, each in a cookie-free tab of its own
    (closed after), clips of something else dropped, then one from each site in turn up to `count`."""
    run = uuid.uuid4().hex[:8]  # this search's own tabs: two searches at once never share one

    async def one(key: str, label: str) -> tuple[list[dict], str]:
        tab = f"clips:{key}:{run}"
        try:
            await browser.open(tab, search_url(key, query), isolated=True)  # a clip search never needs a session
            await browser.scroll(tab)
            return PARSERS[key](await browser.html(tab)), ""
        except Exception as e:  # noqa: BLE001 (one site down never stops the other)
            return [], f"{label}: {e}"
        finally:
            try:
                await browser.close_tab(tab)
            except Exception:  # noqa: BLE001
                pass
    got = await asyncio.gather(*(one(key, label) for key, label, _ in SOURCES))
    relevant = [[c for c in found if is_about(c, query)] for found, _ in got]
    return {"clips": _take_turns(relevant, count), "failed": [why for _, why in got if why]}


def size_text(clip: dict) -> str:
    """The clip's size as the model reads it: exact when the page gave it, "~" in front when it was worked out.
    Example: a Pexels file -> "720x1280"; a Pixabay one -> "~1280x720"; an old Pixabay upload (not known) -> ""."""
    if not clip["width"] or not clip["height"]:
        return ""
    size = f"{clip['width']}x{clip['height']}"
    if clip["approx"]:
        return "~" + size
    return size


def find_text(got: dict) -> str:
    lines = []
    if got["clips"]:
        lines.append("Stock clips (Pexels, Pixabay: free to use; length in seconds; a size with ~ is approximate):")
        for c in got["clips"]:
            parts = [c["address"], c["title"]]
            if c["seconds"]:
                parts.append(f"{c['seconds']:g} s")
            if size_text(c):
                parts.append(size_text(c))
            parts.append(f"credit: {c['credit']}")
            lines.append("- " + " | ".join(parts))
        lines.append("For make_video's clips=[...], write each as one line \"address — what it shows (credit)\", "
                     "with the address and the credit exactly as given.")
    else:
        lines.append("No clips found: try plainer words (\"ocean waves\", \"snowy mountains\", \"busy street\").")
    if got.get("failed"):
        lines.append("Not reached: " + "; ".join(got["failed"]))
    return _fence("\n".join(lines))
