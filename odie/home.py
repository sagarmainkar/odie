"""Where Odie keeps everything: one folder, ~/.odie (ODIE_HOME moves it). Inside it: .env (keys and settings),
SOUL.md, mcp.json, memories.md, skills/, addons/, data/ (databases, push keys, photos), logs/ and app/.
ODIE_DATA_DIR / ODIE_CONFIG_DIR set the folders directly instead (tests, test copies)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Layout:
    home: Path | None  # None: folders set directly, with no home folder around them
    data_dir: Path
    config_dir: Path


def resolve(user_home: Path | None = None) -> Layout:
    explicit = os.environ.get("ODIE_HOME")
    root = Path(explicit).expanduser() if explicit else (user_home or Path.home()) / ".odie"
    data, conf = os.environ.get("ODIE_DATA_DIR"), os.environ.get("ODIE_CONFIG_DIR")
    if not data and not conf:
        return Layout(root, root / "data", root)
    # Folders set directly stand alone: no home folder unless ODIE_HOME names one, so nothing (memory, logs)
    # lands in a real ~/.odie by default.
    return Layout(root if explicit else None, Path(data).expanduser() if data else root / "data",
                  Path(conf).expanduser() if conf else root)


def ensure(layout: Layout) -> None:
    """Create the folders on first start; the home folder is the owner's alone (it holds keys and chats)."""
    if layout.home is not None:
        layout.home.mkdir(mode=0o700, parents=True, exist_ok=True)
        layout.home.chmod(0o700)
    layout.data_dir.mkdir(parents=True, exist_ok=True)
    layout.config_dir.mkdir(parents=True, exist_ok=True)
