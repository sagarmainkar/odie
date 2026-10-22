"""The Desk's cards (22 Oct 2026): what the watch found, drawn by code as the chat's own blocks, so the user reads a
card with buttons instead of a paragraph. Each item is one card: its title, one line of why with its date or amount,
and its two buttons (the suggestion and the escape), whose taps send chat requests that name the item ("desk item
mail:<id>") so chat can act on it. A drafted reply never goes into a card: chat shows it when asked."""
from __future__ import annotations

import json
from datetime import datetime

PILE_ICON = {"alerts": "alert", "bills": "rupee", "events": "cal", "personal": "heart", "orders": "ticket"}
DEFAULT_ICON = "mail"
MAX_CARDS = 6  # cards in one post; more items follow as compact rows
DONE_TITLE = "Done while you were away"
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
    """The value at the end of a row: the amount when there is one, else the due day, else ""."""
    if item.get("amount"):
        return money(item["amount"])
    if item.get("due"):
        return day(item["due"])
    return ""


def ask_about(item: dict) -> str:
    """The chat request for an item without a suggestion: "Tell me about desk item mail:p1"."""
    return f"Tell me about desk item {item['ref']}"


def item_card(item: dict) -> dict:
    """One item as a card: a section titled with the item, a line of why with its icon and its date or amount as a
    pill, then its buttons. With a suggestion and an escape -> two buttons; with neither -> one "Tell me more" button
    that asks about the item."""
    icon = PILE_ICON.get(item.get("pile", ""), DEFAULT_ICON)
    line = f":icon[{icon}] {item.get('why', '')}".strip()
    extra = when_or_amount(item)
    if extra:
        line += f" :badge[{extra}]"
    children: list[dict] = [{"type": "text", "text": line}]
    for key in ("suggestion", "escape"):
        action = item.get(key)
        if action:
            children.append({"type": "button", "label": action["label"], "run": action["run"]})
    if len(children) == 1:
        children.append({"type": "button", "label": "Tell me more", "run": ask_about(item)})
    return {"type": "section", "title": item.get("title") or "Needs you", "children": children}


def item_row(item: dict) -> dict:
    """One item as a compact row (after the first cards): title, why, date or amount, icon; its tap runs the
    suggestion, or asks about the item."""
    suggestion = item.get("suggestion") or {}
    return {"title": item.get("title", ""), "subtitle": item.get("why", ""), "value": when_or_amount(item),
            "icon": PILE_ICON.get(item.get("pile", ""), DEFAULT_ICON), "run": suggestion.get("run") or ask_about(item)}


def round_text(opener: str, items: list[dict], done: list[str]) -> str:
    """A Desk post: the opener (a sentence or two, or ""), then one blocks fence: a card for each of the first
    MAX_CARDS items, the rest as rows, and the "Done while you were away" lines as a list. No items and nothing done ->
    "" (nothing to post)."""
    if not items and not done:
        return ""
    blocks: list[dict] = [item_card(item) for item in items[:MAX_CARDS]]
    rest = items[MAX_CARDS:]
    if rest:
        blocks.append({"type": "list", "title": f"{len(rest)} more", "items": [item_row(i) for i in rest]})
    if done:
        rows = [{"title": line, "icon": "check"} for line in done]
        blocks.append({"type": "list", "title": DONE_TITLE, "items": rows})
    fence = "```odie-blocks\n" + json.dumps(blocks, ensure_ascii=False) + "\n```"
    if opener.strip():
        return f"{opener.strip()}\n\n{fence}"
    return fence
