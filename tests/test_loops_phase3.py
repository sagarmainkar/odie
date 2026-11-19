"""Phase 3's ledger pieces (proactive design §5, §8): what a card needs kept on its loop, the loops he finished (so a
later mention attaches quietly), a loop's reminder, Later counted, Split and Reopen."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from odie.loops import ledger
from odie.store.db import Store

NOW = datetime(2026, 11, 19, 10, 0, tzinfo=ZoneInfo("Asia/Kolkata"))


@pytest.fixture
def store(isolated_settings, tmp_path):
    s = Store(tmp_path / "a.db")
    s.init_schema()
    return s


def test_a_loop_keeps_what_its_card_shows(store):
    lid = ledger.open_loop(store, "", NOW, "Reply to Asha", "reply owed", owner="you",
                           card={"pile": "personal", "draft": {"to": "asha@example.com", "subject": "Deck", "body": "Hi"}})
    assert ledger.get(store, lid)["card"]["pile"] == "personal"
    ledger.merge_card(store, lid, NOW, {"amount": {"value": 4280, "currency": "INR"}})
    card = ledger.get(store, lid)["card"]
    assert card["pile"] == "personal" and card["amount"]["value"] == 4280 and card["draft"]["body"] == "Hi"


def test_an_older_database_gains_the_card_column(tmp_path, isolated_settings):
    import sqlite3
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.execute("create table loops (id integer primary key autoincrement, personality text, title text not null, "
                 "kind text not null default '', owner text not null default 'odie', state text not null default 'new', "
                 "next_step text not null default '', playbook text not null default '', priority text not null "
                 "default 'normal', due_at text, next_check_at text, hidden_until text, refs_json text not null "
                 "default '[]', has_news integer not null default 0, result text not null default '', brief text not "
                 "null default '', link text not null default '', nudges integer not null default 0, attempts integer "
                 "not null default 0, shown_at text, tapped text, closed_by text, closed_why text, created_at text not "
                 "null, updated_at text not null, closed_at text)")
    conn.execute("insert into loops(title, created_at, updated_at) values ('old one', '2026-11-18', '2026-11-18')")
    conn.commit()
    conn.close()
    s = Store(path)
    s.init_schema()
    assert ledger.get(s, 1)["card"] == {}


def test_finished_lists_what_was_closed_and_is_still_remembered(store):
    mine = ledger.open_loop(store, "", NOW - timedelta(days=3), "Vote: Northwind ballot", "reminder", owner="you",
                            refs=["event:uid1"])
    ledger.done(store, mine, NOW - timedelta(days=1))
    odies = ledger.open_loop(store, "", NOW, "Order: lamp", "order", owner="them")
    ledger.close(store, odies, NOW, "odie", "delivered 19 Nov")
    old = ledger.open_loop(store, "", NOW - timedelta(days=60), "Old", "reminder", owner="you")
    ledger.done(store, old, NOW - timedelta(days=40))
    assert [lp["id"] for lp in ledger.finished(store, "", NOW)] == [odies, mine]  # Odie's closes are shown too
    assert "finished by you" in ledger.finished_line(ledger.get(store, mine))
    assert "closed by Odie" in ledger.finished_line(ledger.get(store, odies))


def test_a_loops_reminder_is_the_task_it_points_at(store):
    lid = ledger.open_loop(store, "", NOW, "Vote", "reminder", owner="you", refs=["event:uid1", "task:12"])
    assert ledger.reminder_of(ledger.get(store, lid)) == 12
    other = ledger.open_loop(store, "", NOW, "Order", "order", refs=["mail:m1"])
    assert ledger.reminder_of(ledger.get(store, other)) is None
    assert ledger.pointing_at(store, 12)["id"] == lid


def test_closing_a_loop_closes_the_reminder_odie_made_for_it(store):
    tid = store.add_task("Vote: Northwind ballot", "reminder", due_at="2026-11-21T09:00+05:30", source_kind="loop",
                         source_ref="loop:1", origin="agent")
    own = store.add_task("Pay rent", "reminder", due_at="2026-11-21T09:00+05:30")
    lid = ledger.open_loop(store, "", NOW, "Vote", "reminder", owner="you", refs=[f"task:{tid}"])
    other = ledger.open_loop(store, "", NOW, "Rent", "reminder", owner="you", refs=[f"task:{own}"])
    ledger.done(store, lid, NOW)
    ledger.done(store, other, NOW)
    assert store.one("select status from tasks where id=?", (tid,))["status"] == "done"
    assert store.one("select status from tasks where id=?", (own,))["status"] == "open"  # his own: never touched


def test_the_third_later_goes_to_sunday(store):
    lid = ledger.open_loop(store, "", NOW, "Reply to Asha", "reply owed", owner="you")
    assert ledger.laters(store, lid) == 0
    ledger.note_later(store, lid, NOW, "2026-11-20T09:00:00+05:30")
    ledger.note_later(store, lid, NOW, "2026-11-21T09:00:00+05:30")
    assert ledger.laters(store, lid) == 2


def test_split_moves_the_chosen_evidence_and_refs_to_a_new_loop(store):
    lid = ledger.open_loop(store, "", NOW, "Invoices from Northwind", "bill", owner="you", refs=["mail:a1"],
                           source="mail", ref="mail:a1", fact="Invoice 101: Rs 4,000 due 25 Nov")
    ledger.attach(store, lid, NOW, "mail", "mail:a2", "Invoice 102: Rs 9,000 due 30 Nov", refs=["mail:a2"])
    wrong = [e for e in ledger.events(store, lid) if e["ref"] == "mail:a2"]
    new = ledger.split(store, lid, [wrong[0]["id"]], NOW)
    assert new != lid
    assert "mail:a2" not in ledger.get(store, lid)["refs"] and ledger.get(store, new)["refs"] == ["mail:a2"]
    facts_new = [e["fact"] for e in ledger.events(store, new)]
    assert facts_new[0] == "Invoice 102: Rs 9,000 due 30 Nov" and any("Split off from #" in f for f in facts_new)
    assert any("Split off into #" in e["fact"] for e in ledger.events(store, lid))
    assert ledger.get(store, new)["state"] == "ready"  # his: a card of its own
    with pytest.raises(ValueError):
        ledger.split(store, lid, [], NOW)


def test_reopen_only_within_seven_days(store):
    lid = ledger.open_loop(store, "", NOW, "Order: lamp", "order", owner="them")
    ledger.close(store, lid, NOW - timedelta(days=8), "odie", "delivered")
    assert not ledger.may_reopen(ledger.get(store, lid), NOW)
    other = ledger.open_loop(store, "", NOW, "Order: desk", "order", owner="them")
    ledger.close(store, other, NOW - timedelta(days=2), "odie", "delivered")
    assert ledger.may_reopen(ledger.get(store, other), NOW)
    assert not ledger.may_reopen(ledger.get(store, ledger.open_loop(store, "", NOW, "x", "y")), NOW)  # open


# --- Cards are a view of loops (design §8) ---

def test_every_ready_loop_is_one_card_with_why_and_the_three_buttons(store):
    from odie.loops import cards
    from odie.watch import needs
    lid = ledger.open_loop(store, "", NOW, "Reply to Asha", "reply owed", owner="you", refs=["mail:m1", "thread:t1"],
                           state="ready", result="asks for the deck by Friday", source="mail", ref="mail:m1",
                           fact="Send the deck by Friday",
                           card={"pile": "personal", "draft": {"to": "asha@example.com", "subject": "Deck", "body": "Hi"},
                                 "suggestion": "Show the draft", "from": "Asha"})
    got = [c for c in needs.cards(store, NOW, "") if c["ref"] == f"loop:{lid}"]
    assert len(got) == 1
    card = got[0]
    assert card["why"] == "asks for the deck by Friday" and card["pile"] == "personal" and card["icon"] == "heart"
    assert card["main"] == {"label": "Show the draft", "action": "chat", "value": f"Show the draft for loop #{lid}"}
    assert card["other"]["action"] == "loop_done" and card["later"] == {"label": "Later", "action": "later",
                                                                         "value": f"loop:{lid}"}
    assert card["evidence"][0]["fact"] == "Send the deck by Friday" and card["evidence"][0]["id"]
    assert card["more"][0] == {"label": "Split", "action": "split", "value": lid}  # then Less like this, Forget this
    for name in ("main", "other", "later", "pile", "since", "decide", "ref", "title", "why", "icon", "badge", "ask"):
        assert name in card  # the fields the Mac app reads


def test_a_bill_card_shows_its_amount_and_a_loops_reminder_is_not_a_second_card(store):
    from odie.watch import needs
    tid = store.add_task("Pay electricity bill", "reminder", due_at="2026-11-25T09:00+05:30", source_kind="loop",
                         source_ref="loop:1", origin="agent")
    lid = ledger.open_loop(store, "", NOW, "Pay electricity bill", "bill", owner="you", refs=[f"task:{tid}"],
                           state="ready", card={"pile": "bills", "amount": {"value": 4280, "currency": "INR"}})
    own = store.add_task("Call the plumber", "todo")
    refs = [c["ref"] for c in needs.cards(store, NOW, "")]
    assert refs.count(f"loop:{lid}") == 1 and f"task:{tid}" not in refs and f"task:{own}" in refs
    card = next(c for c in needs.cards(store, NOW, "") if c["ref"] == f"loop:{lid}")
    assert card["badge"] == "₹4,280" and card["pile"] == "bills" and card["icon"] == "rupee"


def test_an_old_watch_thread_task_is_never_a_card_of_its_own(store):
    from odie.watch import needs
    store.add_task("Gas bill", "reminder", due_at="2026-11-25T09:00+05:30", source_kind="watch", source_ref="mail:g1",
                   origin="agent")
    assert [c for c in needs.cards(store, NOW, "") if c["title"] == "Gas bill"] == []


def test_the_third_later_puts_the_card_off_until_sunday(store):
    from odie.watch import needs
    lid = ledger.open_loop(store, "", NOW, "Reply to Asha", "reply owed", owner="you", state="ready")
    assert needs.later(store, f"loop:{lid}", NOW, "") == "2026-11-20T09:00:00+05:30"
    assert needs.later(store, f"loop:{lid}", NOW, "") == "2026-11-20T09:00:00+05:30"
    assert needs.later(store, f"loop:{lid}", NOW, "") == "2026-11-22T09:00:00+05:30"  # Thursday 19 Nov -> Sunday 22
    assert ledger.laters(store, lid) == 3


def test_on_sunday_cards_waiting_over_a_week_fold_into_one_still_care_card(store):
    from odie.watch import needs
    sunday = datetime(2026, 11, 22, 10, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    old = [ledger.open_loop(store, "", sunday - timedelta(days=8), f"Old {n}", "reply owed", owner="you", state="ready")
           for n in range(2)]
    fresh = ledger.open_loop(store, "", sunday - timedelta(days=1), "Fresh", "reply owed", owner="you", state="ready")
    refs = [c["ref"] for c in needs.cards(store, sunday, "")]
    assert "batch:sunday" in refs and f"loop:{fresh}" in refs and not any(f"loop:{lid}" in refs for lid in old)
    batch = next(c for c in needs.cards(store, sunday, "") if c["ref"] == "batch:sunday")
    assert batch["title"] == "Still care? 2 waiting over a week" and len(batch["evidence"]) == 2
    assert batch["other"] == {"label": "Drop them", "action": "dismiss", "value": "batch:sunday"}
    monday = sunday + timedelta(days=1)
    refs = [c["ref"] for c in needs.cards(store, monday, "")]
    assert "batch:sunday" not in refs and all(f"loop:{lid}" in refs for lid in old)  # back one by one on Monday
    from odie.loops import cards
    assert cards.drop_batch(store, "", sunday) == 2
    assert all(ledger.get(store, lid)["state"] == "dropped" for lid in old)
    assert ledger.get(store, old[0])["closed_by"] == "you"
