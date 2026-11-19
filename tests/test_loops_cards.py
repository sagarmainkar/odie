"""Loop cards on Pulse (proactive design §8): the move is built by code; Later hides a card; what Odie is on and
what it closed today."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from odie.loops import cards, ledger
from odie.store.db import Store

NOW = datetime(2026, 11, 18, 10, 0, tzinfo=ZoneInfo("Asia/Kolkata"))


@pytest.fixture
def store(isolated_settings, tmp_path):
    s = Store(tmp_path / "a.db")
    s.init_schema()
    return s


def test_the_move_is_built_from_a_checked_ref():
    pr = {"id": 3, "title": "x", "kind": "pull request", "refs": ["thread:t1", "example/app#49"]}
    assert cards.move_of(pr) == {"label": "Open PR #49", "action": "open", "value": "https://github.com/example/app/pull/49"}
    issue = {**pr, "kind": "issue", "refs": ["example/app#7"]}
    assert cards.move_of(issue)["label"] == "Open issue #7"
    nothing = {**pr, "refs": ["thread:t1", "example/app#49; rm -rf ~"]}
    assert cards.move_of(nothing)["action"] == "chat"


def test_later_hides_the_card_until_tomorrow_morning(store):
    lid = ledger.open_loop(store, "", NOW, "app #49", "pull request", refs=["example/app#49"])
    ledger.update(store, lid, NOW, state="ready")
    assert [c["ref"] for c in cards.cards(store, "", NOW)] == [f"loop:{lid}"]
    assert cards.later(store, lid, (NOW + timedelta(hours=23)).isoformat(), "", NOW)
    assert cards.cards(store, "", NOW) == []
    assert [c["ref"] for c in cards.cards(store, "", NOW + timedelta(days=1))] == [f"loop:{lid}"]
    assert not cards.later(store, lid, NOW.isoformat(), "someone-else", NOW)


def test_on_it_and_done_today(store):
    waiting = ledger.open_loop(store, "", NOW, "app #51", "pull request")
    ledger.update(store, waiting, NOW, state="waiting", next_step="CI still running")
    merged = ledger.open_loop(store, "", NOW, "app #50", "pull request")
    ledger.close(store, merged, NOW - timedelta(hours=1), "odie", "merged 18 Nov 09:00")
    assert cards.on_it(store, "") == [{"id": waiting, "title": "app #51", "state": "waiting", "next": "CI still running"}]
    assert [d["id"] for d in cards.done_today(store, "", NOW)] == [merged]
    assert cards.done_today(store, "", NOW + timedelta(days=1)) == []
