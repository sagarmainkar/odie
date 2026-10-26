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
         "draft": {"to": "asha@example.com", "subject": "Re: Saturday", "body": "SECRET-DRAFT-BODY"},
         "suggestion": {"label": "Show the draft", "run": "Show the draft for watch item mail:r1"},
         "escape": {"label": "Not needed", "run": "Close watch item mail:r1: Not needed"}}


def test_a_watch_item_becomes_a_card_with_its_two_buttons(store):
    card_with(store, REPLY)
    [c] = needs.cards(store, NOW)
    assert c["title"] == "Reply to Asha" and c["why"] == "Asks if Saturday 4pm works" and c["icon"] == "heart"
    assert c["main"] == {"label": "Show the draft", "action": "chat", "value": "Show the draft for watch item mail:r1"}
    assert c["other"] == {"label": "Not needed", "action": "dismiss", "value": "mail:r1"}
    assert "SECRET-DRAFT-BODY" not in str(c)  # a drafted reply never goes on a card: chat shows it when asked


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


def test_notes_the_watch_told_in_the_last_day_go_under_needs_you(store):
    """With the Desk gone, what the watch did for a Watch for entry (and said worth telling) shows on Today; quiet
    notes and older ones don't."""
    card_with(store)
    card = store.get_setting(report.CARD)
    card["done"] = [
        {"at": "2026-10-21T10:00:00+05:30", "message": "Older heads-up", "told": True},
        {"at": "2026-10-23T09:00:00+05:30", "message": "HN: still no reply", "told": False},
        {"at": "2026-10-23T10:00:00+05:30", "message": "Added a heads-up for the recital", "told": True,
         "media": [{"id": "abc", "kind": "file", "title": "deck.pptx", "filename": "deck.pptx", "size": 10}]},
    ]
    store.set_setting(report.CARD, card)
    notes = needs.recent_notes(store, NOW)
    assert [n["message"] for n in notes] == ["Added a heads-up for the recital"]
    assert notes[0]["media"][0]["id"] == "abc"


OLD_KEYS = {"ref", "title", "why", "icon", "badge", "ask", "main", "other"}


def test_a_watch_card_says_its_pile_since_and_whether_it_needs_a_choice(store):
    declined = {"ref": "mail:s1", "title": "Card payment declined", "why": "No retry since", "pile": "alerts",
                "escape": {"label": "It was me", "run": "Close watch item mail:s1: It was me"},
                "at": "2026-10-23T11:00:00+05:30"}
    card_with(store, {**REPLY, "at": "2026-10-21T09:00:00+05:30"}, declined, {"ref": "mail:u1", "title": "Odd", "pile": "urgent"})
    reply, choice, unlabelled = needs.cards(store, NOW)
    assert (reply["pile"], reply["since"], reply["decide"]) == ("personal", "2026-10-21T09:00:00+05:30", False)
    assert (choice["pile"], choice["since"], choice["decide"]) == ("alerts", "2026-10-23T11:00:00+05:30", True)
    assert (unlabelled["pile"], unlabelled["since"], unlabelled["decide"]) == ("alerts", "", True)


def test_the_users_tasks_get_a_pile_from_their_icon_and_never_decide(store):
    bill = store.add_task("Pay electricity bill ₹2,480", "reminder", due_at="2026-10-20T09:00:00+05:30")
    order = store.add_task("Order: desk lamp", "todo")
    plain = store.add_task("Call the plumber", "todo")
    store.update_task(bill, created_at="2026-10-21T03:30:00.000Z")
    store.upsert_source_task("mail", "m7", "Reply to Sam Lee: Lunch on Friday?", "followup")
    got = {c["title"]: c for c in needs.cards(store, NOW)}
    assert got["Pay electricity bill ₹2,480"]["pile"] == "bills"
    assert got["Pay electricity bill ₹2,480"]["since"] == "2026-10-21T09:00:00+05:30"
    assert got["Order: desk lamp"]["pile"] == "orders" and got["Call the plumber"]["pile"] == "alerts"
    assert got["Reply to Sam Lee: Lunch on Friday?"]["pile"] == "alerts"
    assert not any(c["decide"] for c in got.values())


def test_the_old_fields_are_untouched(store):
    card_with(store, REPLY)
    [c] = needs.cards(store, NOW)
    assert set(c) == OLD_KEYS | {"pile", "since", "decide"}
    assert {k: c[k] for k in OLD_KEYS} == {
        "ref": "mail:r1", "title": "Reply to Asha", "why": "Asks if Saturday 4pm works", "icon": "heart", "badge": "",
        "ask": "Tell me about watch item mail:r1",
        "main": {"label": "Show the draft", "action": "chat", "value": "Show the draft for watch item mail:r1"},
        "other": {"label": "Not needed", "action": "dismiss", "value": "mail:r1"}}


def test_a_task_with_an_unreadable_created_at_has_no_since(store):
    tid = store.add_task("Call the plumber", "todo")
    store.update_task(tid, created_at="yesterday")
    [c] = needs.cards(store, NOW)
    assert c["since"] == ""


def test_counts_cover_every_pile_with_zeros(store):
    card_with(store, REPLY, {"ref": "mail:s1", "title": "New sign-in", "pile": "alerts"})
    store.add_task("Pay electricity bill ₹2,480", "reminder", due_at="2026-10-20T09:00:00+05:30")
    assert needs.counts(needs.cards(store, NOW)) == {"alerts": 1, "bills": 1, "events": 0, "personal": 1, "orders": 0}
    assert needs.counts([]) == {"alerts": 0, "bills": 0, "events": 0, "personal": 0, "orders": 0}
