"""Photos for decks and videos: downloaded once by code (odie.net: public addresses only), decoded, re-encoded to JPEG
at most 2000 px with EXIF dropped, and cached by address in <data>/workspace/images/. A browser screenshot or the
user's upload is used by its id, and a picture in the user's Photos library by photo:<id> (the largest copy Photos
keeps on this Mac). Each photo keeps its credit; the user's own pictures need none."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from PIL import Image, ImageOps, UnidentifiedImageError

from odie.net import DownloadError, safe_download
from odie.photos.library import A_PHOTO_UUID

MAX_BYTES, MAX_EDGE = 10 * 1024 * 1024, 2000
MAX_PIXELS = 60_000_000  # a decompression bomb is refused, not decoded
MIN_LIBRARY_SIDE = 1000  # px on the long side: a library picture with only a smaller copy here is left out
HEIC_TYPES = (".heic", ".heif")
PRIVATE_REFUSAL = "not fetched: this chat read a signed-in page, so photos from the web aren't fetched here"


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
    # A temporary file of its own, then a rename: two fetches of one address at once each write their own and the
    # second rename simply wins, never finding the other's file gone.
    handle, name = tempfile.mkstemp(dir=dest.parent, suffix=".tmp")
    os.close(handle)
    tmp = Path(name)
    try:
        img.save(tmp, "JPEG", quality=82, optimize=True, progressive=True)  # no exif=: nothing carried over
        tmp.replace(dest)
    finally:
        tmp.unlink(missing_ok=True)
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
    if ref.startswith("photo:"):
        return await asyncio.to_thread(_library, ref)
    if not re.match(r"^https?://", ref, re.I):
        raise PhotoError("Use a photo address a tool returned (https://…), screenshot:<id>, upload:<id> or "
                         "photo:<id>.")
    credit = credit.strip() or site_name(ref)
    dest = _dest(ref)
    if (hit := await asyncio.to_thread(_cached, dest, ref, credit)) is not None:
        return hit
    from odie.agent import turn
    if turn.private_sites():  # the address could carry what the model read on a signed-in page
        raise PhotoError(PRIVATE_REFUSAL)
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


def library_row(uuid: str) -> dict | None:
    """The index's row for one picture in the user's Photos library (its kind, and in "big" the largest copy on this
    Mac: odie.photos.library.pick_copies' choice), or None when there's no such picture or photos aren't set up. The
    store is the one Odie's background jobs use (set by the runner)."""
    from odie.making import jobs
    from odie.vault import settings
    store = jobs.hooks.get("store")
    if store is None:
        return None
    index = settings.index_for(store)
    if index is None:
        return None
    return index.photo(uuid)


def long_side(path: Path) -> int | None:
    """A picture file's longer side in pixels, read from its header, or None when Pillow can't open it (a HEIC
    without a HEIC reader): a 2048×1536 JPEG -> 2048; a HEIC here -> None."""
    try:
        with Image.open(path) as img:
            return max(img.size)
    except (UnidentifiedImageError, OSError):
        return None


def library_id(ref: str) -> str:
    """The picture's id in a photo: address, read so that words after it never lose the picture: the first Photos id
    (a uuid) in it, else its first word. "photo:0F1E…EEFF (for a video or a deck)" -> "0F1E…EEFF";
    "photo: 0F1E…EEFF us at Nathula" -> "0F1E…EEFF"; "photo:3F2A" -> "3F2A"; "photo:" -> ""."""
    rest = ref.partition(":")[2]
    found = A_PHOTO_UUID.search(rest)
    if found is not None:
        return found.group(0)
    words = rest.split()
    if not words:
        return ""
    return words[0]


def library_copy(ref: str) -> Path:
    """Decides whether photo:<id> can go in, and gives the file it comes from: the largest copy of a photo the index
    knows on this Mac. Anything else raises PhotoError with what the user can do, since Odie never asks iCloud for the
    full picture: photo:<id> with a 2048 px copy here -> that file; with only a 360 px copy -> "photo:<id> has only a
    small copy on this Mac (360 px); open it in Photos once so the full picture comes down"; a video, no copy, a
    HEIC Odie can't read or an unknown id -> its own refusal. Words after the id are ignored (library_id), and the
    refusals name the picture by photo:<id> alone. It only reads the index and the file's header, so make_video can
    check a line within the chat turn."""
    uuid = library_id(ref)
    ref = f"photo:{uuid}"
    row = library_row(uuid)
    if row is None:
        raise PhotoError(f"There's no picture {ref} in the user's Photos library here.")
    if row["kind"] != "photo":
        raise PhotoError(f"{ref} is a video; only photos from the library can go in")
    big = row["big"]
    if not big or not Path(big).is_file():
        raise PhotoError(f"{ref} has no copy on this Mac; open it in Photos once so the full picture comes down")
    path = Path(big)
    side = long_side(path)
    if side is None and path.suffix.lower() in HEIC_TYPES:
        raise PhotoError(f"{ref} is a HEIC Odie can't read here; export it as JPEG from Photos")
    if side is None:
        raise PhotoError(f"{ref} isn't a picture Odie can read.")
    if side < MIN_LIBRARY_SIDE:
        raise PhotoError(f"{ref} has only a small copy on this Mac ({side} px); open it in Photos once so the full "
                         "picture comes down")
    return path


def _library(ref: str) -> Photo:
    """photo:<id>: the user's own picture from the Photos library, by the copy library_copy allows, re-encoded like
    the others (upright, at most 2000 px, EXIF and its place dropped), and known by photo:<id> alone, whatever words
    followed the id. It needs no credit and works in a private chat (it never leaves the Mac)."""
    path = library_copy(ref)
    ref = f"photo:{library_id(ref)}"
    dest = _dest(ref)
    width, height = _encode(path.read_bytes(), dest)
    return Photo(ref, dest, width, height, "")


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
