"""Today's "Needs you": one list of cards, the watch's items and the user's own open reminders, each with two buttons."""
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from odie.store.db import Store
from odie.watch import needs, report, threads

IST = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 10, 23, 12, 0, tzinfo=IST)


@pytest.fixture
def store(isolated_settings, tmp_path):
    s = Store(tmp_path / "a.db")
    s.init_schema()
    return s


def card_with(store, *items):
    store.set_setting(report.CARD, {"checked_at": "2026-10-23T12:00:00+05:30", "line": "quiet", "needs_you": list(items),
                                    "events": [], "sources": {}})


REPLY = {"ref": "mail:r1", "title": "Reply to Asha", "why": "Asks if Saturday 4pm works", "pile": "personal",
         "suggestion": {"label": "Show the draft", "run": "Show the draft for desk item mail:r1"},
         "escape": {"label": "Not needed", "run": "Close desk item mail:r1: Not needed"}}


def test_a_watch_item_becomes_a_card_with_its_two_buttons(store):
    card_with(store, REPLY)
    [c] = needs.cards(store, NOW)
    assert c["title"] == "Reply to Asha" and c["why"] == "Asks if Saturday 4pm works" and c["icon"] == "heart"
    assert c["main"] == {"label": "Show the draft", "action": "chat", "value": "Show the draft for desk item mail:r1"}
    assert c["other"] == {"label": "Not needed", "action": "dismiss", "value": "mail:r1"}


def test_a_watch_item_without_buttons_asks_about_itself_and_can_be_dismissed(store):
    card_with(store, {"ref": "mail:s1", "title": "New sign-in", "why": "From a new laptop", "pile": "alerts"})
    [c] = needs.cards(store, NOW)
    assert c["main"]["action"] == "chat" and "mail:s1" in c["main"]["value"]
    assert c["other"] == {"label": "Dismiss", "action": "dismiss", "value": "mail:s1"}


def test_the_users_reminders_follow_with_done_and_tomorrow(store):
    card_with(store, REPLY)
    later = store.add_task("Renew passport", "reminder", due_at="2026-10-30T09:00:00+05:30")
    overdue = store.add_task("Pay electricity bill ₹2,480", "reminder", due_at="2026-10-20T09:00:00+05:30")
    undated = store.add_task("Call the plumber", "todo")
    got = needs.cards(store, NOW)
    assert [c["ref"] for c in got] == ["mail:r1", f"task:{overdue}", f"task:{later}", f"task:{undated}"]
    bill = got[1]
    assert bill["icon"] == "rupee" and bill["badge"] == "Overdue"
    assert bill["main"] == {"label": "Done", "action": "done_task", "value": overdue}
    assert bill["other"] == {"label": "Tomorrow", "action": "snooze_task", "value": overdue}
    assert got[2]["badge"] == "30 Oct, 09:00" and got[3]["badge"] == ""


def test_the_watchs_own_threads_show_only_when_dated_or_on_its_card(store):
    threads.track(store, "mail:o1", "order", "Order: desk lamp", "shipped", due="2026-10-24")  # in transit: needs nobody
    threads.track(store, "mail:b1", "bill", "Gas bill ₹900", "due", due="2026-10-25")          # a bill: fires on its date
    threads.track(store, "mail:r1", "reply", "Reply to Asha", "owed")                          # on the card already
    card_with(store, REPLY)
    titles = [c["title"] for c in needs.cards(store, NOW)]
    assert titles == ["Reply to Asha", "Gas bill ₹900"]


def test_done_items_on_the_card_are_left_out(store):
    card_with(store, {**REPLY, "done": True})
    assert needs.cards(store, NOW) == []


def test_a_reply_task_from_mail_opens_the_email(store):
    tid, _ = store.upsert_source_task("mail", "m7", "Reply to Priya Nair: Can we move our 1:1?", "followup")
    [c] = needs.cards(store, NOW)
    assert c["icon"] == "mail"
    assert c["main"] == {"label": "Open it", "action": "chat",
                         "value": "Open the email from Priya Nair about Can we move our 1:1?"}
    assert c["other"] == {"label": "Done", "action": "done_task", "value": tid}
