"""Saved cards (Settings → Vault → Cards): the number, expiry and name on the card, in the login keychain of the Mac
that runs Odie, as a generic password (service "Odie card", account: the card's id, base64 JSON), never read by the AI.
The engine types a card into a payment page only when the user picks it in the live view (odie.signin.live); the user
types the CVV and the bank's OTP. The list Settings shows lives in the store (wallet.cards: {id: {label, brand, last4,
expiry, saved_at, last_used}}), without the number or the name. Tests point ODIE_KEYCHAIN at a throwaway keychain."""
from __future__ import annotations

import base64
import binascii
import json
import re
import secrets
from datetime import datetime

from odie.signin import money
from odie.signin.vault import COMMENT, CREATOR, UNREADABLE, VaultError, _keychain, _q, _security

KEY = "wallet.cards"
SERVICE = "Odie card"
ID = re.compile(r"[0-9a-f]{8}")
BAD_NUMBER = "That card number doesn't look right."
BAD_EXPIRY = "Type the expiry as MM/YY, for example 03/29."


def _all(store) -> dict:
    return dict(store.get_setting(KEY) or {})


def brand(number: str) -> str:
    """The card's network from its first digits. Example: "4242…" -> "Visa"; "5555…" or "2221…" -> "Mastercard";
    "3782…" -> "Amex"; "6521…", "60…" or "508…" -> "RuPay"; anything else -> "Card"."""
    if number.startswith("4"):
        return "Visa"
    if re.match(r"5[1-5]|2[2-7]", number):
        return "Mastercard"
    if re.match(r"3[47]", number):
        return "Amex"
    if re.match(r"60|65|81|82|508|353|356", number):
        return "RuPay"
    return "Card"


def _number(text: str) -> str:
    """The card number as digits only; ValueError when it isn't one (13 to 19 digits passing the Luhn check).
    Example: "4242 4242 4242 4242" -> "4242424242424242"; "4242 4242 4242 4241" -> ValueError."""
    digits = re.sub(r"[\s-]", "", text or "")
    if not digits.isdigit() or not 13 <= len(digits) <= 19 or not money._luhn(digits):
        raise ValueError(BAD_NUMBER)
    return digits


def _expiry(text: str) -> tuple[int, int]:
    """(month, four-digit year) from MM/YY or MM/YYYY; ValueError otherwise. Example: "03/29" -> (3, 2029);
    "1/2030" -> (1, 2030); "13/29" -> ValueError."""
    m = re.fullmatch(r"\s*(\d{1,2})\s*/\s*(\d{2}|\d{4})\s*", text or "")
    if not m or not 1 <= int(m.group(1)) <= 12:
        raise ValueError(BAD_EXPIRY)
    year = int(m.group(2))
    if year < 100:
        year += 2000
    return int(m.group(1)), year


def _read(card_id: str) -> str | None:
    r = _security(["find-generic-password", "-s", SERVICE, "-a", card_id, "-w", *_keychain()])
    return r.stdout.rstrip("\n") if r.returncode == 0 else None


def _remove(card_id: str) -> None:
    _security(["delete-generic-password", "-s", SERVICE, "-a", card_id, *_keychain()])


def listing(store) -> list[dict]:
    return sorted(({"id": k, **v} for k, v in _all(store).items()), key=lambda x: x["saved_at"])


def save(store, number: str, expiry: str, name: str, label: str, now: datetime) -> dict:
    """Save a card in the keychain and list it; returns its listing. ValueError for a wrong number or expiry."""
    digits = _number(number)
    month, year = _expiry(expiry)
    name = " ".join((name or "").split())[:80]
    if any(ord(c) < 32 or ord(c) == 127 for c in name + (label or "")):
        raise ValueError("A name can't hold control characters.")
    card_id = secrets.token_hex(4)
    secret = json.dumps({"number": digits, "month": month, "year": year, "name": name})
    stored = "b64:" + base64.b64encode(secret.encode()).decode()
    cmd = (f"add-generic-password -a {_q(card_id)} -s {_q(SERVICE)} -l {_q('Odie: card ' + digits[-4:])} -j {_q(COMMENT)} "
           f"-c {CREATOR} -T /usr/bin/security -w {_q(stored)}" + "".join(" " + _q(k) for k in _keychain()) + "\n")
    _security(["-i"], stdin=cmd)  # on standard input: the number never shows in a process list
    if _read(card_id) != stored:
        raise VaultError("Odie couldn't save it in the Mac's Keychain.")
    kind = brand(digits)
    own_label = " ".join((label or "").split())[:40]
    entry = {"label": own_label or f"{kind} •••• {digits[-4:]}", "brand": kind, "last4": digits[-4:],
             "expiry": f"{month:02d}/{year % 100:02d}", "saved_at": now.isoformat(timespec="seconds"), "last_used": None}
    got = _all(store)
    got[card_id] = entry
    store.set_setting(KEY, got)
    store.audit("user", "card_saved", result_summary=entry["label"])
    return {"id": card_id, **entry}


def get(store, card_id: str) -> dict | None:
    """The whole card ({number, month, year, name}) for the engine to type, or None when there's no such card."""
    if card_id not in _all(store):
        return None
    raw = _read(card_id)
    if raw is None or not raw.startswith("b64:"):
        raise VaultError(UNREADABLE)  # a locked keychain answers like a missing item: never forget it here
    try:
        return json.loads(base64.b64decode(raw[4:]).decode())
    except (binascii.Error, UnicodeDecodeError, ValueError) as e:
        raise VaultError(UNREADABLE) from e


def used(store, card_id: str, site: str, now: datetime) -> None:
    got = _all(store)
    if card_id in got:
        got[card_id]["last_used"] = now.isoformat(timespec="seconds")
        store.set_setting(KEY, got)
        store.audit("user", "card_filled", result_summary=f"{got[card_id]['label']} on {site}")


def delete(store, card_id: str) -> bool:
    got = _all(store)
    entry = got.pop(card_id, None)
    if entry is None:
        return False
    _remove(card_id)
    store.set_setting(KEY, got)
    store.audit("user", "card_deleted", result_summary=entry["label"])
    return True
