"""The digests (proactive design §8, §17): the 19:30 evening digest (a push only when something needs him, within the
shared 3 a day, never 22:00-07:00) and "while you were away" on opening Pulse after 3+ hours; and the morning hello's
two ledger lines."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from odie import personalities
from odie.loops import digest, ladder, ledger, quiet
from odie.store.db import Store
from odie.watch import pushes

TZ = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 11, 19, 19, 30, tzinfo=TZ)


@pytest.fixture
def store(isolated_settings, tmp_path):
    s = Store(tmp_path / "a.db")
    s.init_schema()
    return s


def his(store, title, shown=None, due=None, pid="", kind="reply owed", card=None):
    at = shown or NOW - timedelta(hours=2)
    return ledger.open_loop(store, pid, at, title, kind, owner="you", state="ready", due_at=due, card=card)


def test_code_text_says_what_needs_him_first():
    f = {"needs": ["Reply to Asha", "Gas bill"], "new": ["Gas bill"], "odie_closed": [{"title": "Order: lamp",
         "why": "delivered"}], "you_closed": 3, "quiet": [{"id": 9, "title": "Acme weekly"}], "held": []}
    assert digest.code_text(f) == ("2 need you: Reply to Asha, Gas bill. Odie closed 1: Order: lamp. You finished 3. "
                                   "In the digest: Acme weekly.")
    assert digest.code_text(f, away=True) == "1 new for you: Gas bill. Odie closed 1: Order: lamp."
    empty = {"needs": [], "new": [], "odie_closed": [], "you_closed": 0, "quiet": [], "held": []}
    assert digest.code_text(empty) == ""


def test_checked_text_keeps_plain_words_only():
    assert digest.checked_text("Two things need you:\n the reply to Asha.") == "Two things need you: the reply to Asha."
    assert digest.checked_text("Open http://evil.example now") is None
    assert digest.checked_text("Go to www.evil.example") is None
    assert digest.checked_text("Your PIN is 4321") is None
    assert digest.checked_text("") is None and digest.checked_text(None) is None
    assert len(digest.checked_text("word " * 200)) <= digest.TEXT_MOST + 1


def test_needs_him_examples(store):
    store.set_setting("watch.card", {"seen_at": (NOW - timedelta(hours=3)).isoformat()})
    assert digest.needs_him(store, "", NOW) is False  # nothing at all
    seen_card = his(store, "Seen at noon", shown=NOW - timedelta(hours=8), due=(NOW + timedelta(days=6)).isoformat())
    assert digest.needs_him(store, "", NOW) is False
    his(store, "Due tomorrow", shown=NOW - timedelta(hours=8), due=(NOW + timedelta(hours=14)).isoformat())
    assert digest.needs_him(store, "", NOW) is True
    ledger.done(store, seen_card, NOW)


def test_an_unseen_card_needs_him(store):
    store.set_setting("watch.card", {"seen_at": (NOW - timedelta(hours=5)).isoformat()})
    his(store, "New since lunch", shown=NOW - timedelta(hours=1))
    assert digest.needs_him(store, "", NOW) is True


def test_a_digest_line_never_needs_him(store):
    store.set_setting("watch.card", {"seen_at": (NOW - timedelta(hours=5)).isoformat()})
    lid = his(store, "Acme weekly", kind="newsletter", card={"sender": "news@acme.example"})
    quiet.less_like_this(store, ledger.get(store, lid), NOW - timedelta(hours=1))
    his(store, "Acme weekly 2", kind="newsletter", card={"sender": "news@acme.example"})
    assert digest.needs_him(store, "", NOW) is False


def pusher():
    sent = []

    def push(title, body):
        sent.append((title, body))
    push.sent = sent
    return push


def test_the_evening_digest_pushes_only_when_something_needs_him(store):
    push = pusher()
    store.set_setting("watch.card", {"seen_at": NOW.isoformat()})
    quiet_day = digest.make_evening(store, "", NOW, "All calm.")
    assert digest.tell(store, "", NOW, quiet_day, push) == "quiet" and push.sent == []
    his(store, "Reply to Asha", shown=NOW + timedelta(minutes=1))
    later = NOW + timedelta(minutes=2)
    busy_day = digest.make_evening(store, "", later, "One thing needs you: the reply to Asha.")
    assert digest.tell(store, "", later, busy_day, push) == "pushed"
    assert push.sent == [("Evening digest", "One thing needs you: the reply to Asha.")]
    assert pushes.sent_today(store, later) == 1  # one of the shared three


def test_over_the_days_three_it_is_held_and_at_night_kept_for_the_morning(store):
    his(store, "Reply to Asha")
    push = pusher()
    store.set_setting(pushes.KEY, {"day": NOW.date().isoformat(), "sent": pushes.DAILY})
    d = digest.make_evening(store, "", NOW, "One thing needs you.")
    assert digest.tell(store, "", NOW, d, push) == "over budget" and push.sent == []
    night = NOW.replace(hour=22, minute=40)
    d = digest.make_evening(store, "", night, "One thing needs you.")
    assert digest.tell(store, "", night, d, push) == "held"
    assert store.get_setting("watch.held")[-1]["title"] == "Evening digest"  # the morning brief says it


def test_the_review_words_or_codes(store):
    his(store, "Reply to Asha")
    assert digest.make_evening(store, "", NOW, "Open http://x.example")["text"] == "1 needs you: Reply to Asha."
    assert digest.make_evening(store, "", NOW, None)["text"] == "1 needs you: Reply to Asha."
    assert digest.make_evening(store, "", NOW, "Asha's reply waits.")["text"] == "Asha's reply waits."


def test_held_pushes_are_taken_into_the_evening_digest(store):
    pushes.hold(store, NOW - timedelta(hours=3), "Gas bill", "due Friday", owner="", ref="loop:4")
    mira = personalities.create(store, "Mira")
    pushes.hold(store, NOW - timedelta(hours=2), "Mira · Plumber", "x", owner=mira.id)
    d = digest.make_evening(store, "", NOW, "x")
    assert d["held"] == ["Gas bill"]
    assert [h["title"] for h in store.get_setting(pushes.HELD)] == ["Mira · Plumber"]  # hers stays for her digest


def test_pulse_shows_the_evening_digest_until_got_it(store):
    his(store, "Reply to Asha")
    digest.make_evening(store, "", NOW, "One thing needs you.")
    got = digest.for_pulse(store, "", NOW + timedelta(minutes=10))
    assert got["kind"] == "evening" and got["text"] == "One thing needs you."
    digest.seen(store, "", NOW + timedelta(minutes=11))
    assert digest.for_pulse(store, "", NOW + timedelta(minutes=12))["kind"] == "evening"  # seen isn't Got it
    digest.seen(store, "", NOW + timedelta(minutes=13), dismiss=True)
    assert digest.for_pulse(store, "", NOW + timedelta(minutes=14)) is None
    assert digest.for_pulse(store, "", NOW + timedelta(days=1, hours=-10)) is None  # yesterday's is gone


def test_away_three_hours_with_news_shows_what_happened(store):
    morning = NOW.replace(hour=9)
    digest.seen(store, "", morning)
    assert digest.for_pulse(store, "", morning + timedelta(hours=4)) is None  # nothing happened
    his(store, "Reply to Asha", shown=morning + timedelta(hours=1))
    assert digest.for_pulse(store, "", morning + timedelta(hours=2)) is None  # not 3 hours yet
    got = digest.for_pulse(store, "", morning + timedelta(hours=4))
    assert got["kind"] == "away" and got["text"] == "1 new for you: Reply to Asha."
    digest.seen(store, "", morning + timedelta(hours=4))
    assert digest.for_pulse(store, "", morning + timedelta(hours=4, minutes=1)) is None


def test_the_digest_lists_digest_lines_with_their_ids(store):
    lid = his(store, "Acme weekly", kind="newsletter", card={"sender": "news@acme.example"})
    quiet.less_like_this(store, ledger.get(store, lid), NOW)
    digest.make_evening(store, "", NOW, "x")
    assert digest.for_pulse(store, "", NOW)["quiet"] == [{"id": lid, "title": "Acme weekly"}]


def test_each_owner_has_its_own_digest(store):
    mira = personalities.create(store, "Mira")
    digest.make_evening(store, mira.id, NOW, "Mira's evening.")
    assert digest.for_pulse(store, "", NOW) is None
    assert digest.for_pulse(store, mira.id, NOW)["text"] == "Mira's evening."


# --- the morning hello's two ledger lines ---

def test_the_hello_gains_waiting_on_you_and_due_today(store):
    morning = datetime(2026, 11, 20, 7, 30, tzinfo=TZ)
    his(store, "Reply to Asha", shown=morning - timedelta(days=3))
    his(store, "Fresh card", shown=morning - timedelta(hours=10))
    ledger.open_loop(store, "", morning, "Electricity bill", "bill", owner="you", state="ready",
                     due_at="2026-11-20T00:00:00+05:30")
    ledger.open_loop(store, "", morning, "Call with Asha", "meeting", owner="them", state="waiting",
                     due_at="2026-11-20T15:00:00+05:30")
    ledger.open_loop(store, "", morning, "Next week", "bill", owner="you", state="ready",
                     due_at="2026-11-27T00:00:00+05:30")
    assert ladder.ledger_lines(store, "", morning) == ["Waiting on you: Reply to Asha (3 days)",
                                                      "Due today: Electricity bill, Call with Asha 15:00"]
    assert ladder.ledger_lines(store, "x", morning) == []
