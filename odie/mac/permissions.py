"""Whether macOS lets Odie control each app, read without raising a dialog (AEDeterminePermissionToAutomateTarget,
askUserIfNeeded false), and asked for on purpose (the probe script, which makes macOS show its dialog). The service
runs as python under launchd, so the dialog names python; the grant is per app, once."""
from __future__ import annotations

import ctypes
import json
import logging
import struct
import time
from dataclasses import dataclass
from pathlib import Path

from odie.mac import scripts

log = logging.getLogger("odie.mac")

APPS: dict[str, str] = {"mail": "Mail", "calendar": "Calendar", "reminders": "Reminders", "contacts": "Contacts"}
BUNDLES: dict[str, str] = {"mail": "com.apple.mail", "calendar": "com.apple.iCal", "reminders": "com.apple.reminders",
                           "contacts": "com.apple.AddressBook"}
# Apps Odie doesn't offer yet: no Settings row, no Allow, no tool. Contacts (21 Oct 2026): its Allow came back
# refused on the owner's Mac without a dialog, and nothing needs it yet. odie.mac.contacts and its script stay.
HELD_BACK = frozenset({"contacts"})
GRANTED, DENIED, UNKNOWN = "granted", "denied", "unknown"
CACHE_FOR = 60.0
_cache: dict[str, tuple[float, str]] = {}
MEMORY = "mac-permissions.json"  # in the data dir: {"mail": "granted", …}, what macOS last said for sure


@dataclass
class AppRow:
    id: str
    name: str
    status: str

    def as_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "status": self.status}


def _fourcc(s: str) -> int:
    return struct.unpack(">I", s.encode())[0]


def _determine(bundle: str) -> int:
    """AEDeterminePermissionToAutomateTarget for a bundle id, never asking: 0 granted, -1743 denied, -1744 not yet
    asked, -600 the app isn't running (then macOS can't say). Raises OSError when CoreServices can't be loaded."""
    cs = ctypes.CDLL("/System/Library/Frameworks/CoreServices.framework/CoreServices")

    class AEDesc(ctypes.Structure):
        _fields_ = [("descriptorType", ctypes.c_uint32), ("dataHandle", ctypes.c_void_p)]

    create = cs.AECreateDesc
    create.argtypes = [ctypes.c_uint32, ctypes.c_void_p, ctypes.c_long, ctypes.POINTER(AEDesc)]
    create.restype = ctypes.c_int32
    dispose = cs.AEDisposeDesc
    dispose.argtypes = [ctypes.POINTER(AEDesc)]
    determine = cs.AEDeterminePermissionToAutomateTarget
    determine.argtypes = [ctypes.POINTER(AEDesc), ctypes.c_uint32, ctypes.c_uint32, ctypes.c_bool]
    determine.restype = ctypes.c_int32
    desc = AEDesc()
    data = bundle.encode()
    if create(_fourcc("bund"), data, len(data), ctypes.byref(desc)) != 0:
        raise OSError("AECreateDesc failed")
    try:
        return determine(ctypes.byref(desc), _fourcc("****"), _fourcc("****"), False)
    finally:
        dispose(ctypes.byref(desc))


def status_of(code: int) -> str:
    """What a determine code means for the row: 0 -> granted; -1743 -> denied; -1744 (never asked) -> unknown;
    -600 (the app isn't running, macOS can't tell) -> unknown."""
    if code == 0:
        return GRANTED
    if code == -1743:
        return DENIED
    return UNKNOWN


def _memory_path() -> Path:
    from odie import config
    return Path(config.settings.data_dir) / MEMORY


def remembered() -> dict[str, str]:
    try:
        got = json.loads(_memory_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in got.items() if isinstance(v, str)} if isinstance(got, dict) else {}


def remember(app_id: str, what: str) -> None:
    """Keeps what macOS said for sure (a grant from the dialog, a denial from a failed call), for the times it can't
    say: AEDeterminePermissionToAutomateTarget answers "can't tell" (-600) while the app isn't running, as after a
    reboot, and the watch must not drop Mail for that."""
    kept = remembered()
    kept[app_id] = what
    try:
        path = _memory_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(kept), encoding="utf-8")
    except OSError:
        log.warning("mac: couldn't remember the %s permission", app_id, exc_info=True)
    _cache.pop(app_id, None)


def status(app_id: str, determine=None, now=time.monotonic) -> str:
    """The permission for one app without a dialog, cached for CACHE_FOR seconds. macOS's answer when it has one;
    when it can't say (the app isn't running, CoreServices unavailable), what was remembered from the dialog or a
    failed call; else "unknown". status("mail") on the owner's mini -> "granted"; Calendar closed after a reboot, its
    dialog allowed last week -> "granted"; never asked -> "unknown"."""
    kept = _cache.get(app_id)
    if kept and now() - kept[0] < CACHE_FOR:
        return kept[1]
    try:
        code = (determine or _determine)(BUNDLES[app_id])
    except (OSError, KeyError, AttributeError) as e:
        log.info("mac: permission for %s can't be read: %s", app_id, e)
        code = -600
    got = status_of(code)
    if code == -600 or (got == UNKNOWN and code != -1744):
        got = remembered().get(app_id, UNKNOWN)
    _cache[app_id] = (now(), got)
    return got


def forget(app_id: str | None = None) -> None:
    """Drops the cached statuses (after a request, or in tests)."""
    if app_id is None:
        _cache.clear()
    else:
        _cache.pop(app_id, None)


async def request(app_id: str, run=scripts.run) -> str:
    """Asks on purpose: runs the probe so macOS shows its dialog on this Mac, waits for the answer, and returns the
    status after it. A denial -> "denied"; the dialog allowed -> "granted"."""
    forget(app_id)
    try:
        await run("probe", APPS[app_id], app=APPS[app_id], timeout=120)
        got = GRANTED
    except scripts.MacPermission:
        got = DENIED
    except scripts.MacError as e:
        log.warning("mac: probing %s failed: %s", app_id, e)
        got = UNKNOWN
    if got != UNKNOWN:
        remember(app_id, got)
    _cache[app_id] = (time.monotonic(), got)
    return got


def offered(app_id: str) -> bool:
    """Whether Settings shows the app and its Allow may ask macOS: "mail" -> True; "contacts" (held back) -> False;
    "notes" (no such app) -> False."""
    return app_id in APPS and app_id not in HELD_BACK


def rows(determine=None) -> list[AppRow]:
    """Every offered app with its status, in the Settings order."""
    return [AppRow(app_id, name, status(app_id, determine)) for app_id, name in APPS.items() if offered(app_id)]
