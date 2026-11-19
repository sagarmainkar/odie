"""Pulse's "Needs you": one list of cards, the loops that need the user (what the watch found, one card per thing) and
his own open reminders, each with three buttons: the one move (the draft, the check's label, else "Tell me more"),
Done and Later."""
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from odie.store.db import Store
from odie.loops import ledger
from odie.watch import needs, report

IST = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 10, 23, 12, 0, tzinfo=IST)


@pytest.fixture
def store(isolated_settings, tmp_path):
    s = Store(tmp_path / "a.db")
    s.init_schema()
    return s


def card_with(store, *items) -> list[int]:
    """The watch's findings as stage 2 leaves them: a ready loop each (one ticked done is closed by him). Returns ids."""
    ids = []
    for item in items:
        card = {k: item[k] for k in ("pile", "draft", "from", "subject", "amount") if k in item}
        if item.get("suggestion"):
            card["suggestion"] = item["suggestion"]["label"]
        at = datetime.fromisoformat(item["at"]) if item.get("at") else NOW
        lid = ledger.open_loop(store, "", at, item["title"], "needs you", owner="you", refs=[item["ref"]], state="ready",
                               result=item.get("why", ""), card=card, source="mail", ref=item["ref"],
                               fact=item["title"])
        if item.get("done"):
            ledger.done(store, lid, NOW)
        ids.append(lid)
    store.set_setting(report.CARD, {"checked_at": "2026-10-23T12:00:00+05:30", "line": "quiet", "events": [],
                                    "sources": {}})
    return ids


REPLY = {"ref": "mail:r1", "title": "Reply to Asha", "why": "Asks if Saturday 4pm works", "pile": "personal",
         "draft": {"to": "asha@example.com", "subject": "Re: Saturday", "body": "SECRET-DRAFT-BODY"},
         "suggestion": {"label": "Show the draft", "run": "Show the draft for watch item mail:r1"},
         "escape": {"label": "Not needed", "run": "Close watch item mail:r1: Not needed"}}


def test_a_loop_becomes_a_card_with_its_three_buttons(store):
    [lid] = card_with(store, REPLY)
    [c] = needs.cards(store, NOW)
    assert c["title"] == "Reply to Asha" and c["why"] == "Asks if Saturday 4pm works" and c["icon"] == "heart"
    assert c["main"] == {"label": "Show the draft", "action": "chat", "value": f"Show the draft for loop #{lid}"}
    assert c["other"] == {"label": "Done", "action": "loop_done", "value": lid}  # the model's way out is no button
    assert c["later"] == {"label": "Later", "action": "later", "value": f"loop:{lid}"}
    assert "SECRET-DRAFT-BODY" not in str(c)  # a drafted reply never goes on a card: chat shows it when asked
    assert c["evidence"] and c["evidence"][0]["fact"] == "Reply to Asha"  # Why?, on every card


def test_a_loop_without_a_move_asks_about_itself_with_done_and_later(store):
    [lid] = card_with(store, {"ref": "mail:s1", "title": "New sign-in", "why": "From a new laptop", "pile": "alerts"})
    [c] = needs.cards(store, NOW)
    assert c["main"] == {"label": "Tell me more", "action": "chat", "value": f"Tell me about loop #{lid}: New sign-in"}
    assert c["decide"] is True


def test_a_card_put_off_till_later_stays_hidden_until_9_the_next_morning(store):
    reply, sign_in = card_with(store, REPLY, {"ref": "mail:s1", "title": "New sign-in", "pile": "alerts"})
    assert needs.later(store, f"loop:{reply}", NOW) == "2026-10-24T09:00:00+05:30"
    assert [c["ref"] for c in needs.cards(store, NOW)] == [f"loop:{sign_in}"]
    the_next_morning = datetime(2026, 10, 24, 9, 0, tzinfo=IST)
    assert {c["ref"] for c in needs.cards(store, the_next_morning)} == {f"loop:{reply}", f"loop:{sign_in}"}


def test_later_is_always_the_next_days_9am(store):
    assert needs.later_until(datetime(2026, 10, 23, 23, 50, tzinfo=IST)) == "2026-10-24T09:00:00+05:30"
    assert needs.later_until(datetime(2026, 10, 31, 8, 0, tzinfo=IST)) == "2026-11-01T09:00:00+05:30"


def test_a_hidden_card_stays_hidden_when_a_check_adds_to_its_loop(store):
    from odie.loops import consolidate
    [lid] = card_with(store, REPLY)
    needs.later(store, f"loop:{lid}", NOW)
    again = {"id": "F1", "ref": "mail:r2", "title": "Reply to Asha again", "kind": "reply owed", "why": "", "owner": "you",
             "due": None, "remind_at": None, "done": "", "stage": "", "push": False, "refs": ["mail:r2"], "card": {}}
    consolidate.apply(store, "", NOW, [again], {"F1": {"is": "same", "loop": lid}}, {})
    assert ledger.get(store, lid)["hidden_until"] == "2026-10-24T09:00:00+05:30"
    assert needs.cards(store, NOW) == []


def test_later_on_a_task_snoozes_it_till_9_the_next_morning(store):
    tid = store.add_task("Call the plumber", "todo")
    assert needs.later(store, f"task:{tid}", NOW) == "2026-10-24T09:00:00+05:30"
    assert needs.cards(store, NOW) == []
    assert store.one("select snoozed_until from tasks where id=?", (tid,))["snoozed_until"] == "2026-10-24T09:00:00+05:30"


def test_later_on_something_not_there_says_so(store):
    card_with(store, REPLY)
    assert needs.later(store, "mail:gone", NOW) is None and needs.later(store, "loop:999", NOW) is None
    assert needs.later(store, "task:999", NOW) is None


def test_the_users_reminders_follow_with_tell_me_more_done_and_later(store):
    [lid] = card_with(store, REPLY)
    later = store.add_task("Renew passport", "reminder", due_at="2026-10-30T09:00:00+05:30")
    overdue = store.add_task("Pay electricity bill ₹2,480", "reminder", due_at="2026-10-20T09:00:00+05:30")
    undated = store.add_task("Call the plumber", "todo")
    got = needs.cards(store, NOW)
    assert [c["ref"] for c in got] == [f"loop:{lid}", f"task:{overdue}", f"task:{later}", f"task:{undated}"]
    bill = got[1]
    assert bill["icon"] == "rupee" and bill["badge"] == "Overdue"
    assert bill["main"] == {"label": "Tell me more", "action": "chat", "value": f"Tell me about task #{overdue}: Pay electricity bill ₹2,480"}
    assert bill["other"] == {"label": "Done", "action": "done_task", "value": overdue}
    assert bill["later"] == {"label": "Later", "action": "later", "value": f"task:{overdue}"}
    assert got[2]["badge"] == "30 Oct, 09:00" and got[3]["badge"] == ""


def test_the_watchs_old_threads_and_a_loops_reminders_are_no_cards_of_their_own(store):
    store.add_task("Gas bill ₹900", "reminder", due_at="2026-10-25T09:00+05:30", source_kind="watch",
                   source_ref="mail:b1", origin="agent")
    tid = store.add_task("Vote reminder", "reminder", due_at="2026-10-25T09:00+05:30", source_kind="loop",
                         source_ref="loop:1", origin="agent")
    [lid] = card_with(store, REPLY)
    ledger.add_refs(store, lid, NOW, [f"task:{tid}"])
    titles = [c["title"] for c in needs.cards(store, NOW)]
    assert titles == ["Reply to Asha"]


def test_loops_he_finished_are_left_out(store):
    card_with(store, {**REPLY, "done": True})
    assert needs.cards(store, NOW) == []


def test_a_reply_task_from_mail_opens_the_email(store):
    tid, _ = store.upsert_source_task("mail", "m7", "Reply to Priya Nair: Can we move our 1:1?", "followup")
    [c] = needs.cards(store, NOW)
    assert c["icon"] == "mail"
    assert c["main"] == {"label": "Open it", "action": "chat",
                         "value": "Open the email from Priya Nair about Can we move our 1:1?"}
    assert c["other"] == {"label": "Done", "action": "done_task", "value": tid}
    assert c["later"] == {"label": "Later", "action": "later", "value": f"task:{tid}"}
    assert c["decide"] is False  # Odie has a move: opening the mail


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


def test_a_loop_card_says_its_pile_since_and_whether_it_needs_a_choice(store):
    declined = {"ref": "mail:s1", "title": "Card payment declined", "why": "No retry since", "pile": "alerts",
                "at": "2026-10-23T11:00:00+05:30"}
    card_with(store, {**REPLY, "at": "2026-10-21T09:00:00+05:30"}, declined, {"ref": "mail:u1", "title": "Odd", "pile": "urgent"})
    unlabelled, choice, reply = needs.cards(store, NOW)  # newest first
    assert (reply["pile"], reply["since"], reply["decide"]) == ("personal", "2026-10-21T09:00:00+05:30", False)
    assert (choice["pile"], choice["since"], choice["decide"]) == ("alerts", "2026-10-23T11:00:00+05:30", True)
    assert (unlabelled["pile"], unlabelled["decide"]) == ("alerts", True)


def test_the_users_tasks_get_a_pile_from_their_icon_and_decide_unless_odie_can_open_the_mail(store):
    bill = store.add_task("Pay electricity bill ₹2,480", "reminder", due_at="2026-10-20T09:00:00+05:30")
    store.add_task("Order: desk lamp", "todo")
    store.add_task("Call the plumber", "todo")
    store.update_task(bill, created_at="2026-10-21T03:30:00.000Z")
    store.upsert_source_task("mail", "m7", "Reply to Sam Lee: Lunch on Friday?", "followup")
    got = {c["title"]: c for c in needs.cards(store, NOW)}
    assert got["Pay electricity bill ₹2,480"]["pile"] == "bills"
    assert got["Pay electricity bill ₹2,480"]["since"] == "2026-10-21T09:00:00+05:30"
    assert got["Order: desk lamp"]["pile"] == "orders" and got["Call the plumber"]["pile"] == "alerts"
    assert got["Reply to Sam Lee: Lunch on Friday?"]["pile"] == "alerts"
    assert got["Reply to Sam Lee: Lunch on Friday?"]["decide"] is False  # "Open it" is Odie's move
    assert got["Call the plumber"]["decide"] is True  # only "Tell me more": the choice is the user's


def test_the_fields_the_mac_app_reads_are_all_there(store):
    [lid] = card_with(store, REPLY)
    [c] = needs.cards(store, NOW)
    assert OLD_KEYS | {"pile", "since", "decide", "later", "brief", "evidence"} <= set(c)
    assert {k: c[k] for k in OLD_KEYS} == {
        "ref": f"loop:{lid}", "title": "Reply to Asha", "why": "Asks if Saturday 4pm works", "icon": "heart", "badge": "",
        "ask": f"Tell me about loop #{lid}: Reply to Asha",
        "main": {"label": "Show the draft", "action": "chat", "value": f"Show the draft for loop #{lid}"},
        "other": {"label": "Done", "action": "loop_done", "value": lid}}


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
