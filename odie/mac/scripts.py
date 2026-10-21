"""Running the fixed AppleScripts in odie/mac/scripts/ through osascript. Each script has an `on run argv` handler
and gets its arguments as argv (never spliced into the text); the shared handlers in _lib.applescript are appended
at load time, since AppleScript has no include. Errors come back as three exceptions: MacPermission (macOS hasn't
allowed Odie to control that app), MacTimeout, and MacError for the rest (the script's own message)."""
from __future__ import annotations

import asyncio
import platform
import re
import shutil
from pathlib import Path

SCRIPTS = Path(__file__).parent / "scripts"
TIMEOUT = 60.0
ALLOWED = True  # tests switch this off (tests/conftest.py), so no test ever reads the developer's own Mail
NOT_ALLOWED = re.compile(r"-1743|Not authori[sz]ed to send Apple events", re.I)


class MacError(Exception):
    """The script failed; str() is osascript's message, trimmed."""


class MacPermission(MacError):
    """macOS hasn't let Odie control this app (its name is in the message)."""


class MacTimeout(MacError):
    """The app didn't answer in time."""


def available() -> bool:
    """Whether the Mac apps can be driven here at all: macOS with osascript on the path. A Linux box -> False."""
    return platform.system() == "Darwin" and shutil.which("osascript") is not None


def source(name: str) -> str:
    """The whole text osascript runs for a script: its own file, then the shared handlers.
    "probe" -> the probe script with q(), iso() and the rest appended."""
    own = (SCRIPTS / f"{name}.applescript").read_text(encoding="utf-8")
    lib = (SCRIPTS / "_lib.applescript").read_text(encoding="utf-8")
    return f"{own}\n\n{lib}"


def app_in(message: str, fallback: str) -> str:
    """Which app a "not authorised" error is about, from osascript's wording, else `fallback`.
    'Not authorized to send Apple events to Calendar. (-1743)' -> "Calendar"; anything else -> fallback"""
    m = re.search(r"Apple events to ([A-Za-z ]+?)\.", message)
    return m.group(1).strip() if m else fallback


async def run(name: str, *args: str, app: str = "", timeout: float = TIMEOUT) -> str:
    """Runs one script with its arguments and returns its stdout (JSON for all but the probe).
    run("mail_new", "2026-10-21T09:00", "25") -> the JSON list; an app that isn't allowed -> MacPermission."""
    if not ALLOWED:
        raise MacError("the Mac apps are switched off here")
    proc = await asyncio.create_subprocess_exec(
        "osascript", "-", *[str(a) for a in args],
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        out, err = await asyncio.wait_for(proc.communicate(source(name).encode("utf-8")), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise MacTimeout(f"{app or name} didn't answer in {timeout:.0f} s") from None
    message = err.decode("utf-8", "replace").strip()
    if proc.returncode != 0:
        if NOT_ALLOWED.search(message):
            raise MacPermission(app_in(message, app or name))
        raise MacError(message[-300:] or f"{name} failed")
    return out.decode("utf-8", "replace").strip()
