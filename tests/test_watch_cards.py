"""The Desk's cards: what the watch found, drawn by code as chat blocks (never the model's paragraphs)."""
import json
import re
from pathlib import Path

from odie.watch import cards

CATALOG = json.loads(Path("odie/blocks/catalog.json").read_text())
ICONS = set(CATALOG["icons"])
KINDS = {b["kind"] for b in CATALOG["blocks"]}
INVITE = {"ref": "mail:m1", "title": "Workshop invite", "why": "Asks your fee and a date by Friday", "pile": "alerts",
          "suggestion": {"label": "Reply with your fee", "run": "Show the draft for desk item mail:m1"},
          "escape": {"label": "Not interested", "run": "Close desk item mail:m1: not interested"}, "due": "2026-10-24",
          "draft": {"to": "a@example.com", "subject": "Re: Workshop", "body": "SECRET-DRAFT-BODY"}}
BILL = {"ref": "mail:b1", "title": "Card bill", "why": "Statement ready", "pile": "bills",
        "amount": {"value": 12400, "currency": "INR"}}


def blocks_of(text: str) -> list[dict]:
    fence = re.search(r"```odie-blocks\n(.*?)\n```", text, re.DOTALL)
    assert fence, text
    return json.loads(fence.group(1))


def kinds_in(blocks):
    for b in blocks:
        yield b["type"]
        yield from kinds_in(b.get("children", []))


def test_a_round_has_the_opener_then_one_card_per_item():
    text = cards.round_text("Good morning: two things need you.", [INVITE, BILL], ["✓ Delivered · Desk lamp"])
    assert text.startswith("Good morning: two things need you.")
    blocks = blocks_of(text)
    assert set(kinds_in(blocks)) <= KINDS
    first = blocks[0]
    assert first["type"] == "section" and first["title"] == "Workshop invite"
    buttons = [c for c in first["children"] if c["type"] == "button"]
    assert [b["label"] for b in buttons] == ["Reply with your fee", "Not interested"]
    assert buttons[0]["run"] == "Show the draft for desk item mail:m1"
    assert "24 Oct" in first["children"][0]["text"]
    assert "₹12,400" in blocks[1]["children"][0]["text"]
    done = blocks[-1]
    assert done["type"] == "list" and done["title"] == "Done while you were away"


def test_icons_are_the_apps_own():
    for pile, icon in cards.PILE_ICON.items():
        assert icon in ICONS, pile


def test_a_draft_never_goes_in_a_card():
    assert "SECRET-DRAFT-BODY" not in cards.round_text("", [INVITE], [])


def test_an_item_without_buttons_still_asks_about_itself():
    plain = {"ref": "mail:p1", "title": "Something", "why": "A thing"}
    card = cards.item_card(plain)
    buttons = [c for c in card["children"] if c["type"] == "button"]
    assert [b["run"] for b in buttons] == ["Tell me about desk item mail:p1"]


def test_many_items_become_rows_after_the_first_cards():
    many = [{**INVITE, "ref": f"mail:m{i}", "title": f"Item {i}"} for i in range(9)]
    blocks = blocks_of(cards.round_text("", many, []))
    assert sum(1 for b in blocks if b["type"] == "section") == cards.MAX_CARDS
    more = blocks[cards.MAX_CARDS]
    assert more["type"] == "list" and len(more["items"]) == 9 - cards.MAX_CARDS


def test_nothing_to_show_is_no_text():
    assert cards.round_text("", [], []) == ""
