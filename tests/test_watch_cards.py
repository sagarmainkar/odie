"""How a watch item reads on its Today card: icons the app has, amounts and dates as people write them."""
import json
from pathlib import Path

from odie.watch import cards

CATALOG = json.loads(Path("odie/blocks/catalog.json").read_text())
ICONS = set(CATALOG["icons"])


def test_icons_are_the_apps_own():
    for pile, icon in cards.PILE_ICON.items():
        assert icon in ICONS, pile


def test_an_amount_or_a_date_ends_the_card():
    assert cards.when_or_amount({"amount": {"value": 12400, "currency": "INR"}, "due": "2026-10-24"}) == "₹12,400"
    assert cards.when_or_amount({"due": "2026-10-24"}) == "24 Oct"
    assert cards.when_or_amount({"due": "2026-10-24T18:00+05:30"}) == "24 Oct, 18:00"
    assert cards.when_or_amount({}) == ""
    assert cards.money({"value": 58.25, "currency": "USD"}) == "$58.25"


def test_an_item_without_a_suggestion_asks_about_itself():
    assert cards.ask_about({"ref": "mail:p1"}) == "Tell me about watch item mail:p1"
