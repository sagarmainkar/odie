"""Files the user gets from the chat (odie.media). make_file writes a text file into Odie's workspace; attach_file
hands over one a skill or the shell made there. A picture, a video or a sound is shown or played under the reply
(its kind says so); anything else is a download card. Nothing outside the workspace is ever attached."""
from __future__ import annotations

import mimetypes
import re
from pathlib import Path

from google.adk.tools import FunctionTool

from odie import media

MAKE_TYPES = {"md": "text/markdown", "txt": "text/plain", "csv": "text/csv", "html": "text/html", "json": "application/json",
              "ics": "text/calendar", "svg": "image/svg+xml"}
# Files shown or played inline rather than offered as a download, by extension (what the browser can draw or play).
SHOWN = {"picture": ("png", "jpg", "jpeg", "webp", "gif", "svg"), "video": ("mp4", "webm", "mov", "m4v"),
         "audio": ("mp3", "m4a", "wav", "ogg", "aac")}
OFFICE = {"pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
          "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
          "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}
MAX_MAKE = 1_000_000
MAX_ATTACH = 50 * 1024 * 1024


def workspace() -> Path:
    from odie import config
    d = config.settings.data_dir / "workspace"
    d.mkdir(parents=True, exist_ok=True)
    return d


workspace_root = workspace  # the workspace itself (decks cache their photos under it)


def safe_name(name: str) -> str:
    """A file name with no folders, control or reserved characters, at most 80 characters (the extension kept)."""
    base = Path((name or "").replace("\\", "/")).name
    base = re.sub(r"[\x00-\x1f\x7f<>:\"/\\|?*]", "", base)
    base = " ".join(base.split()).strip(" .")
    stem, dot, ext = base.rpartition(".")
    if dot and len(base) > 80:
        base = stem[: 80 - len(ext) - 1].rstrip(" .") + "." + ext
    return base[:80] or "file"


def _free(folder: Path, name: str) -> Path:
    """`name` in `folder`, or "name (2).ext" and so on: an existing file is never overwritten."""
    p = folder / name
    stem, ext = p.stem, p.suffix
    n = 2
    while p.exists():
        p = folder / f"{stem} ({n}){ext}"
        n += 1
    return p


def _size(n: int) -> str:
    return f"{n} B" if n < 1024 else f"{n / 1024:.0f} KB" if n < 1024 * 1024 else f"{n / 1024 / 1024:.1f} MB"


def in_workspace(path: str) -> Path | None:
    """Where a path the model gave really points, when that is inside Odie's workspace; None when it points outside.
    Relative paths start at the workspace, and links and ".." are followed first:
    "notes/tides.txt" -> <workspace>/notes/tides.txt; "../secret.txt", "~/secret.txt", "/etc/hosts", a link that
    leads out, or a path with a NUL byte in it (no file can have one) -> None."""
    if "\x00" in path:
        return None
    ws = workspace().resolve()
    given = Path(path).expanduser()
    if not given.is_absolute():
        given = ws / given
    real = given.resolve()
    if not real.is_relative_to(ws):
        return None
    return real


def kind_of(ext: str) -> str:
    """How the chat treats a file, by its extension: "logo.svg" / "png" -> picture (shown), "mp4" -> video (played),
    "m4a" -> audio (played), "csv" / "pptx" / anything else -> file (a download card)."""
    ext = ext.lower().lstrip(".")
    for kind, exts in SHOWN.items():
        if ext in exts:
            return kind
    return "file"


def hand_over(path: Path, title: str = "") -> dict:
    """The file as a card under the reply (a picture shown, a video or sound played, anything else a download):
    its media, and the short result the model sees."""
    ext = path.suffix.lower().lstrip(".")
    mime = MAKE_TYPES.get(ext) or OFFICE.get(ext) or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    data = path.read_bytes()
    stored = re.sub(r"[^a-z0-9]", "", ext)[:8] or "bin"  # the name on disk; the download keeps the file's own
    kind = kind_of(ext)
    m = media.save(data, kind, stored, mime, title or path.name, {"filename": path.name})
    how = {"picture": "is shown under your reply", "video": "plays under your reply", "audio": "plays under your reply"}
    said = how.get(kind, "is under your reply, ready to download")
    return {"result": f"{path.name} ({_size(len(data))}) {said}.", "media": {k: m[k] for k in ("id", "kind", "title", "filename", "size")}}


def make_file_tools() -> list[FunctionTool]:
    async def make_file(name: str, content: str, title: str = "") -> dict:
        """Make a file for the user from the chat: a spreadsheet (.csv), notes (.md or .txt), a web page (.html), data
        (.json), a calendar event (.ics) or a drawing (.svg, shown right under your reply; for a drawing in the reply
        itself an ```odie-svg block needs no file). `name` is the file name with its extension ("Goa packing list.csv");
        `content` is the whole file. The card appears under your reply. For slides (PowerPoint) or a Word document,
        load the documents skill instead."""
        fname = safe_name(name)
        ext = Path(fname).suffix.lower().lstrip(".")
        if not ext:
            return {"error": "Give the file name with its extension: .csv, .md, .txt, .html, .json, .ics or .svg."}
        if ext not in MAKE_TYPES:
            return {"error": f"I can make .csv, .md, .txt, .html, .json, .ics or .svg files here, not .{ext}. For slides or a Word "
                             "document, load the documents skill."}
        data = (content or "").encode("utf-8")
        if len(data) > MAX_MAKE:
            return {"error": "That's more than 1 MB of text: make it shorter, or split it into files."}
        try:
            path = _free(workspace(), fname)
            path.write_bytes(data)
            return hand_over(path, title)
        except OSError as e:
            return {"error": f"The file couldn't be saved ({e.strerror or type(e).__name__})."}

    async def attach_file(path: str, title: str = "") -> dict:
        """Attach a file you made in Odie's workspace (with the shell or a skill). A picture (png, jpg, webp, gif, svg)
        is shown under your reply, a video (mp4, webm, mov) or a sound (mp3, m4a, wav) plays there, anything else is
        a download card. `path` is inside the workspace: relative to it, or absolute."""
        ws = workspace().resolve()
        real = in_workspace(path)
        if real is None:
            return {"error": f"Only files in Odie's workspace ({ws}) can be attached."}
        if not real.is_file():
            return {"error": f"There's no file at {real.relative_to(ws)} in Odie's workspace ({ws}): save it there first."}
        if real.stat().st_size > MAX_ATTACH:
            return {"error": "That file is over 50 MB: too big to attach."}
        try:
            return hand_over(real, title)
        except (OSError, ValueError) as e:
            return {"error": f"The file couldn't be attached ({getattr(e, 'strerror', None) or e})."}

    return [FunctionTool(make_file), FunctionTool(attach_file)]
