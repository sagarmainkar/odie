"""How a watch item reads on its card on Today (odie.watch.needs): its icon, its date or amount, and the chat request
for asking about it ("Tell me about watch item mail:<id>"). A drafted reply never goes into a card: chat shows it when
asked (odie.agent.tools.watch_items)."""
from __future__ import annotations

from datetime import datetime

PILE_ICON = {"alerts": "alert", "bills": "rupee", "events": "cal", "personal": "heart", "orders": "ticket"}
DEFAULT_ICON = "mail"
CURRENCY_SIGN = {"INR": "₹", "USD": "$", "EUR": "€", "GBP": "£"}


def money(amount: dict) -> str:
    """An amount as people write it: {"value": 12400, "currency": "INR"} -> "₹12,400"; {"value": 58.25,
    "currency": "USD"} -> "$58.25"; an unknown currency -> "CHF 40"."""
    value = amount.get("value")
    number = f"{value:,.2f}".rstrip("0").rstrip(".") if isinstance(value, float) else f"{value:,}"
    currency = str(amount.get("currency") or "")
    sign = CURRENCY_SIGN.get(currency.upper())
    if sign:
        return f"{sign}{number}"
    return f"{currency} {number}".strip()


def day(due: str) -> str:
    """A due date as a short day: "2026-10-24" -> "24 Oct"; "2026-10-24T18:00+05:30" -> "24 Oct, 18:00"; not a date ->
    as given."""
    try:
        when = datetime.fromisoformat(due)
    except ValueError:
        return due
    short = f"{when.day} {when.strftime('%b')}"
    if "T" in due:
        short += f", {when.strftime('%H:%M')}"
    return short


def when_or_amount(item: dict) -> str:
    """The value at the end of a row: the amount when there is one, else the due day, else "". {"amount": {"value":
    12400, "currency": "INR"}, "due": "2026-10-24"} -> "₹12,400"; {"due": "2026-10-24"} -> "24 Oct"; {} -> ""."""
    if item.get("amount"):
        return money(item["amount"])
    if item.get("due"):
        return day(item["due"])
    return ""


def ask_about(item: dict) -> str:
    """The chat request for an item without a suggestion: "Tell me about watch item mail:p1"."""
    return f"Tell me about watch item {item['ref']}"
