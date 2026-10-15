"""Paired devices: while pairing is on, Odie answers only the browsers it knows.

- A device is a browser holding a random 256-bit key in an httpOnly cookie. Only the key's sha256 is stored.
- A new device pairs with a one-time code (10 minutes; Settings shows it as text and as a QR code), or with the
  four-word recovery passcode (scrypt). Five wrong passcodes lock it for 10 minutes, for every device, across restarts.
- The first device comes through a one-time setup link, written to <config>/setup-link for the installer to open while
  nothing is paired.
- An install that already chats starts with pairing off; its owner turns it on from Settings.
None of the secrets is logged or put in the audit log."""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import re
import secrets
import time
from pathlib import Path

COOKIE = "odie_device"
COOKIE_AGE = 365 * 24 * 3600
CODE_TTL = 10 * 60
LOCK_AFTER = 5
LOCK_FOR = 10 * 60
EXEMPT = ("/api/health", "/api/pair/")
PRIVATE = {"detail": "This Odie is private.", "pair": True}
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O or 1/I to misread
_PAIRING, _PASSCODE, _TRIES = "pairing", "pairing_passcode", "pairing_tries"

WORDS = tuple("""
acorn anchor atlas apple arrow autumn badge bakery bamboo banjo barn basil beach beacon bean bear bell berry bike birch bird blanket bloom
boat bone book boot bottle bread breeze brick bridge brook brush bucket butter cabin cactus cake camel camera candle
canoe canyon carpet carrot castle cedar chair chalk cherry chess cider circle cliff clock cloud clover coast cocoa comet
copper coral cotton crane crayon creek cricket crown cup daisy dawn desert dinner dolphin door dragon dream drum eagle
earth echo elbow ember engine falcon feather fence fern field fig finch flag flame flute forest fossil fox frost garden
garlic ginger glacier globe glove goat gold grape grass gravel guitar hammer harbor harp hazel helmet heron hill honey
horse island ivory jacket jade jam jar jelly jungle kettle key kite kiwi ladder lake lamp lantern leaf lemon lily lime
lion lizard llama lotus magnet mango maple marble meadow melon mint mirror mitten moon moss mountain mouse mule mushroom
needle nest noodle nutmeg oak oasis ocean olive onion orange orbit otter owl paddle panda paper parrot peach peanut pearl
pebble pencil pepper piano pickle pigeon pillow pine planet plum pond poppy potato prairie puzzle quilt rabbit radio rain
raven reef ribbon river robin rocket rose ruby saddle salmon sand scarf seal shell silver sky sled snow sock sparrow
spoon spruce star stone storm straw stream sugar summer sun swan table teapot thistle thunder tiger timber toast tomato
topaz tower trail tulip turtle valley velvet violet violin wagon walnut whale wheat willow window winter wolf yarn zebra
""".split())


def now() -> float:
    return time.time()


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def gated(path: str) -> bool:
    """Every API path but the exempt ones. Static files and the manifest are outside /api: browsers fetch the manifest
    without cookies, and it names only the assistant."""
    return path.startswith("/api/") and path != EXEMPT[0] and not path.startswith(EXEMPT[1])


# ── on or off ──
def forced_choice(value: str) -> bool | None:
    """What an ODIE_PAIRING value decides, if anything. The odie command reads it the same way.
    Examples: "on" → True; "OFF" → False; "" or "maybe" → None (the saved choice decides)."""
    value = value.strip().lower()
    if value in ("on", "1", "true", "yes"):
        return True
    if value in ("off", "0", "false", "no"):
        return False
    return None


def pairing_on(store) -> bool:
    """ODIE_PAIRING=on|off wins (tests and test copies). Otherwise the saved choice, decided the first time it's asked:
    on for a new install, off for one that already chats, so nobody is locked out the day this ships."""
    forced = forced_choice(os.environ.get("ODIE_PAIRING", ""))
    if forced is not None:
        return forced
    saved = store.get_setting(_PAIRING)
    if saved is None:
        saved = {"on": not store.has_chats()}
        store.set_setting(_PAIRING, saved)
    return bool(saved.get("on"))


def set_pairing(store, on: bool) -> None:
    store.set_setting(_PAIRING, {"on": bool(on)})


# ── devices ──
def _any_device(store) -> bool:
    return store.one("select 1 from devices limit 1") is not None


def name_from(user_agent: str | None) -> str:
    """A name for a browser that didn't give one: "iPhone, Safari", "Mac, Chrome"."""
    ua = user_agent or ""
    kind = next((name for needle, name in (("iPhone", "iPhone"), ("iPad", "iPad"), ("Android", "Android"), ("Macintosh", "Mac"),
                                           ("Windows", "Windows PC"), ("CrOS", "Chromebook"), ("Linux", "Linux")) if needle in ua), "")
    app = next((name for needle, name in (("Edg/", "Edge"), ("Firefox/", "Firefox"), ("FxiOS", "Firefox"), ("CriOS", "Chrome"),
                                          ("Chrome/", "Chrome"), ("Safari/", "Safari")) if needle in ua), "")
    return ", ".join(p for p in (kind, app) if p) or "A browser"


def _clean_name(name: str | None) -> str:
    return " ".join((name or "").split())[:40] or "A browser"


def add_device(store, name: str) -> str:
    """Pairs a new device and returns its key (for its cookie; it is shown to nobody). Pairing a device ends the setup
    link."""
    key = secrets.token_urlsafe(32)
    t = now()
    store.execute("insert into devices(name,key_hash,created_at,last_seen_at) values(?,?,?,?)", (_clean_name(name), _sha(key), t, t))
    store.execute("delete from pair_codes where kind='setup'")
    setup_file().unlink(missing_ok=True)
    return key


def device_for(store, key: str | None) -> dict | None:
    """The device holding this key, or None. The lookup is by the sha256 of a 256-bit random key, so its timing tells a
    guesser nothing."""
    if not key:
        return None
    row = store.one("select id, name, created_at, last_seen_at from devices where key_hash=?", (_sha(key),))
    if row is None:
        return None
    d = dict(row)
    if now() - d["last_seen_at"] > 60:
        store.execute("update devices set last_seen_at=? where id=?", (now(), d["id"]))
    return d


def list_devices(store) -> list[dict]:
    return [dict(r) for r in store.query("select id, name, created_at, last_seen_at from devices order by created_at, id")]


def remove_device(store, device_id: int) -> bool:
    """Its key stops working, and its push subscriptions go with it."""
    store.execute("delete from push_subscriptions where device_id=?", (device_id,))
    return store.execute("delete from devices where id=?", (device_id,)).rowcount == 1


# ── one-time codes ──
def new_code(store) -> str:
    """Eight characters, shown as ABCD-EFGH: good once, for 10 minutes."""
    raw = "".join(secrets.choice(_ALPHABET) for _ in range(8))
    store.execute("delete from pair_codes where kind='code' and expires_at < ?", (now(),))
    store.execute("insert into pair_codes(code_hash,kind,expires_at) values(?,?,?)", (_sha(raw), "code", now() + CODE_TTL))
    return f"{raw[:4]}-{raw[4:]}"


def redeem_code(store, code: str | None) -> bool:
    raw = re.sub(r"[^A-Z0-9]", "", (code or "").upper())
    if len(raw) != 8:
        return False
    return store.execute("delete from pair_codes where code_hash=? and kind='code' and expires_at >= ?", (_sha(raw), now())).rowcount == 1


# ── the recovery passcode ──
def _words(text: str | None) -> str:
    return " ".join(re.findall(r"[a-z]+", (text or "").lower()))


def _scrypt(text: str | None, salt: bytes) -> bytes:
    return hashlib.scrypt(_words(text)[:200].encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)


def new_passcode(store) -> str:
    """Four random words, shown once. A new one replaces the old."""
    words = " ".join(secrets.choice(WORDS) for _ in range(4))
    salt = secrets.token_bytes(16)
    store.set_setting(_PASSCODE, {"salt": salt.hex(), "hash": _scrypt(words, salt).hex()})
    store.set_setting(_TRIES, {"fails": 0, "locked_until": 0})
    return words


def try_passcode(store, passcode: str | None) -> bool | None:
    """True when it matches; False when it doesn't; None while locked (five wrong tries lock it for 10 minutes)."""
    tries = store.get_setting(_TRIES) or {"fails": 0, "locked_until": 0}
    if tries.get("locked_until", 0) > now():
        return None
    saved = store.get_setting(_PASSCODE)
    if saved and hmac.compare_digest(_scrypt(passcode, bytes.fromhex(saved["salt"])), bytes.fromhex(saved["hash"])):
        store.set_setting(_TRIES, {"fails": 0, "locked_until": 0})
        return True
    fails = tries.get("fails", 0) + 1
    store.set_setting(_TRIES, {"fails": 0, "locked_until": now() + LOCK_FOR} if fails >= LOCK_AFTER else {"fails": fails, "locked_until": 0})
    return False


def has_passcode(store) -> bool:
    return store.get_setting(_PASSCODE) is not None


# ── the setup link (the first device) ──
def setup_link(store, base_url: str) -> str | None:
    """A new one-time link that pairs the browser opening it, while nothing is paired (it replaces any earlier one)."""
    if _any_device(store):
        return None
    token = secrets.token_urlsafe(32)
    store.execute("delete from pair_codes where kind='setup'")
    store.execute("insert into pair_codes(code_hash,kind,expires_at) values(?,?,null)", (_sha(token), "setup"))
    return f"{base_url.rstrip('/')}/api/pair/setup?token={token}"


def redeem_setup(store, token: str | None) -> bool:
    if not token or _any_device(store):
        return False
    return store.execute("delete from pair_codes where code_hash=? and kind='setup'", (_sha(token),)).rowcount == 1


def setup_file() -> Path:
    from odie import config
    return config.settings.config_dir / "setup-link"


def offer_setup(store) -> Path | None:
    """While pairing is on and nothing is paired: a fresh setup link in <config>/setup-link, readable only by the owner,
    for the installer to open. Otherwise no file."""
    from odie import config
    path = setup_file()
    if not pairing_on(store) or _any_device(store):
        path.unlink(missing_ok=True)
        return None
    link = setup_link(store, f"http://localhost:{config.settings.port}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(f"{link}\n")
    path.chmod(0o600)  # a file left from before keeps its old mode through O_TRUNC
    return path


# ── keeping the setup token out of the server log ──
def without_pairing_query(text: str) -> str:
    """A request path as the access log may show it: a pairing path keeps its path but not its query, which is where
    the setup link carries its token.
    Examples: "/api/pair/setup?token=abc" → "/api/pair/setup?[hidden]"; "/api/pair/status" → unchanged;
    "/api/chat?x=1" → unchanged."""
    path, question_mark, _query = text.partition("?")
    if question_mark and path.startswith(EXEMPT[1]):
        return f"{path}?[hidden]"
    return text


class HidePairingQueries(logging.Filter):
    """Goes on uvicorn's access logger. Its records carry the request path as one of their arguments:
    ('127.0.0.1:50000', 'GET', '/api/pair/setup?token=abc', '1.1', 303) → the same with '/api/pair/setup?[hidden]'."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not isinstance(record.args, tuple):
            return True
        cleaned = []
        for value in record.args:
            if isinstance(value, str):
                value = without_pairing_query(value)
            cleaned.append(value)
        record.args = tuple(cleaned)
        return True  # the line is still logged, just without the secret


ACCESS_LOG_FILTER = HidePairingQueries()  # one instance, so adding it again (every create_app) doesn't stack copies


def hide_pairing_queries_in_access_log() -> None:
    logging.getLogger("uvicorn.access").addFilter(ACCESS_LOG_FILTER)
