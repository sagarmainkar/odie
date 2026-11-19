"""Phase 3's data-safety pass (19 Nov 2026, from the independent review of the upgrade and stage 2). Each test is one
of the reviewer's experiments turned round to assert the right outcome:
  C1  the upgrade never folds different reminders into one loop: one open reminder = one loop; a closed one joins only
      by the same mail or event, or the same title with the same due time; the vote re-made by the old bug stays done
  C2  the upgrade is one transaction, and a second run still applies Done and Later
  C3  two findings about one mail that ask different things stay two
  I1  a finished loop is matched by its mail, event or pull request, never by a mail thread
  I2  a loop Odie closed is shown to stage 2; the same event again attaches quietly
  I3  "new" over a finished loop counts only when it names that loop
  I4  a reminder he made in chat with a source is in stage 2's view
  I5  a moved event moves the loop's open reminder; it makes a new one only when none is open
  I6  the upgrade doesn't make every "waiting on them" loop nudge at the first tick
  I7  before a rollback, the old code shows nothing twice and nothing he closed
  I8  Done is remembered for 30 days after the close, or until the thing's due time, whichever is later"""
import json
import sqlite3
from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from odie.loops import consolidate, findings, ladder, ledger, migrate
from odie.store.db import Store
from odie.watch import needs
from odie.watch.fetch import Mail

TZ = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 11, 19, 12, 0, tzinfo=TZ)


@pytest.fixture
def store(isolated_settings, tmp_path):
    s = Store(tmp_path / "a.db")
    s.init_schema()
    return s


def utc(days_ago: float = 0.0) -> str:
    at = (NOW - timedelta(days=days_ago)).astimezone(ZoneInfo("UTC"))
    return at.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def task(store, title, source_ref, status="open", due=None, created=1.0, closed=None, source_kind="ref", notes=None,
         kind="reminder"):
    tid = store.add_task(title, kind, due_at=due, source_kind=source_kind, source_ref=source_ref, origin="agent",
                         notes=notes)
    fields = {"created_at": utc(created)}
    if status != "open":
        fields["status"] = status
        fields["completed_at"] = utc(closed if closed is not None else created / 2)
    store.execute("update tasks set " + ", ".join(f"{k}=?" for k in fields) + " where id=?", (*fields.values(), tid))
    return tid


def loops(store):
    return [ledger.get(store, r["id"]) for r in store.query("select id from loops order by id")]


def holding(store, ref):
    return [lp for lp in loops(store) if ref in lp["refs"]]


def finding(ref, title, refs=None, remind=None, done="", push=False, due=None):
    return {"id": "F1", "ref": ref, "title": title, "kind": "bill", "why": "", "owner": "you", "due": due,
            "remind_at": remind, "done": done, "stage": "", "push": push, "refs": refs or [ref], "card": {},
            "from_github": False}


# ── C1: one open reminder = one loop ──

def test_two_open_reminders_with_one_title_are_two_loops_and_last_months_bill_doesnt_join(store):
    a = task(store, "Pay credit card bill", "mail:card-a-nov", due="2026-11-22T09:00+05:30", created=3)
    b = task(store, "Pay credit card bill", "mail:card-b-nov", due="2026-11-28T09:00+05:30", created=1)
    task(store, "Pay electricity bill", "mail:elec-oct", status="done", due="2026-10-30T09:00+05:30", created=25,
         closed=20)
    d = task(store, "Pay electricity bill", "mail:elec-nov", due="2026-11-29T09:00+05:30", created=1)
    migrate.run(store, NOW)
    assert ledger.pointing_at(store, a)["id"] != ledger.pointing_at(store, b)["id"]
    assert ledger.pointing_at(store, d)["state"] == "ready"  # November's bill stays open
    ledger.done(store, ledger.pointing_at(store, b)["id"], NOW)
    assert store.one("select status from tasks where id=?", (a,))["status"] == "open"  # Done on one closes one


def test_one_digest_or_one_mail_never_makes_different_things_one(store):
    digest = "Inbox/Digest 2026-11-19.md"
    task(store, "Vote: Northwind postal ballot closes 21 Nov", digest, status="done", due="2026-11-21T09:00+05:30",
         created=0.5, closed=0.2)
    insurance = task(store, "Renew car insurance by 30 Nov", digest, due="2026-11-29T09:00+05:30", created=0.5)
    ptm = task(store, "School PTM Saturday 10:00", "mail:school1", due="2026-11-22T09:00+05:30", created=2)
    fee = task(store, "Pay school term fee by 5 Dec", "mail:school1", due="2026-12-04T09:00+05:30", created=2)
    migrate.run(store, NOW)
    ins = ledger.pointing_at(store, insurance)
    assert ins["state"] == "ready" and ins["title"] == "Renew car insurance by 30 Nov"
    assert "Vote" not in " ".join(e["fact"] for e in ledger.events(store, ins["id"]))
    assert ledger.pointing_at(store, ptm)["id"] != ledger.pointing_at(store, fee)["id"]
    titles = [c["title"] for c in needs.cards(store, NOW, "")]
    assert "School PTM Saturday 10:00" in titles and "Pay school term fee by 5 Dec" in titles


VOTE = "Vote: Northwind postal ballot — e-voting closes 21 Nov"
DUE = "2026-11-20T08:30+05:30"


def eleven_vote_reminders(store) -> int:
    """The live shape, made up: eleven reminders for one vote, one due time; ten ticked by him; the open one re-made by
    the old watch 83 minutes after he ticked the previous one with the same event. Returns the open one's id."""
    rows = [("event:uid-vote", VOTE, 0.90, 0.88), ("Inbox/Digest 2026-11-17.md", VOTE, 0.85, 0.84),
            ("Heads-up: Northwind ballot", "Heads-up: Northwind ballot", 0.80, 0.79),
            ("Inbox/Digest 2026-11-18.md", VOTE, 0.70, 0.69), ("event:uid-vote", VOTE, 0.60, 0.59),
            ("note:Finance/Ballots.md", VOTE, 0.50, 0.49), ("calendar: Northwind e-voting window", VOTE, 0.45, 0.44),
            ("Inbox/Digest 2026-11-19.md", VOTE, 0.40, 0.39),
            ("Heads-up: e-voting closes Friday", "Heads-up: e-voting closes Friday", 0.30, 0.29),
            ("event:uid-vote", VOTE, 0.20, 0.10)]
    for ref, title, made, ticked in rows:
        task(store, title, ref, status="done", due=DUE, created=made, closed=ticked)
    remade = 0.10 - 83 / (24 * 60)  # 83 minutes after he ticked the last one
    return task(store, VOTE, "event:uid-vote", due=DUE, created=remade)


def test_the_vote_re_made_by_the_old_bug_stays_done(store):
    open_one = eleven_vote_reminders(store)
    lines = migrate.run(store, NOW)
    vote = ledger.pointing_at(store, open_one)
    assert vote["state"] == "closed" and vote["closed_by"] == "you" and "event:uid-vote" in vote["refs"]
    assert store.one("select status from tasks where id=?", (open_one,))["status"] == "done"
    assert any(f"tick reminder #{open_one}, re-made after you finished it" in line for line in lines)
    assert [lp for lp in loops(store) if lp["state"] in ledger.OPEN] == []
    assert needs.cards(store, NOW, "") == []


def test_next_months_reminder_and_a_heads_up_only_sibling_stay_open(store):
    task(store, "Pay rent", "mail:rent-oct", status="done", due="2026-10-25T09:00+05:30", created=30, closed=26)
    rent = task(store, "Pay rent", "mail:rent-nov", due="2026-11-25T09:00+05:30", created=1)
    task(store, "Heads-up: dentist", "event:den1", status="done", due="2026-11-21T09:00+05:30", created=2, closed=1.5)
    dentist = task(store, "Dentist Saturday", "event:den1", due="2026-11-21T09:00+05:30", created=1)
    migrate.run(store, NOW)
    assert ledger.pointing_at(store, rent)["state"] == "ready"
    assert ledger.pointing_at(store, dentist)["state"] == "ready"
    assert store.one("select status from tasks where id=?", (dentist,))["status"] == "open"


def test_the_vote_thread_and_its_reminder_loop_are_one_when_both_are_closed(store):
    task(store, "Vote: Northwind postal ballot", "mail:v1", status="done", source_kind="watch",
         notes='Closed by the user: done\nKept for a reopen: {"thread": "tv", "kind": "deadline"}', kind="reminder",
         created=2, closed=1)
    task(store, VOTE, "event:uid-vote", status="done", due=DUE, created=0.9, closed=0.5)
    migrate.run(store, NOW)
    assert len(loops(store)) == 1 and loops(store)[0]["closed_by"] == "you"


# ── C2: one transaction; a second run still applies Done and Later ──

def test_a_crash_midway_leaves_nothing_and_the_next_start_finishes_it(store, monkeypatch):
    later = (NOW + timedelta(hours=21)).isoformat(timespec="seconds")
    store.set_setting("watch.card", {"needs_you": [
        {"ref": "mail:x9", "title": "Sign the lease", "why": "by Friday", "pile": "alerts", "done": True,
         "at": (NOW - timedelta(days=2)).isoformat(timespec="seconds")},
        {"ref": "event:e5", "title": "Dentist moved", "why": "moved", "pile": "events", "done": False,
         "hidden_until": later, "at": NOW.isoformat()}]})
    real = ledger.update

    def crash(store_, lid, now, **fields):
        if "result" in fields:
            raise RuntimeError("killed midway")
        return real(store_, lid, now, **fields)
    monkeypatch.setattr(migrate.ledger, "update", crash)
    assert migrate.run_once(store, NOW) is None
    assert loops(store) == [] and store.get_setting(migrate.KEY) is None  # rolled back, version not written
    monkeypatch.setattr(migrate.ledger, "update", real)
    migrate.run_once(store, NOW)
    assert holding(store, "mail:x9")[0]["closed_by"] == "you"
    assert holding(store, "event:e5")[0]["hidden_until"] == later


def test_a_second_run_applies_done_and_later_to_what_the_first_made(store):
    store.set_setting("watch.card", {"needs_you": [
        {"ref": "mail:x9", "title": "Sign the lease", "why": "by Friday", "pile": "alerts", "done": False,
         "at": NOW.isoformat()}]})
    migrate.run(store, NOW)
    card = store.get_setting("watch.card")
    card["needs_you"][0]["done"] = True
    store.set_setting("watch.card", card)
    migrate.run(store, NOW)
    assert holding(store, "mail:x9")[0]["closed_by"] == "you"


def test_the_upgrade_makes_times_zone_aware(store):
    store.set_setting("watch.card", {"needs_you": [
        {"ref": "mail:z1", "title": "Odd", "why": "", "pile": "alerts", "done": False, "at": "2026-11-19T10:00:00",
         "hidden_until": "2026-11-20T09:00:00", "due": "2026-11-21"}]})
    migrate.run(store, NOW)
    loop = holding(store, "mail:z1")[0]
    assert loop["hidden_until"] == "2026-11-20T09:00:00+05:30" and loop["due_at"].endswith("+05:30")
    needs.cards(store, NOW, "")
    ladder.run(store, NOW)


# ── I7: before a rollback ──

def test_before_a_rollback_the_old_code_sees_nothing_twice_and_nothing_he_closed(store):
    task(store, "Pay the school fee", "event:uid9", due="2026-11-28T09:00+05:30", created=1)
    store.set_setting("watch.card", {"needs_you": [
        {"ref": "mail:z1", "title": "Sign the lease", "why": "by Friday", "pile": "alerts", "at": NOW.isoformat(),
         "done": False}]})
    pr = ledger.open_loop(store, "", NOW, "app #46", "pull request", refs=["example/app#46"], playbook="github-pr",
                          state="ready")
    migrate.run(store, NOW)
    ledger.done(store, holding(store, "mail:z1")[0]["id"], NOW)
    lines = migrate.before_rollback(store, NOW)
    assert lines
    open_now = [lp for lp in loops(store) if lp["state"] in ledger.OPEN]
    assert [lp["id"] for lp in open_now] == [pr]  # only what the old code knew (a pull request) stays open
    assert store.get_setting("watch.card")["needs_you"][0]["done"] is True


def test_the_cli_can_dry_run_the_rollback_step(store, capsys):
    task(store, "Pay the school fee", "event:uid9", due="2026-11-28T09:00+05:30", created=1)
    migrate.run(store, NOW)
    path = store.path
    store.close()
    assert migrate.main(["--before-rollback", "--dry-run", "--db", str(path), "--now", NOW.isoformat()]) == 0
    assert "would" in capsys.readouterr().out
    assert sqlite3.connect(path).execute("select count(*) from loops where state='new' or state='ready'").fetchone()[0]


# ── C3: two findings about one mail ──

def test_a_mail_asking_two_things_gives_two_findings(isolated_settings):
    m = Mail(id="school1", frm="School <office@school.example>", subject="PTM on Saturday; term fee due 5 Dec",
             at="2026-11-19T03:00:00Z", snippet="", attachments=[], source="gmail", thread="ts")
    check = SimpleNamespace(fetcher=SimpleNamespace(read_mail=lambda i: m if i == "school1" else None, statuses={}),
                            sent=[], events=[], ahead=[], threads_found=[], report={"findings": [
                                {"ref": "mail:school1", "title": "School PTM Saturday 10:00", "owner": "you"},
                                {"ref": "mail:school1", "title": "Pay school term fee by 5 Dec", "owner": "you",
                                 "due": "2026-12-05"}]})
    assert [f["title"] for f in findings.collect(check)] == ["School PTM Saturday 10:00", "Pay school term fee by 5 Dec"]


async def test_a_ref_two_loops_hold_is_the_models_and_unanswered_becomes_new(store):
    a = ledger.open_loop(store, "", NOW, "School PTM", "event", owner="you", refs=["mail:school1"], state="ready")
    b = ledger.open_loop(store, "", NOW, "School fee", "bill", owner="you", refs=["mail:school1"], state="ready")
    got = consolidate.apply(store, "", NOW, [finding("mail:school1", "School: reminder")], {},
                            consolidate.hints(store, "", [finding("mail:school1", "x")], NOW))
    assert got.opened and a not in got.changed and b not in got.changed


# ── I1 / I2 / I3 ──

def test_a_finished_bill_isnt_matched_by_its_mail_thread(store):
    lid = ledger.open_loop(store, "", NOW - timedelta(days=30), "Pay electricity bill (Oct)", "bill", owner="you",
                           refs=["mail:oct", "thread:T"], state="ready")
    ledger.done(store, lid, NOW - timedelta(days=25))
    nov = finding("mail:nov", "Pay electricity bill (Nov)", refs=["mail:nov", "thread:T"], remind="2026-11-28T09:00")
    got = consolidate.apply(store, "", NOW, [nov], {}, consolidate.hints(store, "", [nov], NOW))
    assert len(got.opened) == 1 and got.reminders == 1


def test_a_loop_odie_closed_is_shown_and_the_same_event_attaches_quietly(store):
    lid = ledger.open_loop(store, "", NOW - timedelta(days=20), "Dentist 12 Dec", "event", owner="you",
                           refs=["event:uid7"], state="ready", due_at="2026-12-12T10:00+05:30")
    ledger.close(store, lid, NOW - timedelta(days=5), "odie", "No move in 14 days: dropped", state="dropped")
    again = finding("event:uid7", "Dentist 12 Dec", remind="2026-12-11T09:00")
    prompt = consolidate.prompt_for(store, "", NOW, [again], consolidate.hints(store, "", [again], NOW), {})
    assert "Dentist 12 Dec" in prompt and f"Odie closed #{lid}" in prompt
    got = consolidate.apply(store, "", NOW, [again], {}, consolidate.hints(store, "", [again], NOW))
    assert got.opened == [] and got.quiet == [lid] and got.reminders == 0


def test_new_over_a_finished_loop_counts_only_naming_that_loop(store):
    vote = ledger.open_loop(store, "", NOW - timedelta(days=1), "Vote", "reminder", owner="you", refs=["event:uid1"],
                            state="ready")
    ledger.done(store, vote, NOW - timedelta(hours=5))
    other = ledger.open_loop(store, "", NOW - timedelta(days=3), "Order lamp", "order", owner="them",
                             refs=["mail:o1"], state="waiting")
    ledger.close(store, other, NOW - timedelta(days=1), "odie", "delivered")
    f = finding("event:uid1", "Vote", remind="2026-11-21T09:00", push=True)
    got = consolidate.apply(store, "", NOW, [f], {"F1": {"is": "new", "after": other, "why": "x"}},
                            consolidate.hints(store, "", [f], NOW))
    assert got.opened == [] and got.quiet == [vote]


# ── I4 / I5 ──

def test_his_chat_reminder_with_a_source_is_in_stage_twos_view(store):
    own = task(store, "Pay the gas bill", "mail:b1", due="2026-11-25T09:00+05:30", created=0.1)
    assert own in [r["id"] for r in consolidate.his_tasks(store, "")]


def test_a_moved_event_moves_the_open_reminder_and_makes_none_new(store):
    t1 = task(store, "Vote: ballot closes 21 Nov", "event:uid1", due="2026-11-21T09:00+05:30", created=0.5)
    migrate.run(store, NOW)
    lid = ledger.pointing_at(store, t1)["id"]
    f = finding("event:uid1", "Vote: ballot closes 22 Nov", remind="2026-11-22T09:00+05:30")
    got = consolidate.apply(store, "", NOW, [f], {"F1": {"is": "same", "loop": lid}},
                            consolidate.hints(store, "", [f], NOW))
    assert got.reminders == 0 and store.one("select due_at from tasks where id=?", (t1,))["due_at"] == "2026-11-22T09:00+05:30"


# ── I6 ──

def test_the_upgrade_doesnt_make_every_waiting_loop_nudge_at_once(store):
    task(store, "Order: desk lamp", "mail:o1", source_kind="watch", kind="waiting", created=10,
         notes=json.dumps({"thread": "t3", "kind": "order", "due": None}))
    migrate.run(store, NOW)
    assert ladder.run(store, NOW + timedelta(minutes=5)) == []


# ── I8 ──

def test_done_is_remembered_thirty_days_or_until_its_due_time(store):
    long_ago = ledger.open_loop(store, "", NOW - timedelta(days=60), "Concert", "event", owner="you",
                                refs=["event:c1"], state="ready", due_at="2026-12-20T19:00+05:30")
    ledger.done(store, long_ago, NOW - timedelta(days=40))
    assert ledger.find_done_by_user(store, "", ["event:c1"], NOW)["id"] == long_ago  # its day is still ahead
    birthday = ledger.open_loop(store, "", NOW - timedelta(days=400), "Asha's birthday", "event", owner="you",
                                refs=["event:bday"], state="ready", due_at="2025-11-20T09:00+05:30")
    ledger.done(store, birthday, NOW - timedelta(days=360))
    assert ledger.find_done_by_user(store, "", ["event:bday"], NOW) is None  # a year on: shows again
    assert ledger.remembered(ledger.get(store, birthday), NOW) is False
