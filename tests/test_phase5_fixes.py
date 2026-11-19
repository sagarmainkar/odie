"""Phase 5's fix pass (the independent review's R1-R11), each written as the safe outcome: learning counts only what
he really left untouched, the review's stale and merge rails hold across evenings and undo cleanly, the digest's
words carry no address, and Forget and Undo never touch his own reminders or his Done."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from odie.loops import digest, learn, ledger, quiet, review
from odie.store.db import Store

TZ = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 11, 19, 19, 30, tzinfo=TZ)


@pytest.fixture
def store(isolated_settings, tmp_path):
    s = Store(tmp_path / "a.db")
    s.init_schema()
    return s


def loop(store, title, kind="reply owed", owner="you", pid="", fact="From mail", ref="", days=2, **kw):
    state = kw.pop("state", "ready" if owner == "you" else "waiting")
    return ledger.open_loop(store, pid, NOW - timedelta(days=days), title, kind, owner=owner, state=state, fact=fact,
                            ref=ref, refs=[ref] if ref else [], **kw)


def answer(**parts):
    base = {"merge": [], "split": [], "priority": [], "stale": [], "quiet": [], "now": None, "skills": [], "digest": ""}
    return {**base, **parts}


def facts(store, lid):
    return [e["fact"] for e in ledger.events(store, lid)]


def task_status(store, tid):
    return store.one("select status from tasks where id=?", (tid,))["status"]


def odies_reminder(store, lid, kind="loop"):
    tid = store.add_task("Check it", "reminder", due_at="2026-11-21T10:00:00+05:30", source_kind=kind,
                         source_ref=f"loop:{lid}", origin="agent")
    ledger.add_refs(store, lid, NOW, [f"task:{tid}"])
    return tid


# --- M6 / R1: no merge chains ---

def test_R1_a_loop_that_absorbed_another_is_never_merged_again_within_a_week(store):
    a = loop(store, "Deck for Asha", fact="A-evidence", ref="mail:a")
    b = loop(store, "Asha call", fact="B-evidence", ref="mail:b")
    c = loop(store, "Asha venue", fact="C-evidence", ref="mail:c")
    review.apply(store, "", NOW, answer(merge=[{"loops": [b, c]}]))
    later = review.apply(store, "", NOW + timedelta(days=1), answer(merge=[{"loops": [a, b]}]))
    assert later.changes == [] and "merged" in later.refused[0]
    ledger.reopen(store, c, NOW + timedelta(days=2))
    assert "C-evidence" in facts(store, c) and "C-evidence" not in facts(store, b)
    assert "A-evidence" in facts(store, a)


# --- M1 / R2: unmerge restores only what the merge changed ---

def test_R2_unmerge_leaves_the_kept_loop_as_it_moved_on(store):
    keep = loop(store, "Reply to Asha", fact="Asha asks", ref="mail:a")
    gone = loop(store, "Asha's deck", fact="deck", ref="mail:b")
    review.apply(store, "", NOW, answer(merge=[{"loops": [keep, gone]}]))
    ledger.update(store, keep, NOW + timedelta(days=1), state="waiting", owner="them",
                  due_at="2026-11-25T10:00:00+05:30")
    ledger.reopen(store, gone, NOW + timedelta(days=2))
    k = ledger.get(store, keep)
    assert (k["state"], k["owner"], k["due_at"]) == ("waiting", "them", "2026-11-25T10:00:00+05:30")


def test_unmerge_undoes_a_change_the_merge_made_when_nothing_moved_since(store):
    keep = loop(store, "Reply to Asha", fact="Asha asks", ref="mail:a")
    gone = loop(store, "Asha's call", kind="meeting", fact="call", ref="event:e", due_at="2026-11-20T15:00:00+05:30")
    ledger.merge(store, keep, gone, NOW, "same")
    assert ledger.get(store, keep)["due_at"] == "2026-11-20T15:00:00+05:30"
    ledger.unmerge(store, gone, NOW + timedelta(hours=1))
    assert ledger.get(store, keep)["due_at"] is None


# --- M2, M3 / R3, R3b: two bills or two people never become one ---

def test_R3_the_kept_loop_takes_the_amount_so_a_second_bill_is_refused(store):
    reminder = loop(store, "Pay electricity", kind="bill", fact="reminder from chat")
    oct_bill = loop(store, "Electricity bill Oct", kind="bill", fact="Oct", card={"amount": {"value": 2100, "currency": "INR"}})
    nov_bill = loop(store, "Electricity bill Nov", kind="bill", fact="Nov", card={"amount": {"value": 1900, "currency": "INR"}})
    review.apply(store, "", NOW, answer(merge=[{"loops": [reminder, oct_bill]}]))
    assert ledger.get(store, reminder)["card"]["amount"] == {"value": 2100, "currency": "INR"}
    second = review.apply(store, "", NOW + timedelta(days=1), answer(merge=[{"loops": [reminder, nov_bill]}]))
    assert second.changes == [] and ledger.get(store, nov_bill)["state"] in ledger.OPEN
    ledger.reopen(store, oct_bill, NOW + timedelta(days=2))
    assert "amount" not in ledger.get(store, reminder)["card"]  # unmerge takes the amount back


def test_R3b_two_different_senders_are_never_merged(store):
    a = loop(store, "Reply to Asha", card={"sender": "asha@x.example"})
    r = loop(store, "Reply to Ravi", card={"sender": "ravi@y.example"})
    done = review.apply(store, "", NOW, answer(merge=[{"loops": [a, r]}]))
    assert done.changes == [] and ledger.get(store, r)["state"] in ledger.OPEN
    assert "senders" in done.refused[0]


# --- M4 / R4: no address of any kind in the digest's words ---

@pytest.mark.parametrize("text", ["Verify your bank at secure-hdfc-login.com today", "Write to help@evil-pay.com now",
                                  "Visit bit.ly slash x", "Open paypa1.co.in", "Go to evil.example/login"])
def test_R4_the_digest_refuses_bare_domains_and_addresses(text):
    assert digest.checked_text(text) is None


def test_plain_digest_words_still_pass():
    assert digest.checked_text("Asha's deck is due at 3. The gas bill (₹820) is due tomorrow.") is not None


# --- H2 / R5: stale only for what is really stale; a drop's ticked reminder comes back on Undo or Reopen ---

def test_R5_a_fresh_waiting_loop_is_never_dropped_as_stale(store):
    due_ahead = loop(store, "Refund from airline", kind="refund", owner="them", days=40, fact="Refund in 3 days",
                     due_at="2026-11-21T10:00:00+05:30")
    recent = loop(store, "Order: lamp", kind="order", owner="them", days=5, fact="Shipped")
    tid = odies_reminder(store, due_ahead)
    done = review.apply(store, "", NOW, answer(stale=[{"loop": due_ahead}, {"loop": recent}]))
    assert done.changes == [] and len(done.refused) == 2
    assert ledger.get(store, due_ahead)["state"] in ledger.OPEN and ledger.get(store, recent)["state"] in ledger.OPEN
    assert task_status(store, tid) == "open"


def test_R5_undo_of_a_stale_drop_reopens_odies_reminder(store):
    lid = loop(store, "Order: old lamp", kind="order", owner="them", days=40, fact="Shipped")
    tid = odies_reminder(store, lid)
    [change] = review.apply(store, "", NOW, answer(stale=[{"loop": lid, "why": "no word in 6 weeks"}])).changes
    assert task_status(store, tid) == "done" and change["undo"]["tasks"] == [tid]
    assert review.undo(store, "", change["id"], NOW + timedelta(minutes=5))
    assert ledger.get(store, lid)["state"] == "waiting" and task_status(store, tid) == "open"


def test_R5_reopen_of_a_stale_drop_reopens_odies_reminder_too(store):
    lid = loop(store, "Order: old lamp", kind="order", owner="them", days=40, fact="Shipped")
    tid = odies_reminder(store, lid)
    review.apply(store, "", NOW, answer(stale=[{"loop": lid}]))
    ledger.reopen(store, lid, NOW + timedelta(minutes=5))
    assert task_status(store, tid) == "open"


# --- M5 / R6: Forget never ticks his own reminders ---

def test_R6_forget_leaves_a_reminder_he_asked_for_in_chat(store):
    lid = loop(store, "Pay the plumber", kind="bill")
    his = odies_reminder(store, lid, kind="ref")
    odies = odies_reminder(store, lid, kind="loop")
    ledger.forget(store, lid)
    assert task_status(store, his) == "open" and task_status(store, odies) == "done"


# --- L1 / R7: Undo of a split never deletes his Done ---

def test_R7_undo_of_a_split_after_his_done_is_refused(store):
    lid = loop(store, "Two bills", kind="bill", fact="Gas bill ₹900")
    ledger.add_event(store, lid, NOW, "mail", "mail:w", "Water bill ₹300")
    ledger.add_event(store, lid, NOW, "mail", "mail:g2", "Gas reminder")
    water = [e["id"] for e in ledger.events(store, lid) if "Water" in e["fact"]]
    [change] = review.apply(store, "", NOW, answer(split=[{"loop": lid, "evidence": [f"e{water[0]}"],
                                                         "title": "Water bill"}])).changes
    new_id = change["undo"]["loop"]
    ledger.done(store, new_id, NOW + timedelta(minutes=1))
    assert review.undo(store, "", change["id"], NOW + timedelta(minutes=2)) is False
    assert ledger.get(store, new_id)["closed_by"] == "you"


# --- L2 / R8: a Quiet proposal names a kind on his loops ---

def test_R8_a_quiet_proposal_kind_must_be_on_his_open_loops(store):
    loop(store, "Acme weekly", kind="newsletter", card={"sender": "news@acme.example"})
    review.apply(store, "", NOW, answer(quiet=[{"kind": "go to evil-site.com now", "why": "x"}]))
    assert quiet.proposal_cards(store, "") == []
    review.apply(store, "", NOW, answer(quiet=[{"kind": "Newsletter", "why": "put off 5 times"}]))
    assert len(quiet.proposal_cards(store, "")) == 1


# --- L3 / R9: a push held after the digest is said in the next one ---

def test_R9_a_push_held_after_last_nights_digest_is_said_tonight(store):
    from odie.watch import pushes
    store.set_setting(pushes.HELD, [{"at": (NOW + timedelta(hours=1)).isoformat(), "title": "Late push", "owner": ""},
                                    {"at": (NOW + timedelta(days=2)).isoformat(), "title": "Not yet", "owner": ""}])
    assert digest.held_today(store, "", NOW + timedelta(days=1)) == ["Late push"]


# --- H1 / R10, R11: learning counts only cards he left untouched ---

def test_R10_the_reviews_stale_drops_never_teach_learning(store):
    for i in range(5):
        lid = ledger.open_loop(store, "", NOW - timedelta(days=10), f"Reply to person {i}", "reply owed", owner="you",
                               state="ready", fact="mail")
        ledger.close(store, lid, NOW - timedelta(days=1), "odie", "Evening review: stale: old", state="dropped")
    assert learn.learn(store, "", NOW) == []
    boss = ledger.open_loop(store, "", NOW, "Reply to your boss", "reply owed", owner="you", state="ready", fact="mail")
    assert not quiet.digest_only(store, ledger.get(store, boss))


def test_R11_a_card_he_acted_on_outside_odie_is_not_ignored(store):
    lid = ledger.open_loop(store, "", NOW - timedelta(days=10), "Send the deck to Asha", "reply owed", owner="you",
                           state="ready", fact="mail")
    ledger.update(store, lid, NOW - timedelta(days=8), state="waiting", owner="them")
    assert learn.outcome(store, ledger.get(store, lid), NOW) is None


def test_the_ladders_day_14_drop_still_counts_as_ignored(store):
    from odie.loops import ladder
    lid = ledger.open_loop(store, "", NOW - timedelta(days=15), "Old card", "promo", owner="you", state="ready")
    ladder.run(store, NOW)
    assert ledger.get(store, lid)["state"] == "dropped"
    assert learn.outcome(store, ledger.get(store, lid), NOW) == "ignored"
