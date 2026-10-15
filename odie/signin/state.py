"""The switch (spec Part 0): off by default; on only when the user ticks "I accept the risk" on the current disclaimer.
Turning it off empties the signed-in list (the caller clears the browser's cookies and storage)."""
from __future__ import annotations

from datetime import datetime

KEY = "browser.signin"
UPI_KEY = "payments.upi_id"  # for UPI collect requests (spec Part 4): a payment setting, not a secret, never a memory
VERSION = 1
DISCLAIMER = """**Signed-in browsing (experimental).** When it's on, you can sign in to sites in Odie's browser, and Odie can use them for you: your orders, bookings, saved addresses and the last digits of saved cards become visible to the model while it works.

- **What can go wrong:** pages written by strangers (sellers, reviews, ads) can try to trick an AI into leaking what it sees or doing something you didn't ask. Odie asks before contacting any other site and before buying, paying, booking or sending, but no safeguard is perfect. Smaller local models are easier to trick.
- **Where your data goes:** if your model runs in the cloud, what it reads is sent to that provider.
- **What Odie never does:** type your passwords, card numbers, CVVs, UPI PINs or OTPs (you do). It never saves memories from signed-in pages, or from card, UPI or bank details.
- **We suggest:** a local model, and a separate chat thread for signed-in tasks.

**I understand and accept these risks.** Odie and its authors aren't responsible for any loss or security problem arising from this convenience feature."""


def get(store) -> dict:
    """On only under the terms accepted now: when the disclaimer changes, it's off until the user accepts it again."""
    s = store.get_setting(KEY) or {}
    changed = bool(s.get("on")) and s.get("accepted_version") != VERSION
    return {"on": bool(s.get("on")) and not changed, "accepted_at": s.get("accepted_at"), "accepted_version": s.get("accepted_version"),
            "terms_changed": changed}


def is_on(store) -> bool:
    return get(store)["on"]


def turn_on(store, accepted: bool, version: int, now: datetime) -> dict:
    if not accepted:
        raise ValueError("Tick \"I understand and accept these risks\" first.")
    if version != VERSION:
        raise ValueError("The terms changed since you read them: read them again.")
    s = {"on": True, "accepted_at": now.isoformat(timespec="seconds"), "accepted_version": VERSION}
    store.set_setting(KEY, s)
    store.audit("user", "signin_turned_on", result_summary=f"accepted the risks (terms v{VERSION})")
    return get(store)


def turn_off(store) -> dict:
    from odie.signin import sites
    from odie.signin import guard
    store.set_setting(KEY, {"on": False})
    store.set_setting(sites.KEY, {})
    guard.forget_all(store)
    from odie.signin import box, vault
    vault.forget_all(store)  # off means nothing survives: a saved login would make a new session
    box.for_store(store).forget()
    from odie.trackers import signed_in as tracked
    tracked.revoke(store, None, "Signed-in browsing is off.")  # a tracker never signs in with it off
    store.audit("user", "signin_turned_off", result_summary="signed out of everything")
    return get(store)


def upi_id(store) -> str | None:
    return store.get_setting(UPI_KEY) or None


def set_upi_id(store, value: str) -> str | None:
    """Save the UPI ID for collect requests ("" clears it)."""
    from odie.signin.money import UPI_ID
    v = (value or "").strip()
    if v and not UPI_ID.fullmatch(v):
        raise ValueError("That isn't a UPI ID: it looks like name@bank, for example asha@okaxis.")
    store.set_setting(UPI_KEY, v or None)
    store.audit("user", "upi_id_set" if v else "upi_id_cleared")
    return upi_id(store)
