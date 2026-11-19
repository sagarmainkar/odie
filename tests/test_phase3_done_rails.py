"""Done stays Done, whatever stage 2's model answers (19 Nov 2026, from the fourth pass's eval run, where the model
answered "new, after #1" for the very event he had just dismissed):
  - the same mail or event, unchanged, never opens a new loop after his Done; a calendar shows an event at every
    check, so the model is asked about it again and again, and one sloppy answer would bring the card back
  - the same event at a new time (it moved, or it is the next occurrence of a repeating one) may, when the model says
    so and names the finished loop
  - a finding with no ID of its own (a digest note's line) that has the title and the due day of a loop he finished
    attaches quietly too"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from odie.loops import consolidate, ledger
from odie.store.db import Store

TZ = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 11, 19, 9, 0, tzinfo=TZ)
DENTIST = "Dentist moved to 16:00"
VOTE = "Vote: Northwind postal ballot — e-voting closes 21 Nov"


@pytest.fixture
def store(isolated_settings, tmp_path):
    s = Store(tmp_path / "a.db")
    s.init_schema()
    return s


def finding(ref, title, due=None, refs=None, remind=None):
    return {"id": "F1", "ref": ref, "title": title, "kind": "event", "why": "", "owner": "you", "due": due,
            "remind_at": remind, "done": "", "stage": "", "push": True, "refs": refs or [ref], "card": {},
            "from_github": False}


def place(store, found, answer, now):
    answers = {}
    if answer is not None:
        answers = {"F1": answer}
    return consolidate.apply(store, "", now, [found], answers, consolidate.hints(store, "", [found], now))


def dismissed_dentist(store) -> int:
    """The dentist's event became a card at 09:00 and he tapped Done at 09:10."""
    first = place(store, finding("event:e5", DENTIST, due="2026-11-19T16:00+05:30"), {"is": "new"}, NOW)
    lid = first.opened[0]
    ledger.done(store, lid, NOW + timedelta(minutes=10))
    return lid


def test_the_same_event_at_the_same_time_never_comes_back_even_when_the_model_names_the_finished_loop(store):
    lid = dismissed_dentist(store)
    again = finding("event:e5", DENTIST, due="2026-11-19T16:00+05:30", remind="2026-11-19T15:00+05:30")
    got = place(store, again, {"is": "new", "after": lid, "why": "the appointment moved"}, NOW + timedelta(minutes=30))
    assert got.opened == [] and got.quiet == [lid] and got.reminders == 0 and got.to_push == []
    assert store.one("select count(*) n from loops")["n"] == 1


def test_the_same_event_at_a_new_time_may_open_a_new_loop_after_the_finished_one(store):
    lid = dismissed_dentist(store)
    moved = finding("event:e5", "Dentist moved to Friday 10:00", due="2026-11-20T10:00+05:30")
    got = place(store, moved, {"is": "new", "after": lid, "why": "moved again"}, NOW + timedelta(hours=3))
    assert len(got.opened) == 1 and got.opened[0] != lid


def test_a_new_mail_about_a_finished_thing_may_open_a_new_loop(store):
    lid = dismissed_dentist(store)
    mail = finding("mail:m9", "Dentist asks you to confirm Friday", refs=["mail:m9", "event:e5"])
    got = place(store, mail, {"is": "new", "after": lid, "why": "the clinic asks for a confirmation"},
                NOW + timedelta(hours=3))
    assert len(got.opened) == 1


def test_a_loop_carried_by_the_upgrade_takes_the_first_sight_of_its_event_as_the_time_it_knew(store):
    # The upgrade's loop for a reminder: its due is the reminder's ring time, not the event's start.
    lid = ledger.open_loop(store, "", NOW - timedelta(days=2), VOTE, "reminder", owner="you", refs=["event:uid1"],
                           state="ready", due_at="2026-11-20T08:30+05:30")
    ledger.done(store, lid, NOW - timedelta(hours=3))
    event = finding("event:uid1", VOTE, due="2026-11-21T17:00+05:30", remind="2026-11-20T08:30+05:30")
    first = place(store, event, {"is": "new", "after": lid, "why": "x"}, NOW)
    assert first.opened == [] and first.quiet == [lid]
    second = place(store, event, {"is": "new", "after": lid, "why": "x"}, NOW + timedelta(minutes=30))
    assert second.opened == [] and second.quiet == [lid]
    assert store.one("select count(*) n from tasks")["n"] == 0  # and no reminder was made for it


def test_a_digest_line_with_the_title_and_day_of_a_thing_he_finished_attaches_quietly(store):
    first = place(store, finding("event:uid1", VOTE, due="2026-11-21T17:00+05:30"), {"is": "new"}, NOW)
    lid = first.opened[0]
    ledger.done(store, lid, NOW + timedelta(minutes=10))
    digest = finding("note:Inbox/digest 19 Nov.md", VOTE, due="2026-11-21T09:00+05:30",
                     remind="2026-11-20T08:30+05:30")
    for answer in ({"is": "new"}, None):
        got = place(store, digest, answer, NOW + timedelta(hours=2))
        assert got.opened == [] and got.quiet == [lid] and got.reminders == 0


def test_next_months_bill_in_a_digest_is_new_though_last_months_has_the_same_title(store):
    first = place(store, finding("note:Inbox/digest Oct.md", "Pay electricity bill", due="2026-10-30T09:00+05:30"),
                  {"is": "new"}, NOW - timedelta(days=25))
    ledger.done(store, first.opened[0], NOW - timedelta(days=22))
    november = finding("note:Inbox/digest Nov.md", "Pay electricity bill", due="2026-11-29T09:00+05:30")
    got = place(store, november, {"is": "new"}, NOW)
    assert len(got.opened) == 1 and got.quiet == []


def test_a_digest_line_with_no_due_is_not_silenced_by_last_months_same_title(store):
    first = place(store, finding("note:Inbox/digest Oct.md", "Pay the maid's salary"), {"is": "new"},
                  NOW - timedelta(days=25))
    ledger.done(store, first.opened[0], NOW - timedelta(days=24))
    november = finding("note:Inbox/digest Nov.md", "Pay the maid's salary")
    got = place(store, november, {"is": "new"}, NOW)
    assert len(got.opened) == 1 and got.quiet == []


def test_the_same_mail_never_comes_back_though_the_model_reads_another_due_time_from_it(store):
    first = place(store, finding("mail:m1", "Send the signed form", due="2026-11-21T09:00+05:30"), {"is": "new"}, NOW)
    lid = first.opened[0]
    ledger.done(store, lid, NOW + timedelta(minutes=10))
    again = finding("mail:m1", "Send the signed form", due="2026-11-21T23:59+05:30")
    got = place(store, again, {"is": "new", "after": lid, "why": "x"}, NOW + timedelta(hours=1))
    assert got.opened == [] and got.quiet == [lid]


def test_an_events_own_start_is_what_counts_not_a_deadline_the_model_read(store):
    def party(due):
        found = finding("event:p1", "Team dinner", due=due)
        found["card"] = {"when": "2026-11-25T19:00+05:30"}  # the calendar's own start, set by code
        return found
    first = place(store, party("2026-11-22T12:00+05:30"), {"is": "new"}, NOW)  # "RSVP by the 22nd"
    lid = first.opened[0]
    ledger.done(store, lid, NOW + timedelta(minutes=10))
    got = place(store, party("2026-11-25T19:00+05:30"), {"is": "new", "after": lid, "why": "x"},
                NOW + timedelta(hours=1))
    assert got.opened == [] and got.quiet == [lid]
