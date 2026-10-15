"""A picture's original from iCloud, on request. Most originals aren't on this Mac ("Optimise Mac Storage"), so a video
can't play and a photo has only its 2048 px copy. A tap asks Photos, through PhotoKit (osxphotos' export with
download_missing), to download the original into <data>/photos-fetched/<uuid>.<ext>; the chat polls until it's there
and then plays or shows it. The file stays, so the next tap is instant; the folder can be emptied any time. macOS may
ask once, on the Mac, to let Odie's Python use Photos; a refusal is said plainly."""
from __future__ import annotations

import asyncio
import logging
import mimetypes
import re
from pathlib import Path

log = logging.getLogger("odie.photos")
TYPES = {".mov": "video/quicktime", ".mp4": "video/mp4", ".m4v": "video/x-m4v", ".heic": "image/heic", ".heif": "image/heif",
         ".jpeg": "image/jpeg", ".jpg": "image/jpeg", ".png": "image/png", ".gif": "image/gif", ".webp": "image/webp", ".tiff": "image/tiff"}
_jobs: dict[str, dict] = {}  # uuid -> {"state": "fetching" | "failed", "error": str}; "ready" is the file itself


class FetchError(Exception):
    """A plain reason, said to the user as it is."""


def fetched_dir() -> Path:
    from odie import config
    return config.settings.data_dir / "photos-fetched"


def fetched_file(uuid: str, folder: Path) -> Path | None:
    """The fetched original for this uuid, whatever its extension (Photos decides it): <uuid>.MOV, <uuid>.heic…"""
    for p in Path(folder).glob(f"{uuid}.*"):
        if p.is_file():
            return p
    return None


def media_type(path: Path) -> str:
    return TYPES.get(path.suffix.lower()) or mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def plain_reason(e: Exception) -> str:
    """What went wrong, in words the user can act on:
      "…not authorized…" -> allow Odie's Python under Privacy & Security → Photos
      "…isn't in the cloud…" -> Photos says the original isn't in iCloud"""
    text = str(e)
    if re.search(r"not authori[sz]ed|3311|permission|denied", text, re.I):
        return ("macOS didn't let Odie ask Photos for the original. In System Settings → Privacy & Security → Photos, allow "
                "Odie's Python, then tap again.")
    if re.search(r"cloud|network|offline|internet", text, re.I):
        return f"Photos couldn't fetch it from iCloud: {text[:160]}"
    return f"{type(e).__name__}: {text}"[:300]


def download(uuid: str, folder: Path) -> Path:
    """Ask Photos for the original of this picture and put it in `folder` as <uuid>.<ext>. Blocks for as long as the
    download takes (a 4K minute is a few hundred MB). FetchError with a plain reason when it can't."""
    import osxphotos
    from osxphotos.photoexporter import ExportOptions, PhotoExporter

    from odie.photos.library import library_path
    lib = library_path()
    if not lib:
        raise FetchError("There's no Photos library on this computer.")
    folder.mkdir(parents=True, exist_ok=True)
    try:
        photo = osxphotos.PhotosDB(dbfile=lib).get_photo(uuid)
        if photo is None:
            raise FetchError("Photos doesn't have that picture any more.")
        result = PhotoExporter(photo).export(str(folder), options=ExportOptions(download_missing=True, use_photokit=True, overwrite=True))
    except FetchError:
        raise
    except Exception as e:  # noqa: BLE001
        raise FetchError(plain_reason(e)) from e
    if result.error:
        raise FetchError(plain_reason(Exception(str(result.error[0][1]) if result.error[0] else "export failed")))
    if not result.exported:
        raise FetchError("Photos couldn't fetch it from iCloud (it exported nothing).")
    got = Path(result.exported[0])
    final = folder / f"{uuid}{got.suffix}"
    if got != final:
        got.replace(final)
    return final


def status(uuid: str, folder: Path | None = None) -> dict:
    """Where the original stands: ready (the file is here), fetching, failed (with why), or missing (never asked).
      a file <uuid>.MOV in the folder -> {"state": "ready", "error": ""}
      a job running                   -> {"state": "fetching", "error": ""}"""
    if fetched_file(uuid, folder or fetched_dir()):
        return {"state": "ready", "error": ""}
    job = _jobs.get(uuid)
    if job:
        return dict(job)
    return {"state": "missing", "error": ""}


def start(uuid: str, folder: Path | None = None) -> dict:
    """Begin fetching unless it's here or on its way; returns the status after that."""
    folder = folder or fetched_dir()
    now = status(uuid, folder)
    if now["state"] in ("ready", "fetching"):
        return now
    folder.mkdir(parents=True, exist_ok=True)
    _jobs[uuid] = {"state": "fetching", "error": ""}

    async def run():
        try:
            await asyncio.to_thread(download, uuid, folder)
            _jobs.pop(uuid, None)
        except Exception as e:  # noqa: BLE001
            log.warning("fetching %s failed: %s", uuid, e)
            _jobs[uuid] = {"state": "failed", "error": str(e) if isinstance(e, FetchError) else plain_reason(e)}
    asyncio.get_running_loop().create_task(run())
    return status(uuid, folder)
