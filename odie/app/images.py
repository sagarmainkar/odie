"""Photos from the phone: downscale to 1280 px on the long edge, JPEG, saved under the data dir by id.
Keeps vision turns fast on this computer and the session database small."""
from __future__ import annotations

import io
import re
import uuid
from pathlib import Path

from PIL import Image, ImageOps

MAX_EDGE = 1280
ID_RE = re.compile(r"^[0-9a-f]{32}$")


def uploads_dir() -> Path:
    from odie import config
    d = config.settings.data_dir / "uploads"
    d.mkdir(parents=True, exist_ok=True)
    return d


def prepare_image(data: bytes, directory: Path) -> dict:
    img = Image.open(io.BytesIO(data))
    img = ImageOps.exif_transpose(img)
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    img.thumbnail((MAX_EDGE, MAX_EDGE))
    iid = uuid.uuid4().hex
    path = directory / f"{iid}.jpg"
    directory.mkdir(parents=True, exist_ok=True)
    img.save(path, "JPEG", quality=85, optimize=True)
    return {"id": iid, "w": img.width, "h": img.height, "mime": "image/jpeg", "path": str(path)}


def load_image(iid: str, directory: Path | None = None) -> tuple[bytes, str] | None:
    if not ID_RE.match(iid or ""):
        return None
    p = (directory or uploads_dir()) / f"{iid}.jpg"
    return (p.read_bytes(), "image/jpeg") if p.exists() else None
