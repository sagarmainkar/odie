"""Financial details (spec Part 5): card numbers (Luhn-checked), CVVs, UPI IDs, IFSC codes and account numbers. Memory
refuses all of them; pages are masked before the model reads them (cards, accounts and CVVs; a UPI ID or IFSC stays
readable on a page, where the user may need it)."""
from __future__ import annotations

import re

_CARD = re.compile(r"(?<![\d-])(?:\d[ -]?){12,18}\d(?![\d-])")
_CVV = re.compile(r"\b(cvv|cvc|security code)\b\W{0,12}?(\d{3,4})\b", re.I)
_UPI_HANDLES = (r"ok(?:axis|hdfcbank|icici|sbi)|ybl|ibl|axl|paytm|upi|apl|ptyes|ptaxis|pthdfc|ptsbi|fbl|waaxis|wahdfcbank|"
                r"jupiteraxis|axisbank|icici|sbi|hdfcbank|kotak|yesbank|idfcbank")
_UPI = re.compile(rf"\b[a-z0-9._-]{{2,}}@(?:{_UPI_HANDLES})\b", re.I)
_UPI_WORD = re.compile(r"\bupi\b.{0,20}?\b[a-z0-9._-]{2,}@[a-z]{2,}\b|\b[a-z0-9._-]{2,}@[a-z]{2,}\b.{0,20}?\bupi\b", re.I)
_IFSC = re.compile(r"\b[A-Z]{4}0[A-Z0-9]{6}\b")
_ACCOUNT = re.compile(r"\b(a/?c|acct|account)\b(?:\s*(?:no\.?|number|#))?\W{0,6}(\d{9,18})\b", re.I)
UPI_ID = re.compile(r"[a-z0-9][a-z0-9._-]{1,255}@[a-z][a-z0-9]{1,63}", re.I)  # a whole UPI ID (VPA): name@handle


def _luhn(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        alt = not alt
    return total % 10 == 0


def _cards(text: str):
    for m in _CARD.finditer(text or ""):
        digits = re.sub(r"\D", "", m.group(0))
        if 13 <= len(digits) <= 19 and _luhn(digits):
            yield m, digits


def holds_financial(text: str) -> str | None:
    """Why this text holds a financial detail, or None."""
    t = text or ""
    if next(_cards(t), None):
        return "a card number"
    if _CVV.search(t):
        return "a CVV"
    if _UPI.search(t) or _UPI_WORD.search(t):
        return "a UPI ID"
    if _IFSC.search(t):
        return "an IFSC code"
    if _ACCOUNT.search(t):
        return "a bank account number"
    return None


def mask(text: str) -> str:
    """Card numbers as •••• 1234, account numbers as ••••6789, CVVs as •••; everything else as it was."""
    t = text or ""
    t = _ACCOUNT.sub(lambda m: m.group(0)[: m.start(2) - m.start(0)] + "••••" + m.group(2)[-4:], t)  # before cards: an
    for m, digits in reversed(list(_cards(t))):                                                   # account may pass Luhn
        t = t[:m.start()] + f"•••• {digits[-4:]}" + t[m.end():]
    t = _CVV.sub(lambda m: m.group(0)[: m.start(2) - m.start(0)] + "•••", t)
    return t
