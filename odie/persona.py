"""The assistant's name and picture, chosen by the user in Settings. Default: "Odie" and the copper orb."""
from __future__ import annotations

import io
import re
import uuid
from pathlib import Path

from odie import config
from odie.store.db import Store

DEFAULT_NAME = "Odie"
MAX_NAME = 24
AVATAR_PX = 512
_ID = re.compile(r"^[0-9a-f]{32}$")


def _dir(directory: Path | None = None) -> Path:
    return directory or (config.settings.data_dir / "avatar")


def get(store: Store) -> dict:
    p = store.get_setting("persona") or {}
    return {"name": p.get("name") or DEFAULT_NAME, "avatar": p.get("avatar")}


def _save(store: Store, p: dict) -> dict:
    store.set_setting("persona", p)
    return get(store)


def set_name(store: Store, name: str) -> dict:
    clean = " ".join((name or "").split())[:MAX_NAME].strip()
    return _save(store, {**get(store), "name": clean or DEFAULT_NAME})


def apply_name(text: str, name: str) -> str:
    """Swap the default name for the chosen one, whole words only (prompt, SOUL)."""
    return text if name == DEFAULT_NAME else re.sub(rf"\b{DEFAULT_NAME}\b", name, text)


def store_picture(data: bytes, directory: Path | None = None) -> str:
    """Save a picture as a square JPEG and return its id. It becomes nobody's picture here: save_avatar makes it
    Odie's, odie.personalities.set_avatar a personality's."""
    from PIL import Image, ImageOps
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    img = ImageOps.fit(img, (AVATAR_PX, AVATAR_PX), method=Image.LANCZOS, centering=(0.5, 0.4))  # faces sit a little high
    d = _dir(directory)
    d.mkdir(parents=True, exist_ok=True)
    aid = uuid.uuid4().hex
    img.save(d / f"{aid}.jpg", "JPEG", quality=88, optimize=True)
    return aid


def delete_picture(aid: str | None, directory: Path | None = None) -> None:
    """Remove a picture's file; an id that isn't one, or a file already gone, is left alone."""
    path = avatar_path(aid, directory)
    if path is not None:
        path.unlink(missing_ok=True)


def save_avatar(store: Store, data: bytes, directory: Path | None = None) -> dict:
    """Odie's own picture: saved, then set."""
    aid = store_picture(data, directory)
    return _save(store, {**get(store), "avatar": aid})


def clear_avatar(store: Store) -> dict:
    return _save(store, {**get(store), "avatar": None})


def avatar_path(aid: str | None, directory: Path | None = None) -> Path | None:
    if not aid or not _ID.match(aid):
        return None
    p = _dir(directory) / f"{aid}.jpg"
    return p if p.is_file() else None
