"""Photos for decks: downloaded once by code (odie.net: public addresses only), decoded, re-encoded to JPEG at most
2000 px with EXIF dropped, and cached by address in <data>/workspace/images/. A browser screenshot or the user's own
photo is used by its id. Each photo keeps its credit."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from PIL import Image, ImageOps, UnidentifiedImageError

from odie.net import DownloadError, safe_download

MAX_BYTES, MAX_EDGE = 10 * 1024 * 1024, 2000
MAX_PIXELS = 60_000_000  # a decompression bomb is refused, not decoded


class PhotoError(Exception):
    """Why a photo can't be used, in a sentence."""


@dataclass
class Photo:
    ref: str
    path: Path
    width: int
    height: int
    credit: str

    def data_uri(self) -> str:
        return "data:image/jpeg;base64," + base64.b64encode(self.path.read_bytes()).decode()


def cache_dir() -> Path:
    from odie.agent.tools.files import workspace_root
    d = workspace_root() / "images"
    d.mkdir(parents=True, exist_ok=True)
    return d


def site_name(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def _dest(ref: str) -> Path:
    return cache_dir() / (hashlib.sha256(ref.encode()).hexdigest()[:32] + ".jpg")


def _encode(data: bytes, dest: Path) -> tuple[int, int]:
    try:
        img = Image.open(io.BytesIO(data))
        if img.width * img.height > MAX_PIXELS:
            raise PhotoError("The picture is too large.")
        img.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, ValueError):
        raise PhotoError("It isn't a picture.") from None
    img = ImageOps.exif_transpose(img)
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    img.thumbnail((MAX_EDGE, MAX_EDGE))
    tmp = dest.with_suffix(".tmp")
    img.save(tmp, "JPEG", quality=82, optimize=True, progressive=True)  # no exif=: nothing carried over
    tmp.replace(dest)
    return img.width, img.height


def _cached(dest: Path, ref: str, credit: str) -> Photo | None:
    if not dest.is_file():
        return None
    with Image.open(dest) as img:
        return Photo(ref, dest, img.width, img.height, credit)


async def fetch(ref: str, credit: str = "", referer: str | None = None) -> Photo:
    ref = (ref or "").strip()
    if ref.startswith(("screenshot:", "upload:")):
        return await asyncio.to_thread(_local, ref)
    if not re.match(r"^https?://", ref, re.I):
        raise PhotoError("Use a photo address a tool returned (https://…), screenshot:<id> or upload:<id>.")
    credit = credit.strip() or site_name(ref)
    dest = _dest(ref)
    if (hit := await asyncio.to_thread(_cached, dest, ref, credit)) is not None:
        return hit
    from odie.agent import turn
    if turn.private_sites():  # the address could carry what the model read on a signed-in page
        raise PhotoError("not fetched: this chat read a signed-in page, so photos from the web aren't fetched here")
    try:
        data, _ = await safe_download(ref, MAX_BYTES, referer=referer)
    except DownloadError as e:
        raise PhotoError(str(e)) from None
    w, h = await asyncio.to_thread(_encode, data, dest)
    return Photo(ref, dest, w, h, credit)


def _local(ref: str) -> Photo:
    kind, _, rid = ref.partition(":")
    if kind == "screenshot":
        from odie import media
        got = media.get(rid)
        if got is None or got[1].get("kind") != "screenshot":
            raise PhotoError("There's no screenshot with that id.")
        path, m = got
        data, credit = path.read_bytes(), site_name(m.get("url") or "")
    else:
        from odie.app.images import load_image
        got = load_image(rid)
        if got is None:
            raise PhotoError("There's no photo from the user with that id.")
        data, credit = got[0], ""
    dest = _dest(ref)
    w, h = _encode(data, dest)
    return Photo(ref, dest, w, h, credit)


async def fetch_all(refs: list[tuple[str, str]]) -> tuple[dict[str, Photo], list[str]]:
    """Every (ref, credit) at once: the photos that worked, and the refs that didn't."""
    unique = list(dict.fromkeys(refs))
    got = await asyncio.gather(*(fetch(r, c) for r, c in unique), return_exceptions=True)
    ok: dict[str, Photo] = {}
    failed: list[str] = []
    for (ref, _), g in zip(unique, got):
        if isinstance(g, Photo):
            ok.setdefault(ref, g)
        elif ref not in failed:
            failed.append(ref)
    return ok, failed
