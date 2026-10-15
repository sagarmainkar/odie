"""The vault (spec "Sign in for me", Part 1): saved logins in the login keychain of the Mac that runs Odie, never read
by the AI. Each is an internet password (server: the site, account: the username, label "Odie: <site>", comment
"Saved by Odie", creator "odie"), written through `security -i` on its standard input so the password never shows in
a process list, and kept base64-encoded ("b64:...") because `security` prints a non-ASCII password as hex. The list
Settings shows lives in the store (browser.logins: {site: {username, saved_at, last_used}}), without passwords.
Tests point ODIE_KEYCHAIN at a throwaway keychain: they never touch the login keychain."""
from __future__ import annotations

import base64
import binascii
import logging
import os
import subprocess
from datetime import datetime

from odie.signin import sites

KEY = "browser.logins"
COMMENT = "Saved by Odie"
CREATOR = "odie"
UNREADABLE = "Odie couldn't open its vault on the Mac."
log = logging.getLogger("odie.signin")


class VaultError(Exception):
    pass


def _keychain() -> list[str]:
    """The keychain to use: ODIE_KEYCHAIN (tests), else the default (the login keychain). Given a file that doesn't
    exist, `security` quietly falls back to the login keychain (found 2026-10-08), so that refuses before any call."""
    k = os.environ.get("ODIE_KEYCHAIN")
    if k and not os.path.exists(k):
        raise VaultError(UNREADABLE)
    return [k] if k else []


def _q(s: str) -> str:
    """One word for `security -i`: double-quoted, with backslashes and quotes escaped (checked 2026-10-08)."""
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _security(args: list[str], stdin: str | None = None) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(["security", *args], input=stdin, capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise VaultError(UNREADABLE) from e


def _all(store) -> dict:
    return dict(store.get_setting(KEY) or {})


def _read(site: str, username: str) -> str | None:
    """The stored value ("b64:..."), or None when the Keychain doesn't give it (missing, or locked: they look alike)."""
    r = _security(["find-internet-password", "-s", site, "-a", username, "-j", COMMENT, "-w", *_keychain()])
    return r.stdout.rstrip("\n") if r.returncode == 0 else None


def _remove(site: str, username: str) -> None:
    _security(["delete-internet-password", "-s", site, "-a", username, "-j", COMMENT, *_keychain()])


def listing(store) -> list[dict]:
    return sorted(({"site": s, **v} for s, v in _all(store).items()), key=lambda x: x["site"])


def save(store, site: str, username: str, password: str, now: datetime) -> None:
    if any(ord(c) < 32 or ord(c) == 127 for c in f"{site}{username}"):
        raise ValueError("A site or username can't hold control characters.")  # a newline would split the security command
    d, user = sites.site_of(site), (username or "").strip()
    if not d or not user or not password:
        raise ValueError("A login needs the site, a username and a password.")
    got = _all(store)
    old = got.get(d)
    if old and old.get("username") != user:
        _remove(d, old["username"])  # one login per site: the new one replaces it
    _remove(d, user)  # never update in place: changing an item's content needs a person's authorization (a prompt)
    stored = "b64:" + base64.b64encode(password.encode()).decode()
    cmd = (f"add-internet-password -a {_q(user)} -s {_q(d)} -r htps -l {_q('Odie: ' + d)} -j {_q(COMMENT)} -c {CREATOR} "
           f"-T /usr/bin/security -w {_q(stored)}" + "".join(" " + _q(k) for k in _keychain()) + "\n")
    _security(["-i"], stdin=cmd)
    if _read(d, user) != stored:  # `security -i` exits 0 even when it failed: check it's really there
        raise VaultError("Odie couldn't save it in the Mac's Keychain.")
    got[d] = {"username": user, "saved_at": now.isoformat(timespec="seconds"), "last_used": (old or {}).get("last_used")}
    store.set_setting(KEY, got)
    store.audit("user", "login_saved", result_summary=d)


def get(store, site: str) -> tuple[str, str] | None:
    d = sites.site_of(site)
    entry = _all(store).get(d)
    if not entry:
        return None
    raw = _read(d, entry["username"])
    if raw is None:
        raise VaultError(UNREADABLE)  # never forget it here: a locked keychain answers like a missing item
    if not raw.startswith("b64:"):
        return entry["username"], raw
    try:
        return entry["username"], base64.b64decode(raw[4:]).decode()
    except (binascii.Error, UnicodeDecodeError) as e:
        raise VaultError(UNREADABLE) from e


def used(store, site: str, now: datetime) -> None:
    got, d = _all(store), sites.site_of(site)
    if d in got:
        got[d]["last_used"] = now.isoformat(timespec="seconds")
        store.set_setting(KEY, got)
        store.audit("agent", "login_used", result_summary=d)


def delete(store, site: str) -> bool:
    got, d = _all(store), sites.site_of(site)
    entry = got.pop(d, None)
    if entry is None:
        return False
    _remove(d, entry["username"])
    store.set_setting(KEY, got)
    store.audit("user", "login_deleted", result_summary=d)
    return True


def forget_all(store) -> int:
    got = _all(store)
    for d, entry in got.items():
        try:
            _remove(d, entry["username"])
        except VaultError:
            log.warning("a saved login couldn't be removed from the Keychain")
    store.set_setting(KEY, {})
    if got:
        store.audit("user", "logins_forgotten", result_summary=str(len(got)))
    return len(got)
