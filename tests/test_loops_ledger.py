"""The ledger (proactive design §5): one loop per real thing, its evidence kept, closed only with a reason."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from odie import personalities
from odie.loops import ledger
from odie.store.db import Store

NOW = datetime(2026, 11, 18, 10, 0, tzinfo=ZoneInfo("Asia/Kolkata"))


@pytest.fixture
def store(isolated_settings, tmp_path):
    s = Store(tmp_path / "a.db")
    s.init_schema()
    return s


def test_a_loop_opens_with_its_evidence_and_is_due_at_once(store):
    lid = ledger.open_loop(store, "", NOW, "app #49 Threads newest first", "pull request", refs=["example/app#49"],
                           playbook="github-pr", next_step="get the facts", source="mail", ref="mail:m1",
                           fact="Review requested")
    loop = ledger.get(store, lid)
    assert loop["state"] == "new" and loop["owner"] == "odie" and loop["refs"] == ["example/app#49"]
    assert loop["next_check_at"] == NOW.isoformat(timespec="seconds") and loop["personality"] == ""
    assert [e["fact"] for e in ledger.events(store, lid)] == ["Review requested"]


def test_attach_adds_evidence_and_news_and_the_ref(store):
    lid = ledger.open_loop(store, "", NOW, "app #49", "pull request", refs=["example/app#49"])
    ledger.update(store, lid, NOW, has_news=0)
    ledger.attach(store, lid, NOW, "mail", "mail:m2", "New commits pushed", refs=["thread:t9"])
    loop = ledger.get(store, lid)
    assert loop["has_news"] == 1 and loop["refs"] == ["example/app#49", "thread:t9"]
    assert ledger.find_by_refs(store, "", ["thread:t9"])["id"] == lid
    assert ledger.find_by_refs(store, "", ["example/app#50"]) is None


def test_loops_stay_with_their_personality(store):
    mira = personalities.create(store, "Mira").id
    odies = ledger.open_loop(store, "", NOW, "Odie's", "issue", refs=["example/app#1"])
    hers = ledger.open_loop(store, mira, NOW, "Mira's", "issue", refs=["example/app#1"])
    assert [l["id"] for l in ledger.open_loops(store, "")] == [odies]
    assert [l["id"] for l in ledger.open_loops(store, mira)] == [hers]
    assert ledger.find_by_refs(store, mira, ["example/app#1"])["id"] == hers
    ledger.forget_personality(store, mira)
    assert ledger.open_loops(store, mira) == [] and ledger.get(store, hers) is None
    assert ledger.events(store, hers) == []


def test_a_close_needs_a_reason_and_shows_in_done_today_with_reopen(store):
    lid = ledger.open_loop(store, "", NOW, "app #49", "pull request", playbook="github-pr")
    with pytest.raises(ValueError):
        ledger.close(store, lid, NOW, "odie", "")
    ledger.close(store, lid, NOW, "odie", "merged 18 Nov 09:40")
    loop = ledger.get(store, lid)
    assert loop["state"] == "closed" and loop["closed_why"] == "merged 18 Nov 09:40"
    assert [l["id"] for l in ledger.closed_since(store, "", NOW - timedelta(hours=1))] == [lid]
    assert ledger.open_loops(store, "") == []
    ledger.reopen(store, lid, NOW)
    assert ledger.get(store, lid)["state"] == "new" and ledger.get(store, lid)["closed_why"] is None
    assert ledger.events(store, lid)[-1]["fact"] == "Reopened by you"


def test_done_by_the_user_is_not_listed_as_odies(store):
    lid = ledger.open_loop(store, "", NOW, "app #49", "pull request")
    ledger.done(store, lid, NOW)
    assert ledger.get(store, lid)["closed_by"] == "you"
    assert ledger.closed_since(store, "", NOW - timedelta(hours=1)) == []


def test_one_line_per_loop_for_the_model(store):
    lid = ledger.open_loop(store, "", NOW, "app #49 Threads newest first", "pull request", refs=["example/app#49"],
                           fact="Review requested")
    line = ledger.line(ledger.get(store, lid), ledger.events(store, lid))
    assert line.startswith(f"#{lid} app #49 Threads newest first · pull request · owner odie · new")
    assert "example/app#49" in line and "Review requested" in line
