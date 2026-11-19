"""What Odie never keeps in a loop, a "Track this?" offer or the Now list (proactive phase 4): a card, UPI or bank
detail (odie.signin.money), or anything shaped like a secret: an API key or token, or a password, PIN or code given
with its value. These are written from his words and Odie's replies, shown on Pulse and read by later model calls."""
from __future__ import annotations

import re

TOKEN = re.compile(r"\b(sk-|sk_live_|rk_live_|ghp_|gho_|ghs_|github_pat_|xox[abpr]-|AKIA|AIza|glpat-)[A-Za-z0-9_\-]{8,}")
SAID_WITH_VALUE = re.compile(r"\b(password|passcode|passwd|pin|otp|cvv|api[ _-]?key|secret|token)\b\s*(is|:|=)\s*\S+",
                             re.I)


def secret_in(text: str) -> str | None:
    """Why this text holds something never kept, or None.
      "Pay rent from account 123456789012 IFSC HDFC0001234" -> "an IFSC code";  "Rotate sk-abc…xyz" -> "a key";
      "my PIN is 4321" -> "a password or code";  "Renew the passport" -> None;  "Reset my password" -> None"""
    from odie.signin.money import holds_financial
    money = holds_financial(text or "")
    if money:
        return money
    if TOKEN.search(text or ""):
        return "a key"
    if SAID_WITH_VALUE.search(text or ""):
        return "a password or code"
    return None
