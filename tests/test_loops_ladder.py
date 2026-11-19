"""The follow-up ladder (proactive design §8), on the 5-minute tick, by the clock alone (no model): his move — a push
the day before it's due, a line in the morning hello from day 2, Sunday's "Still care?" from day 7 (odie.loops.cards),
dropped on day 14 (kept, never pushed); their move — after 3 quiet days, one nudge card."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from odie.loops import ladder, ledger
from odie.store.db import Store

TZ = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 11, 19, 10, 0, tzinfo=TZ)


@pytest.fixture
def store(isolated_settings, tmp_path):
    s = Store(tmp_path / "a.db")
    s.init_schema()
    return s


def pushes():
    sent = []

    def push_for(pid):
        def push(title, body):
            sent.append((pid, title, body))
        return push
    push_for.sent = sent
    return push_for


def test_a_push_the_day_before_its_due_once(store):
    lid = ledger.open_loop(store, "", NOW - timedelta(days=1), "Send Asha the deck", "reply owed", owner="you",
                           state="ready", due_at=(NOW + timedelta(hours=20)).isoformat(timespec="minutes"))
    far = ledger.open_loop(store, "", NOW, "Pay rent", "bill", owner="you", state="ready",
                           due_at=(NOW + timedelta(days=5)).isoformat(timespec="minutes"))
    push_for = pushes()
    assert (lid, "due tomorrow") in ladder.run(store, NOW, push_for)
    assert push_for.sent == [("", "Send Asha the deck", "Due tomorrow")]
    ladder.run(store, NOW + timedelta(minutes=5), push_for)
    assert len(push_for.sent) == 1  # once
    assert not [s for s in push_for.sent if s[1] == "Pay rent"] and ledger.get(store, far)["state"] == "ready"


def test_no_push_at_night_it_waits_for_the_morning(store):
    night = datetime(2026, 11, 19, 23, 0, tzinfo=TZ)
    ledger.open_loop(store, "", night, "Send the deck", "reply owed", owner="you", state="ready",
                     due_at="2026-11-20T15:00+05:30")
    push_for = pushes()
    ladder.run(store, night, push_for)
    assert push_for.sent == []
    ladder.run(store, datetime(2026, 11, 20, 7, 5, tzinfo=TZ), push_for)
    assert len(push_for.sent) == 1


def test_the_day_before_push_counts_in_the_shared_budget(store):
    from odie.watch import pushes as push_budget
    for _ in range(push_budget.DAILY):
        assert push_budget.spend(store, NOW)
    lid = ledger.open_loop(store, "", NOW, "Send the deck", "reply owed", owner="you", state="ready",
                           due_at=(NOW + timedelta(hours=10)).isoformat(timespec="minutes"))
    push_for = pushes()
    ladder.run(store, NOW, push_for)
    assert push_for.sent == [] and store.get_setting(push_budget.HELD)[-1]["ref"] == f"loop:{lid}"
    ladder.run(store, NOW + timedelta(minutes=5), push_for)
    assert len(store.get_setting(push_budget.HELD)) == 1  # held once, not every tick


def test_their_move_gets_one_nudge_card_after_three_quiet_days(store):
    lid = ledger.open_loop(store, "", NOW - timedelta(days=4), "Waiting on Asha's answer", "waiting on them",
                           owner="them", state="waiting", fact="You asked Asha for the venue")
    store.execute("update loop_events set at=? where loop_id=?", ((NOW - timedelta(days=4)).isoformat(), lid))
    recent = ledger.open_loop(store, "", NOW - timedelta(days=1), "Waiting on Priya", "waiting on them", owner="them",
                              state="waiting", fact="asked")
    ladder.run(store, NOW, pushes())
    loop = ledger.get(store, lid)
    assert loop["state"] == "ready" and loop["nudges"] == 1 and loop["card"]["suggestion"] == "Draft a nudge"
    assert "No word in 4 days" in loop["result"]
    assert ledger.get(store, recent)["state"] == "waiting"
    ledger.update(store, lid, NOW, state="waiting")  # say he put it back to waiting: it never nudges twice
    ladder.run(store, NOW + timedelta(days=5), pushes())
    assert ledger.get(store, lid)["nudges"] == 1


def test_an_order_on_its_way_isnt_nudged_before_its_expected_day(store):
    lid = ledger.open_loop(store, "", NOW - timedelta(days=5), "Order: lamp", "order", owner="them", state="waiting",
                           due_at=(NOW + timedelta(days=2)).isoformat(timespec="minutes"), fact="shipped")
    store.execute("update loop_events set at=? where loop_id=?", ((NOW - timedelta(days=5)).isoformat(), lid))
    ladder.run(store, NOW, pushes())
    assert ledger.get(store, lid)["state"] == "waiting"
    ladder.run(store, NOW + timedelta(days=6), pushes())  # 4 quiet days after it was expected
    assert ledger.get(store, lid)["state"] == "ready"


def test_his_card_untouched_for_fourteen_days_is_dropped_and_kept(store):
    old = ledger.open_loop(store, "", NOW - timedelta(days=15), "Reply to a recruiter", "reply owed", owner="you",
                           state="ready")
    dated = ledger.open_loop(store, "", NOW - timedelta(days=15), "Renew passport", "deadline", owner="you",
                             state="ready", due_at=(NOW + timedelta(days=20)).isoformat(timespec="minutes"))
    push_for = pushes()
    assert (old, "dropped") in ladder.run(store, NOW, push_for)
    loop = ledger.get(store, old)
    assert loop["state"] == "dropped" and loop["closed_by"] == "odie" and "14 days" in loop["closed_why"]
    assert ledger.get(store, dated)["state"] == "ready"  # still before its date
    assert push_for.sent == []


def test_the_hello_gets_a_line_for_what_waits_on_him_since_day_two(store):
    ledger.open_loop(store, "", NOW - timedelta(days=3), "Reply to Asha", "reply owed", owner="you", state="ready")
    ledger.open_loop(store, "", NOW - timedelta(hours=5), "Fresh one", "reply owed", owner="you", state="ready")
    lines = ladder.hello_lines(store, "", NOW)
    assert lines == ["Reply to Asha (waiting on you 3 days)"]
