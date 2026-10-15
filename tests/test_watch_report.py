"""The card and the pushes: refs checked, never the same ref twice, at most 3, quiet hours held for the brief, the
first check silent, a check without a report still leaves a card, and a failing source said once."""
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from odie.store.db import Store
from odie.watch import report
from odie.watch.fetch import Event, Mail

TZ = ZoneInfo("Asia/Kolkata")
DAY = datetime(2026, 10, 8, 10, 0, tzinfo=TZ)
MAILS = [Mail(f"m{i}", "a@b.c", f"Subject {i}", "2026-10-08T09:00:00Z", "s", [], "mail:z") for i in range(5)]
EVENTS = [Event("e1", "Standup", "2026-10-08T15:00:00+05:30", "", "", [], "calendar:z", "new")]


@pytest.fixture
def store(isolated_settings, tmp_path):
    s = Store(tmp_path / "a.db")
    s.init_schema()
    return s


def item(ref, push=True):
    return {"ref": ref, "title": f"About {ref}", "why": "due Friday", "push": push}


def test_refs_are_checked_and_pushes_capped(store):
    out = report.apply(store, DAY, [item("mail:m0"), item("mail:m1"), item("mail:m2"), item("mail:m3"), item("mail:zzz"), item("event:e1", push=False)],
                       "4 new emails", MAILS, EVENTS, {}, first=False)
    assert [i["ref"] for i in out] == ["mail:m0", "mail:m1", "mail:m2"]  # at most 3; the made-up ref is dropped
    card = store.get_setting(report.CARD)
    assert [i["ref"] for i in card["needs_you"]] == ["mail:m0", "mail:m1", "mail:m2", "mail:m3", "event:e1"]
    assert card["line"] == "4 new emails" and card["events"][0]["title"] == "Standup"


def test_never_the_same_ref_twice(store):
    report.apply(store, DAY, [item("mail:m0")], "", MAILS, EVENTS, {}, first=False)
    again = report.apply(store, DAY, [item("mail:m0")], "", MAILS, EVENTS, {}, first=False)
    assert again == [] and [i["ref"] for i in store.get_setting(report.CARD)["needs_you"]] == ["mail:m0"]


def test_quiet_hours_hold_for_the_brief(store):
    night = datetime(2026, 10, 8, 23, 30, tzinfo=TZ)
    assert report.quiet(night) and not report.quiet(DAY)
    assert report.apply(store, night, [item("mail:m0")], "", MAILS, EVENTS, {}, first=False) == []
    assert [i["ref"] for i in store.get_setting(report.HELD)] == ["mail:m0"]


def test_the_first_check_never_pushes(store):
    assert report.apply(store, DAY, [item("mail:m0")], "", MAILS, EVENTS, {}, first=True) == []
    assert store.get_setting(report.CARD)["needs_you"][0]["ref"] == "mail:m0"


def test_no_report_still_leaves_a_card(store):
    report.fallback(store, DAY, MAILS, EVENTS, {"mail:z": {"ok": True, "app": "Zapier", "kind": "mail"}}, "the model didn't answer")
    card = store.get_setting(report.CARD)
    assert card["needs_you"] == [] and "5 new emails" in card["line"] and "Standup" in card["line"] and "didn't answer" in card["off"]


def test_a_failing_source_is_said_once_and_its_return_once(store):
    st = {"mail:z": {"ok": False, "app": "Zapier", "kind": "mail", "reason": "401"}}
    store.set_setting("watch.state", {"sources": {"mail:z": {"fails": 2}}})
    assert report.failing_now(store, st) == ["Zapier"]  # the third failure in a row
    store.set_setting("watch.state", {"sources": {"mail:z": {"fails": 3}}})
    assert report.failing_now(store, st) == []  # said already
    assert report.recovered_now(store, {"mail:z": {"ok": True, "app": "Zapier", "kind": "mail"}}) == ["Zapier"]


def test_a_mail_item_keeps_its_sender_subject_time_and_gist(store):
    """Today draws a needs-you item as the chat's mail row: the sender's letter, "Sender · subject", the reason, the time.
    The report has the mails in hand when it writes an item, so a mail item carries those fields; an event item or a
    mail that isn't in this check's list carries only what the model wrote."""
    mails = [*MAILS, Mail("m9", "Priya Nair <priya@acme.example>", "Lease renewal", "2026-10-08T06:00:00Z", "Sign by Friday please.", [], "mail:z")]
    report.apply(store, DAY, [item("mail:m9"), item("mail:m0"), item("event:e1", push=False)], "", mails, EVENTS, {}, first=True)
    by_ref = {i["ref"]: i for i in store.get_setting(report.CARD)["needs_you"]}
    priya = by_ref["mail:m9"]
    assert (priya["from"], priya["subject"], priya["when"], priya["gist"]) == ("Priya Nair", "Lease renewal", "2026-10-08T06:00:00Z", "Sign by Friday please.")
    assert priya["title"] == "About mail:m9" and priya["why"] == "due Friday"  # the model's words stay
    assert by_ref["mail:m0"]["from"] == "a@b.c"  # a bare address is the name there is
    assert "from" not in by_ref["event:e1"]
