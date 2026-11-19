"""The last narrow check of the upgrade (19 Nov 2026): an open card item never loses its card by joining another open
thing on the same mail; a card he dismissed under the older Odie stays finished after a rollback and a second upgrade;
an odd watch.card never stops the upgrade."""
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from odie.loops import ledger, migrate
from odie.store.db import Store
from odie.watch import needs
from tests.test_phase3_data_safety import loops, task

TZ = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 11, 19, 12, 0, tzinfo=TZ)


@pytest.fixture
def store(isolated_settings, tmp_path):
    s = Store(tmp_path / "a.db")
    s.init_schema()
    return s


def titles(store, now=NOW):
    return [c["title"] for c in needs.cards(store, now)]


def item(ref, title, pile="alerts"):
    return {"ref": ref, "title": title, "why": "", "done": False, "pile": pile,
            "at": (NOW - timedelta(days=1)).isoformat()}


def test_two_different_open_things_on_one_mail_both_stay_cards(store):
    kept = json.dumps({"thread": "tS", "kind": "bill"})
    task(store, "Pay term fee Rs 12,000", "mail:school1", source_kind="watch", notes=kept, created=2,
         due="2026-11-30T09:00+05:30")
    store.set_setting("watch.card", {"needs_you": [item("mail:school1", "PTM on Saturday")]})
    migrate.run(store, NOW)
    assert "PTM on Saturday" in titles(store) and "Pay term fee Rs 12,000" in titles(store)


def test_an_open_item_on_the_mail_of_an_order_odie_follows_stays_a_card(store):
    kept = json.dumps({"thread": "tO", "kind": "order", "due": "2026-11-22T09:00+05:30"})
    task(store, "Order: desk lamp", "mail:o1", source_kind="watch", kind="waiting", notes=kept, created=3)
    store.set_setting("watch.card", {"needs_you": [item("mail:o1", "Delivery failed: pick a new slot", "orders")]})
    migrate.run(store, NOW)
    assert "Delivery failed: pick a new slot" in titles(store)


def test_the_same_open_thing_worded_a_little_differently_is_still_one_card(store):
    kept = json.dumps({"thread": "tB", "kind": "bill"})
    task(store, "Pay Cloudbase invoice #A-11 — $58.58", "mail:b1", source_kind="watch", notes=kept, created=2,
         due="2026-11-19T09:00+05:30")
    store.set_setting("watch.card", {"needs_you": [item("mail:b1", "Cloudbase invoice #A-11 — $58.58", "bills")]})
    migrate.run(store, NOW)
    assert len(titles(store)) == 1 and len(loops(store)) == 1


def test_a_card_he_dismissed_under_the_older_odie_stays_finished_after_a_second_upgrade(store):
    store.set_setting("watch.card", {"needs_you": [item("mail:r1", "Reply to Asha", "personal")]})
    migrate.run(store, NOW)
    migrate.before_rollback(store, NOW + timedelta(hours=1))
    card = store.get_setting("watch.card")  # the older Odie's Done takes the item out of the list
    card["needs_you"] = [i for i in card["needs_you"] if i.get("ref") != "mail:r1"]
    store.set_setting("watch.card", card)
    migrate.run(store, NOW + timedelta(hours=2))
    asha = [lp for lp in loops(store) if lp["title"] == "Reply to Asha"]
    assert asha and all(lp["state"] not in ledger.OPEN for lp in asha)
    assert "Reply to Asha" not in titles(store, NOW + timedelta(hours=2))


@pytest.mark.parametrize("card", [["x"], "text", 7, {"needs_you": "text"}, {"needs_you": {"a": 1}},
                                  {"needs_you": ["text", 3, None, {"title": "no ref"}]}])
def test_an_odd_watch_card_never_stops_the_upgrade(store, card):
    task(store, "Pay rent", "mail:rent", due="2026-11-25T09:00+05:30")
    store.set_setting("watch.card", card)
    migrate.run(store, NOW)
    migrate.before_rollback(store, NOW + timedelta(hours=1))
    migrate.run(store, NOW + timedelta(hours=2))
    assert [lp["title"] for lp in loops(store) if lp["state"] in ledger.OPEN] == ["Pay rent"]
