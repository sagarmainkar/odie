"""Odie's search over the user's own things (odie.vault.index): one tool for notes and pictures alike, like Spotlight,
plus reading a note, looking around one, and the index's status. They only read, never outside the vault folder, and
a picture is only ever named by the address its thumbnail route serves, or, for a video or a deck, by photo:<uuid>."""
from __future__ import annotations

from datetime import date

from google.adk.tools import FunctionTool

from odie.photos import settings as photos
from odie.vault import settings
from odie.vault.index import AnyHit, Hit, PhotoHit

EXCERPT = 700
PHOTOS_SHOWN = 6     # pictures listed per search unless asked for more (the reply shows them, so a few at a time)
PHOTOS_MOST = 12
ONLY = ("docs", "media", "photos", "videos")
HOW_TO_SHOW = ('Show the ones with an address in one ```odie-images block (url: the /api/photos/… address exactly as '
               'given, caption: the date and place). Never invent an address.')


def _lines(hits: list[Hit], excerpt: int = EXCERPT) -> str:
    out = []
    for i, h in enumerate(hits, 1):
        text = h.text if len(h.text) <= excerpt else h.text[:excerpt] + "…"
        out.append(f"{i}. {h.note} ({h.path}) · {h.heading or 'top'} · updated {h.updated}\n{text}")
    return "\n\n".join(out)


def nice_day(day: str) -> str:
    """"2024-05-16" -> "16 May 2024" (anything else as it is)."""
    try:
        return date.fromisoformat(day[:10]).strftime("%-d %b %Y")
    except ValueError:
        return day


def library_address(h: PhotoHit) -> str | None:
    """Decides whether a picture gets the address that puts it in a video or a deck (make_video's images, a deck's
    photo): a photo with a copy on this computer -> "photo:<uuid> (for a video or a deck)"; a video, or a photo with
    nothing of it here -> None (those take photos only, from a copy on this Mac)."""
    if h.kind != "photo" or not h.has_thumb:
        return None
    return f"photo:{h.uuid} (for a video or a deck)"


def picture_line(h: PhotoHit) -> str:
    """A picture for the model, with the thumbnail address when a copy is on this computer (for the odie-images
    gallery), and for a photo, the address a video or a deck takes.
      a beach photo with a copy -> "[photo] 16 May 2024 · Baga Beach, Goa, India · with Asha · shows Beach, Sea ·
                                    album Goa 2024 · /api/photos/<uuid>/thumb ·
                                    photo:<uuid> (for a video or a deck)" """
    bits = [nice_day(h.taken)]
    if h.place:
        bits.append(h.place)
    if h.people:
        bits.append("with " + ", ".join(h.people))
    if h.labels:
        bits.append("shows " + ", ".join(h.labels[:8]))
    if h.albums:
        bits.append("album " + ", ".join(h.albums))
    if h.extras:
        bits.append("also " + ", ".join(h.extras))
    bits.append(f"/api/photos/{h.uuid}/thumb" if h.has_thumb else "no copy on this computer (can't be shown)")
    for_making = library_address(h)
    if for_making:
        bits.append(for_making)
    return f"[{h.kind}] " + " · ".join(bits)


def note_line(h: Hit, excerpt: int = EXCERPT) -> str:
    text = h.text if len(h.text) <= excerpt else h.text[:excerpt] + "…"
    return f"[note] {h.note} ({h.path}) · {h.heading or 'top'} · updated {h.updated}\n{text}"


def result_lines(hits: list[AnyHit], pictures: int) -> str:
    """The one list for the model, best first, each line saying what it is; pictures beyond `pictures` are counted,
    not listed, and a line says how to show the ones with an address.
      [a note, a photo with a copy, 8 more photos], pictures 6 -> the note, 6 photo lines, "3 more pictures match…", how to show"""
    lines: list[str] = []
    shown, extra, any_address = 0, 0, False
    for h in hits:
        if h.kind == "note" and h.note is not None:
            lines.append(note_line(h.note))
        elif h.photo is not None:
            if shown >= pictures:
                extra += 1
                continue
            shown += 1
            any_address = any_address or h.photo.has_thumb
            lines.append(picture_line(h.photo))
    if extra:
        lines.append(f"{extra} more pictures match: ask for more, or narrow by who, where or when.")
    if any_address:
        lines.append(HOW_TO_SHOW)
    return "\n".join(lines)


def make_vault_tools(store) -> list[FunctionTool]:
    def index():
        return settings.index_for(store)

    async def search_everything(query: str, only: str | None = None, people: list[str] | None = None, place: str | None = None,
                                since: str | None = None, until: str | None = None, album: str | None = None, k: int = 8,
                                photos: int = PHOTOS_SHOWN) -> str:
        """Search the user's own things in one go, like Spotlight: their notes (the Obsidian vault: anything they wrote, decided, planned or studied) and their photos and videos (what Photos knows about each: who is in it, what it shows, where and when, its albums; and what is in the picture itself, when pictures are read by meaning). One ranked list, best first, each line tagged [note], [photo] or [video]. only: docs, media, photos or videos narrows the kinds (leave it out to search everything). Filters for pictures, applied after the search: people (every name must be in it), place, since and until (ISO dates), album; with a filter or only=media the query may be empty (newest first). k: note passages (up to 20). photos: pictures listed (up to 12; more are counted, not listed). Cite notes by name and prefer recent ones; show pictures with an odie-images block using the addresses returned; a photo's photo:<id> address is what make_video's images (and a deck) take."""
        ix = index()
        if ix is None:
            return "Neither notes nor photos are set up."
        only = only if only in ONLY else None
        pictures_on = photos_on(store)
        if only in ("media", "photos", "videos") and not pictures_on:
            return "Photos aren't on: turn them on in Settings → Photos to search pictures."
        if only is None and not pictures_on:
            only = "docs"
        if only is None and not settings.configured(store):
            only = "media"
        hits = await ix.search_all(query or "", k=max(1, min(k, 20)), embedder=settings.embedder_for(store), only=only,
                                   people=people, place=place, since=since, until=until, album=album)
        if hits:
            return result_lines(hits, max(1, min(photos, PHOTOS_MOST)))
        where = "notes or photos" if pictures_on and settings.configured(store) else ("photos" if pictures_on else "notes")
        return f"Nothing in the {where} matches that. Try other words, or say it isn't there."

    async def read_note(note: str) -> str:
        """Read one whole note by its name, title, alias or path (very long notes are cut). Use after search_everything when a passage is not enough."""
        ix = index()
        text = ix.read(note) if ix else None
        return text if text is not None else f"No note called {note!r} in the vault."

    async def related_notes(note: str, k: int = 8) -> str:
        """Notes connected to one note: by meaning when that is set up, else the notes it links to, the ones linking to it, and ones sharing its tags."""
        ix = index()
        hits = await ix.related(note, k=max(1, min(k, 20))) if ix else []
        return _lines(hits, 300) if hits else f"No notes related to {note!r} found."

    async def index_status() -> str:
        """How the index is doing: notes and passages, keyword or meaning search, photos and videos read, the last scan, any error."""
        ix = index()
        if ix is None:
            return "Neither notes nor photos are set up."
        st = ix.status()
        how = f"keyword and meaning ({st['model']}, {st['vectors']} of {st['chunks']} passages)" if st["model"] else "keyword"
        out = f"{st['notes']} notes, {st['chunks']} passages; search: {how}; last scan {st['scanned_at'] or 'not yet'}."
        if photos_on(store):
            out += f" Photos: {st['photos']} photos and {st['videos']} videos (read {st['photos_at'] or 'not yet'})"
            out += f"; pictures by meaning: {st['photo_vectors']} of {st['photos'] + st['videos']}." if st["model"] else "."
        return out + (f" Embedding error: {st['embed_error']}" if st["embed_error"] else "")

    return [FunctionTool(search_everything), FunctionTool(read_note), FunctionTool(related_notes), FunctionTool(index_status)]


def photos_on(store) -> bool:
    return photos.is_on(store)


VAULT_TOOLS = frozenset({"search_everything", "read_note", "related_notes", "index_status"})
