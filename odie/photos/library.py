"""The user's Photos library, read-only, through osxphotos: what Apple already knows about each photo and video (who is
in it, what it shows, where and when it was taken, its albums, and Apple's own extras: holidays, seasons, trips,
activities, pets, landmarks, text seen in it), plus the small and large JPEG copies Photos keeps on this Mac, which
serve as the thumbnail and, later, the picture an embedding model reads. Nothing is written to the library, nothing
leaves the computer. Hidden items and the bin are never read; screenshots only when asked."""
from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import asdict, dataclass, field

THUMB_MARK = "_5005_"  # Photos' smallest copy (about 360 px, under 100 KB): the thumbnail
IMAGE_TYPES = (".jpeg", ".jpg", ".png", ".heic", ".heif", ".tiff", ".tif", ".gif", ".webp", ".bmp")  # a still image, never a movie
EXTRAS = ("holidays", "season", "trip", "activities", "pets", "landmarks", "detected_text", "times_of_day", "venue_types",
          "events", "human_actions", "bodies_of_water", "areas_of_interest")


class LibraryError(Exception):
    """A plain reason the library couldn't be read, said to the user as it is."""


@dataclass
class PhotoRow:
    uuid: str
    kind: str            # "photo" or "video"
    taken: str           # local time, "2024-05-16T11:09:23"
    people: list[str]
    labels: list[str]    # what Photos saw: "Beach", "Dog"
    place: str           # "Baga Beach, Goa, India" (Photos' own words), or ""
    city: str
    country: str
    albums: list[str]
    extras: dict[str, list[str]] = field(default_factory=dict)  # Apple's search extras, by kind
    favorite: bool = False
    screenshot: bool = False
    width: int = 0
    height: int = 0
    thumb: str | None = None   # the small JPEG on this Mac, or None (nothing of it here: metadata only)
    big: str | None = None     # the largest copy here: the original, else Photos' 2048 px copy, else None

    def as_dict(self) -> dict:
        return asdict(self)


def pick_copies(paths: list[str], original: str | None) -> tuple[str | None, str | None]:
    """Which files stand for a picture: the thumbnail is Photos' own smallest copy (its name carries _5005_), else
    the smallest file; the big one is Photos' largest copy (a 2048 px JPEG, which anything can open and the model
    reads at 1024 px anyway), else the original when it's on this Mac and is a still image. A movie's original is a
    .mov: never the big copy (14 Oct 2026: one stopped the whole picture pass).
      ["x_4_5005_c.jpeg", "x_1_102_o.jpeg"], original "IMG_1.HEIC" -> ("x_4_5005_c.jpeg", "x_1_102_o.jpeg")
      ["x_4_5005_c.jpeg"], original "IMG_1.HEIC"                   -> ("x_4_5005_c.jpeg", "IMG_1.HEIC")
      ["x_4_5005_c.jpeg"], original "clip.mov"                     -> ("x_4_5005_c.jpeg", "x_4_5005_c.jpeg")
      [], original "clip.mov"                                      -> (None, None)"""
    still = original if original and original.lower().endswith(IMAGE_TYPES) else None
    if not paths and not still:
        return None, None
    by_size = sorted(paths, key=_size)
    marked = [p for p in paths if THUMB_MARK in os.path.basename(p)]
    thumb = marked[0] if marked else (by_size[0] if by_size else None)
    others = [p for p in by_size if p != thumb]
    big = others[-1] if others else (still or thumb)
    return thumb, big


def _size(path: str) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def library_path() -> str | None:
    """The Photos library to read: the system library as macOS names it, else the usual ~/Pictures one; None when
    neither is there. (osxphotos' own default lookup fails on some Macs, so the path is always given.)"""
    try:
        from osxphotos.utils import get_system_library_path
        found = get_system_library_path()
    except Exception:  # noqa: BLE001
        found = None
    usual = os.path.expanduser("~/Pictures/Photos Library.photoslibrary")
    for candidate in (found, usual):
        if candidate and os.path.isdir(candidate):
            return candidate
    return None


def read_library(include_screenshots: bool = False, progress: Callable[[int, int], None] | None = None,
                 dbfile: str | None = None) -> list[PhotoRow]:
    """Every photo and video Photos knows (hidden ones and the bin left out; screenshots when asked), as rows for the
    index. Takes a few seconds for ten thousand items; the first open after a change in Photos copies its database."""
    try:
        import osxphotos
    except ImportError as e:
        raise LibraryError("osxphotos isn't installed: run the installer again") from e
    dbfile = dbfile or library_path()
    if not dbfile:
        raise LibraryError("There's no Photos library on this computer.")
    try:
        db = osxphotos.PhotosDB(dbfile=dbfile)
        items = db.photos(movies=True)
    except Exception as e:  # noqa: BLE001
        raise LibraryError(_plain_reason(e)) from e
    rows = []
    for i, p in enumerate(items):
        if p.hidden or p.intrash:
            continue
        if p.screenshot and not include_screenshots:
            continue
        rows.append(row_of(p))
        if progress and (i % 500 == 0 or i + 1 == len(items)):
            progress(i + 1, len(items))
    return rows


def row_of(p) -> PhotoRow:
    """One osxphotos PhotoInfo as a row (every field read defensively: a library from another macOS may lack some)."""
    place = p.place
    thumb, big = pick_copies(list(p.path_derivatives or []), p.path if p.path and not p.ismissing else None)
    info = p.search_info
    extras: dict[str, list[str]] = {}
    for key in EXTRAS:
        values = getattr(info, key, None) if info is not None else None
        if values:
            extras[key] = sorted({str(v) for v in (values if isinstance(values, (list, tuple, set)) else [values]) if v})
    taken = p.date.replace(tzinfo=None).isoformat(timespec="seconds") if p.date else ""
    return PhotoRow(
        uuid=p.uuid, kind="video" if p.ismovie else "photo", taken=taken,
        people=sorted({n for n in (p.persons or []) if n and n != "_UNKNOWN_"}),
        labels=sorted({str(l) for l in (p.labels or []) if l}),
        place=(place.name or "") if place else "",
        city=_first(place, "city"), country=_first(place, "country"),
        albums=sorted({a for a in (p.albums or []) if a}),
        extras=extras, favorite=bool(p.favorite), screenshot=bool(p.screenshot),
        width=int(p.width or 0), height=int(p.height or 0), thumb=thumb, big=big,
    )


def _first(place, field_name: str) -> str:
    names = getattr(place, "names", None) if place else None
    values = getattr(names, field_name, None) if names else None
    if isinstance(values, (list, tuple)):
        return str(values[0]) if values else ""
    return str(values or "")


def _plain_reason(e: Exception) -> str:
    text = str(e)
    if "Operation not permitted" in text or "permission" in text.lower():
        return ("macOS didn't let Odie read the Photos library. In System Settings → Privacy & Security → Photos (or Full "
                "Disk Access), allow it for Odie's Python, then try again.")
    if "No such file" in text or "does not exist" in text.lower():
        return "There's no Photos library on this computer."
    return f"{type(e).__name__}: {text}"[:300]
