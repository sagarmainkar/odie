"""Stage 2, Consolidate (proactive design §5): one model call places each finding of a check in the ledger. The model
matches; code keeps the rails: Done is remembered (news attaches quietly), a reminder only for a new loop, unsure ->
new, one loop per pull request. These run with a scripted model."""
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from odie.loops import consolidate, ledger
from odie.store.db import Store

NOW = datetime(2026, 11, 19, 4, 30, tzinfo=ZoneInfo("Asia/Kolkata"))


@pytest.fixture
def store(isolated_settings, tmp_path):
    s = Store(tmp_path / "a.db")
    s.init_schema()
    return s


def finding(ref, title, **kw):
    out = {"ref": ref, "title": title, "kind": kw.pop("kind", "reminder"), "why": kw.pop("why", ""),
           "owner": kw.pop("owner", "you"), "due": kw.pop("due", None), "remind_at": kw.pop("remind_at", None),
           "done": kw.pop("done", ""), "stage": "", "push": kw.pop("push", False),
           "refs": kw.pop("refs", [ref]), "card": kw.pop("card", {})}
    assert not kw
    return out


def scripted(*answers):
    """A model that answers each call with the next of `answers` (a list of answers, or a raw text)."""
    calls = []

    async def think(prompt, instruction):
        calls.append(prompt)
        got = answers[min(len(calls), len(answers)) - 1]
        if isinstance(got, str):
            return got
        return json.dumps({"answers": got})
    think.calls = calls
    return think


def reminders(store):
    return store.query("select * from tasks where source_kind='loop'")


VOTE = "Vote: Northwind postal ballot — e-voting closes 21 Nov"


async def test_the_vote_reminder_is_made_once_and_done_sticks_whatever_source_brings_it_back(store):
    # 04:30, from the calendar event: a new loop and its reminder.
    event = finding("event:uid1", VOTE, remind_at="2026-11-21T09:00+05:30", due="2026-11-21T17:00+05:30")
    got = await consolidate.consolidate(store, "", NOW, [event], scripted([{"f": "F1", "is": "new"}]), {})
    lid = got.opened[0]
    assert got.reminders == 1 and len(reminders(store)) == 1
    assert ledger.get(store, lid)["state"] == "ready" and ledger.reminder_of(ledger.get(store, lid))
    ledger.done(store, lid, NOW + timedelta(minutes=10))
    assert reminders(store)[0]["status"] == "done"  # his Done closed the reminder too
    # 06:29, the digest note his Watch for relays: another source, the same thing. The model matches it.
    digest = finding("note:Inbox/digest.md", VOTE, remind_at="2026-11-21T09:00+05:30")
    think = scripted([{"f": "F1", "is": "same", "loop": lid}])
    got = await consolidate.consolidate(store, "", NOW + timedelta(hours=2), [digest], think, {})
    assert got.opened == [] and got.reminders == 0 and got.reminder_to_finished
    assert "the user finished" not in think.calls[0].split("Findings")[1].split("Open loops")[0]  # no shared ID
    assert f"#{lid} {VOTE}" in think.calls[0] and "finished by you" in think.calls[0]
    # 09:05, the same event again; even a sloppy "new" can't bring it back (its own ID is held by the finished loop).
    again = finding("event:uid1", VOTE, remind_at="2026-11-21T09:00+05:30")
    got = await consolidate.consolidate(store, "", NOW + timedelta(hours=5), [again], scripted([{"f": "F1", "is": "new"}]), {})
    assert got.opened == [] and got.quiet == [lid]
    assert len(reminders(store)) == 1 and store.one("select count(*) n from loops")["n"] == 1
    assert ledger.get(store, lid)["state"] == "closed" and ledger.get(store, lid)["has_news"] == 0
    assert len(ledger.events(store, lid)) >= 3  # the digest and the event again kept as evidence, quietly


async def test_a_genuinely_new_ask_after_done_is_a_new_loop_that_says_so(store):
    first = await consolidate.consolidate(store, "", NOW, [finding("event:uid1", VOTE)],
                                          scripted([{"f": "F1", "is": "new"}]), {})
    old = first.opened[0]
    ledger.done(store, old, NOW)
    reopened = finding("mail:m9", "E-voting reopened: closes 28 Nov", due="2026-11-28T17:00+05:30")
    think = scripted([{"f": "F1", "is": "new", "after": old, "why": "the vote was reopened with a new deadline"}])
    got = await consolidate.consolidate(store, "", NOW + timedelta(days=1), [reopened], think, {})
    new = got.opened[0]
    assert new != old
    assert ledger.events(store, new)[0]["fact"].startswith(f"New since you finished #{old}")


async def test_no_answer_goes_by_the_shortcut_and_else_a_new_loop(store):
    lid = ledger.open_loop(store, "", NOW, "Reply to Asha: the deck", "reply owed", owner="you", refs=["thread:t1"],
                           state="ready")
    held = finding("mail:m2", "Asha: any news on the deck?", refs=["mail:m2", "thread:t1"])
    loose = finding("mail:m3", "Pay the plumber", kind="bill")
    got = await consolidate.consolidate(store, "", NOW, [held, loose], scripted([]), {})  # read, but no answers
    assert got.changed == [lid] and len(got.opened) == 1
    assert ledger.get(store, got.opened[0])["title"] == "Pay the plumber"


async def test_a_reply_owed_with_no_due_date_is_a_card(store):
    got = await consolidate.consolidate(store, "", NOW, [finding("mail:m1", "Reply to Asha", kind="reply owed")],
                                        scripted([{"f": "F1", "is": "new"}]), {})
    loop = ledger.get(store, got.opened[0])
    assert loop["state"] == "ready" and loop["due_at"] is None and loop["shown_at"]


async def test_a_call_with_the_same_person_moves_the_due_date(store):
    lid = ledger.open_loop(store, "", NOW, "Send Asha the deck", "reply owed", owner="you", refs=["mail:m1"],
                           due_at="2026-11-21T09:00+05:30", state="ready")
    call = finding("event:e7", "Call with Asha", kind="event", due="2026-11-21T15:00+05:30")
    think = scripted([{"f": "F1", "is": "same", "loop": lid, "due": "2026-11-21T15:00"}])
    got = await consolidate.consolidate(store, "", NOW, [call], think, {})
    assert got.changed == [lid] and ledger.get(store, lid)["due_at"] == "2026-11-21T15:00+05:30"
    assert "event:e7" in ledger.get(store, lid)["refs"]


async def test_closes_cites_its_evidence_and_closes_the_reminder(store):
    lid = ledger.open_loop(store, "", NOW, "Pay electricity bill — ₹4,280", "bill", owner="you", refs=["mail:b1"],
                           state="ready")
    consolidate.make_reminder(store, "", NOW, lid, "Pay electricity bill", "2026-11-25T09:00+05:30")
    paid = finding("mail:p1", "Payment of Rs 4,280 received", done="paid: confirmation mail 21 Nov")
    think = scripted([{"f": "F1", "is": "closes", "loop": lid, "why": "paid: confirmation 21 Nov"}])
    got = await consolidate.consolidate(store, "", NOW, [paid], think, {})
    loop = ledger.get(store, lid)
    assert got.closed == [lid] and loop["state"] == "closed" and loop["closed_by"] == "odie"
    assert loop["closed_why"] == "paid: confirmation 21 Nov"
    assert any(e["ref"] == "mail:p1" for e in ledger.events(store, lid))
    assert reminders(store)[0]["status"] == "done"


async def test_one_loop_per_pull_request_whatever_the_model_says(store):
    lid = ledger.open_loop(store, "", NOW, "app #49", "pull request", refs=["example/app#49"], playbook="github-pr")
    mail = finding("mail:g2", "app #49: new commits", kind="pull request", owner="odie",
                   refs=["mail:g2", "example/app#49"])
    got = await consolidate.consolidate(store, "", NOW, [mail], scripted([{"f": "F1", "is": "new"}]), {})
    assert got.opened == [] and got.changed == [lid]


async def test_a_pull_request_finding_gets_the_playbook_and_two_mails_about_it_are_one(store):
    one = finding("mail:g1", "app #50 review requested", kind="pull request", owner="you", push=True,
                  refs=["mail:g1", "example/app#50"])
    two = finding("mail:g2", "app #50 new commits", kind="pull request", owner="odie", refs=["mail:g2", "example/app#50"])
    got = await consolidate.consolidate(store, "", NOW, [one, two], scripted([]), {})
    assert len(got.opened) == 1
    loop = ledger.get(store, got.opened[0])
    assert loop["playbook"] == "github-pr" and loop["state"] == "new" and loop["owner"] == "odie"
    assert loop["priority"] == "high"


async def test_his_own_reminder_is_not_a_second_loop(store):
    tid = store.add_task("Pay rent", "reminder", due_at="2026-11-25T09:00+05:30")
    think = scripted([{"f": "F1", "is": "same", "task": tid}])
    got = await consolidate.consolidate(store, "", NOW, [finding("mail:r1", "Rent due on 25 Nov", kind="bill")], think, {})
    assert got.opened == [] and store.one("select count(*) n from loops")["n"] == 0
    assert f"task #{tid} Pay rent" in think.calls[0]


async def test_a_failed_call_leaves_the_findings_for_the_next_check(store):
    async def broken(prompt, instruction):
        raise TimeoutError("slow model")
    got = await consolidate.consolidate(store, "", NOW, [finding("mail:m1", "Reply to Asha")], broken, {})
    assert got is None and store.one("select count(*) n from loops")["n"] == 0
    think = scripted([{"f": "F1", "is": "new"}, {"f": "F2", "is": "new"}])
    got = await consolidate.consolidate(store, "", NOW + timedelta(minutes=30), [finding("mail:m2", "Pay rent")],
                                        think, {})
    titles = {ledger.get(store, lid)["title"] for lid in got.opened}
    assert titles == {"Reply to Asha", "Pay rent"}
    assert store.get_setting("loops.pending") == {}


async def test_after_three_failed_checks_the_findings_are_placed_anyway(store):
    async def broken(prompt, instruction):
        return "no json here"
    for n in range(2):
        assert await consolidate.consolidate(store, "", NOW, [finding(f"mail:m{n}", f"Thing {n}")] if n == 0 else [],
                                             broken, {}) is None
    got = await consolidate.consolidate(store, "", NOW, [], broken, {})
    assert got is not None and len(got.opened) == 1


async def test_the_prompt_fences_other_peoples_words_and_says_what_the_shortcut_knows(store):
    lid = ledger.open_loop(store, "", NOW, "Order: lamp", "order", owner="them", refs=["thread:o1"])
    think = scripted([{"f": "F1", "is": "same", "loop": lid}])
    shipped = finding("mail:o2", "Your lamp has shipped", kind="order", owner="them", refs=["mail:o2", "thread:o1"])
    await consolidate.consolidate(store, "", NOW, [shipped], think, {"watch": "- Votes: remind me", "memory": "Asha: sister"})
    prompt = think.calls[0]
    assert prompt.count("<<<UNTRUSTED") >= 4
    assert f"loop #{lid} holds thread:o1" in prompt and "- Votes: remind me" in prompt and "Asha: sister" in prompt


async def test_their_move_becomes_his_card_when_a_finding_needs_him(store):
    lid = ledger.open_loop(store, "", NOW, "Order: lamp", "order", owner="them", refs=["thread:o1"], state="waiting")
    failed = finding("mail:o3", "Delivery failed: reschedule", owner="you", push=True, refs=["mail:o3", "thread:o1"])
    got = await consolidate.consolidate(store, "", NOW, [failed], scripted([{"f": "F1", "is": "same", "loop": lid,
                                                                           "owner": "you"}]), {})
    loop = ledger.get(store, lid)
    assert loop["state"] == "ready" and loop["owner"] == "you" and got.to_push == [lid]


async def test_a_loop_number_of_another_personality_is_not_used(store):
    from odie import personalities
    mira = personalities.create(store, "Mira").id
    hers = ledger.open_loop(store, mira, NOW, "Mira's thing", "reminder", owner="you")
    got = await consolidate.consolidate(store, "", NOW, [finding("mail:m1", "Odie's thing")],
                                        scripted([{"f": "F1", "is": "same", "loop": hers}]), {})
    assert len(got.opened) == 1 and ledger.get(store, got.opened[0])["personality"] == ""
    assert len(ledger.events(store, hers)) == 0


async def test_a_pull_request_is_never_nothing_here(store):
    mail = finding("mail:g1", "app #71 checks passed", kind="pull request", owner="odie",
                   refs=["mail:g1", "example/app#71"])
    got = await consolidate.consolidate(store, "", NOW, [mail], scripted([{"f": "F1", "is": "nothing"}]), {})
    assert len(got.opened) == 1 and ledger.get(store, got.opened[0])["playbook"] == "github-pr"
