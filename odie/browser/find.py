"""Finding a Chromium-family browser on this computer (nothing is installed for it)."""
from __future__ import annotations

import os
import shutil
from pathlib import Path

_MAC = ["Google Chrome.app/Contents/MacOS/Google Chrome", "Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        "Chromium.app/Contents/MacOS/Chromium", "Brave Browser.app/Contents/MacOS/Brave Browser"]
CANDIDATES = [str(Path(root) / app) for root in ("/Applications", str(Path.home() / "Applications")) for app in _MAC]
NAMES = ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge", "brave-browser"]


def _runnable(path: str) -> bool:
    return Path(path).is_file() and os.access(path, os.X_OK)


def browser_binary() -> str | None:
    """ODIE_BROWSER (a path, or "off") wins; else the first browser found here, or None."""
    forced = os.environ.get("ODIE_BROWSER", "").strip()
    if forced:
        return None if forced.lower() in ("off", "0", "no", "false") or not _runnable(forced) else forced
    return installed()


def installed() -> str | None:
    """The first Chromium-family browser on this computer, whatever ODIE_BROWSER says."""
    for path in CANDIDATES:
        if _runnable(path):
            return path
    for name in NAMES:
        if found := shutil.which(name):
            return found
    return None
