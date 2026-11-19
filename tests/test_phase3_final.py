"""Phase 3's fourth pass (19 Nov 2026, from the final check). Each test is one of the reviewer's probes asserting the
safe outcome: the upgrade never changes whether a thing is open (but for the re-made reminder) and never folds two
open things into one loop; a calendar update can't be steered by a decoy id; a note is granted only as a path he
wrote; every model change to a loop's reminder needs his tap and is checked before anything is written; findings
about two bills in one mail stay two; an old mail found by a search is never a strong ID; a rollback round trip leaves
open what was open; the toolsets pass the calendar app's own instructions on and declare each tool once."""
import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from odie.loops import consolidate, findings, ledger, migrate
from odie.store.db import Store
from odie.watch import check, needs
from odie.watch.fetch import Mail
from tests.test_phase3_data_safety import loops, task

TZ = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 11, 19, 12, 0, tzinfo=TZ)


@pytest.fixture
def store(isolated_settings, tmp_path):
    s = Store(tmp_path / "a.db")
    s.init_schema()
    return s


def ctx(sid):
    return SimpleNamespace(session=SimpleNamespace(id=sid), state={})


# ── 1. the upgrade ──

def test_a_ticked_card_item_never_closes_an_open_thread_on_the_same_mail(store):
    kept = json.dumps({"thread": "tS", "kind": "bill"})
    fee = task(store, "Pay term fee Rs 12,000", "mail:school1", source_kind="watch", kind="followup", notes=kept,
               created=2, due="2026-11-30T09:00+05:30")
    store.set_setting("watch.card", {"needs_you": [
        {"ref": "mail:school1", "title": "PTM on Saturday", "done": True, "at": (NOW - timedelta(days=2)).isoformat()}]})
    migrate.run(store, NOW)
    assert store.one("select status from tasks where id=?", (fee,))["status"] == "open"
    assert ledger.pointing_at(store, fee)["state"] in ledger.OPEN
    ptm = [lp for lp in loops(store) if lp["title"] == "PTM on Saturday"]
    assert len(ptm) == 1 and ptm[0]["state"] == "closed"


def test_an_open_card_item_never_hides_in_a_closed_loop_on_the_same_mail(store):
    kept = json.dumps({"thread": "tS", "kind": "bill"})
    task(store, "Pay term fee Rs 12,000", "mail:school1", status="done", source_kind="watch", kind="followup",
         notes="Closed by the user: paid\nKept for a reopen: " + kept, created=4, closed=2)
    store.set_setting("watch.card", {"needs_you": [
        {"ref": "mail:school1", "title": "PTM on Saturday", "done": False, "pile": "alerts",
         "at": (NOW - timedelta(days=1)).isoformat()}]})
    migrate.run(store, NOW)
    assert "PTM on Saturday" in [c["title"] for c in needs.cards(store, NOW)]


def test_no_due_on_either_side_is_not_the_same_due(store):
    task(store, "Renew the parking permit", "Inbox/digest.md", status="done", created=10, closed=9)
    again = task(store, "Renew the parking permit", "Inbox/digest.md", created=1)
    migrate.run(store, NOW)
    assert store.one("select status from tasks where id=?", (again,))["status"] == "open"


def test_a_digest_born_bill_he_ticked_never_ticks_a_bank_mail_born_one(store):
    task(store, "Pay credit card bill", "Inbox/digest.md", status="done", due="2026-11-22T09:00+05:30", created=3,
         closed=2)
    bank = task(store, "Pay credit card bill", "mail:bank-nov", due="2026-11-22T09:00+05:30", created=1)
    lines = migrate.run(store, NOW)
    assert store.one("select status from tasks where id=?", (bank,))["status"] == "open"
    assert not any("re-made" in line for line in lines)


def test_the_live_vote_shape_still_ends_closed_with_the_re_made_one_ticked(store):
    from tests.test_phase3_data_safety import eleven_vote_reminders
    open_one = eleven_vote_reminders(store)
    migrate.run(store, NOW)
    assert store.one("select status from tasks where id=?", (open_one,))["status"] == "done"
    assert ledger.pointing_at(store, open_one)["closed_by"] == "you"


def test_an_old_thread_and_card_item_of_a_pull_request_join_its_open_loop(store):
    pr = ledger.open_loop(store, "", NOW - timedelta(days=1), "app #46 Threads newest first", "pull request",
                          refs=["example/app#46", "thread:T1"], playbook="github-pr", state="ready",
                          result="Open · CI green")
    later = (NOW + timedelta(hours=20)).isoformat(timespec="seconds")
    ledger.update(store, pr, NOW, hidden_until=later)
    task(store, "Re-review PR #46", "mail:T1", source_kind="watch", kind="followup", created=1,
         notes=json.dumps({"thread": "T1", "kind": "reply"}))
    store.set_setting("watch.card", {"needs_you": [
        {"ref": "mail:T1", "title": "PR #46: review requested", "done": True, "at": NOW.isoformat()}]})
    migrate.run(store, NOW)
    assert len(loops(store)) == 1
    loop = ledger.get(store, pr)
    assert loop["state"] == "ready" and loop["hidden_until"] == later
    assert loop["title"] == "app #46 Threads newest first" and loop["result"] == "Open · CI green"


# ── 2. calendar writes ──

def test_a_decoy_id_cannot_steer_a_calendar_update():
    check.STAGE1.events = {"bill-ev-1"}
    try:
        update = SimpleNamespace(name="calendar_update_event")
        for args in ({"event_id": "team-meeting", "id": "bill-ev-1"}, {"eventId": "team-meeting", "event": "bill-ev-1"},
                     {"event": {"id": "team-meeting"}, "id": "bill-ev-1"},
                     {"event_id": "bill-ev-1", "calendarId": "family@group.calendar.google.com"}):
            assert check.guard(update, args, None) is not None, args
        assert check.guard(update, {"event_id": "bill-ev-1", "summary": "✓ Paid"}, None) is None
    finally:
        check.STAGE1.events = set()


def test_a_create_names_no_other_calendar_and_shares_with_nobody():
    create = SimpleNamespace(name="calendar_create_event")
    for args in ({"summary": "x", "calendarId": "family@group.calendar.google.com"}, {"summary": "x", "cc": "a@b"},
                 {"summary": "x", "to": "a@b"}, {"summary": "x", "share_with": ["a@b"]}, {"summary": "x", "shared": True}):
        assert check.guard(create, args, None) is not None, args
    mac = SimpleNamespace(name="mac_calendar_add")
    assert check.guard(mac, {"title": "x", "start": "2026-11-20T09:00", "calendar_name": "Family"}, None) is not None


# ── 3. note paths ──

def test_a_plain_word_never_grants_a_folder(tmp_path):
    vault = tmp_path / "vault"
    for folder in ("People", "Daily", "inbox"):
        (vault / folder).mkdir(parents=True)
    (vault / "People" / "Asha.md").write_text("x")
    assert check.notes_named("- Replies: tell me when people reply", vault) == set()
    assert check.notes_named("- Daily: check daily", vault) == set()
    assert check.notes_named("- x: watch inbox", vault) == set()
    assert check.notes_named('- z: "People"', vault) == {"People/"}
    assert check.notes_named("- y: see `People/Asha.md`", vault) == {"People/Asha.md"}
    assert check.notes_named("- see people/Asha.md", vault) == set()  # its case doesn't match the folder


# ── 4. the tap gate ──

def test_a_terminal_snooze_of_a_loops_reminder_is_never_written(store):
    from odie.agent import turns
    from odie.agent.tools.local import make_local_tools
    lid = ledger.open_loop(store, "", NOW, "Reply to Asha", "reply owed", owner="you", state="ready", fact="x")
    tid = consolidate.make_reminder(store, "", NOW, lid, "Reply to Asha", "2026-11-20T09:00+05:30")
    tool = next(t for t in make_local_tools(store, "Asia/Kolkata") if t.name == "task_update")
    turns.mark("term-1", turns.TERMINAL)
    try:
        said = asyncio.run(tool.func(task_id=tid, snooze_until="2026-12-30T09:00", tool_context=ctx("term-1")))
    finally:
        turns.unmark("term-1")
    assert "only you" in said.lower()
    assert store.one("select snoozed_until from tasks where id=?", (tid,))["snoozed_until"] is None


def test_any_model_change_to_a_loops_reminder_needs_the_tap(store):
    from odie.agent.tools.local import make_local_tools
    lid = ledger.open_loop(store, "", NOW, "Reply to Asha", "reply owed", owner="you", state="ready", fact="x")
    tid = consolidate.make_reminder(store, "", NOW, lid, "Reply to Asha", "2026-11-20T09:00+05:30")
    asks = next(t for t in make_local_tools(store, "Asia/Kolkata") if t.name == "task_update")._require_confirmation
    for status in ("open", "waiting", "done", "dropped"):
        assert asks(task_id=tid, status=status, tool_context=ctx("c")) is True, status
    ledger.done(store, lid, NOW)  # a closed loop's reminder too
    assert asks(task_id=tid, status="open", tool_context=ctx("c")) is True


# ── 5. findings ──

def test_two_bills_in_one_statement_stay_two(store):
    stmt = Mail(id="st1", frm="Bank <cards@bank.example>", subject="Your card statements", at="", snippet="",
                attachments=[], source="gmail", thread="tB")
    fetcher = SimpleNamespace(store=store, owner="", now=NOW, statuses={}, read_mail=lambda i: stmt if i == "st1" else None)
    chk = SimpleNamespace(fetcher=fetcher, sent=[], events=[], ahead=[], mails=[stmt], threads_found=[],
                          report={"findings": [{"ref": "mail:st1", "title": "Pay Visa card Rs 8,000 by 25 Nov",
                                                "kind": "bill", "owner": "you", "due": "2026-11-25"}]})
    chk.threads_found.append(findings.from_thread("mail:st1", "bill", "Pay Amex card Rs 21,000", "due", "2026-11-28", ""))
    assert len(findings.collect(chk)) == 2


def test_an_old_mail_found_by_a_search_is_never_a_strong_id(store):
    lid = ledger.open_loop(store, "", NOW, "Pay the card bill", "bill", owner="you", state="ready", fact="x",
                           refs=["mail:old-card"], ref="mail:old-card")
    old = Mail(id="old-card", frm="Bank <alerts@bank.example>", subject="Statement", at="", snippet="",
               attachments=[], source="gmail", thread="tH")
    fetcher = SimpleNamespace(store=store, owner="", now=NOW, statuses={},
                              read_mail=lambda i: old if i == "old-card" else None)
    chk = SimpleNamespace(fetcher=fetcher, sent=[], events=[], ahead=[], threads_found=[], mails=[],
                          report={"findings": [{"ref": "mail:old-card", "title": "Card bill", "done": "paid",
                                                "owner": "you"}]})
    found = findings.collect(chk)
    consolidate.apply(store, "", NOW, found, {}, consolidate.hints(store, "", found, NOW))
    assert ledger.get(store, lid)["state"] == "ready"


# ── 6. rollback round trips ──

def test_a_reminder_acted_on_before_the_rollback_doesnt_close_a_live_loop(store):
    lid = ledger.open_loop(store, "", NOW, "Reply to Asha", "reply owed", owner="you", state="ready", fact="x",
                           refs=["mail:a1"])
    tid = consolidate.make_reminder(store, "", NOW, lid, "Reply to Asha", "2026-11-19T09:00+05:30")
    store.update_task(tid, status="done")  # it rang and he acted on it: the loop stays open
    store.set_setting(migrate.KEY, {"version": 1})
    migrate.before_rollback(store, NOW)
    migrate.run_once(store, NOW + timedelta(hours=1))
    assert ledger.get(store, lid)["state"] in ledger.OPEN


def test_a_loop_he_reopened_stays_open_across_a_round_trip(store):
    store.set_setting("watch.card", {"needs_you": [
        {"ref": "mail:z1", "title": "Sign the lease", "done": True, "at": (NOW - timedelta(days=1)).isoformat()}]})
    migrate.run(store, NOW)
    [lease] = loops(store)
    ledger.reopen(store, lease["id"], NOW)
    migrate.before_rollback(store, NOW)
    migrate.run_once(store, NOW + timedelta(hours=1))
    assert ledger.get(store, lease["id"])["state"] in ledger.OPEN


def test_a_second_rollback_marks_the_items_of_loops_he_closed(store):
    store.set_setting("watch.card", {"needs_you": [
        {"ref": "mail:z1", "title": "Sign the lease", "done": False, "pile": "alerts", "at": NOW.isoformat()}]})
    migrate.run(store, NOW)
    [lease] = loops(store)
    migrate.before_rollback(store, NOW)
    migrate.run_once(store, NOW + timedelta(hours=1))
    assert ledger.get(store, lease["id"])["state"] == "ready" and store.get_setting(migrate.ROLLBACK) in (None, {})
    ledger.done(store, lease["id"], NOW + timedelta(hours=2))
    migrate.before_rollback(store, NOW + timedelta(hours=3))
    assert store.get_setting("watch.card")["needs_you"][0].get("done") is True


def test_before_rollback_twice_is_the_same_and_says_what_to_do(store, capsys):
    store.set_setting("watch.card", {"needs_you": [
        {"ref": "mail:z1", "title": "Sign the lease", "done": False, "pile": "alerts", "at": NOW.isoformat()}]})
    migrate.run(store, NOW)
    migrate.before_rollback(store, NOW)
    first = [(lp["state"], lp["closed_by"]) for lp in loops(store)]
    lines = migrate.before_rollback(store, NOW + timedelta(minutes=5))
    assert [(lp["state"], lp["closed_by"]) for lp in loops(store)] == first
    assert set(store.get_setting(migrate.ROLLBACK)) == {str(loops(store)[0]["id"])}
    assert "Start the older Odie now. If the newer one starts first, run this again." in lines[-1]


# ── 7. code notes ──

def test_an_odie_close_never_ticks_a_reminder_he_may_have_asked_for(store):
    his = task(store, "Pay the gas bill", "mail:g1", due="2026-11-25T09:00+05:30", created=0.1)  # 'ref', from chat
    lid = ledger.open_loop(store, "", NOW, "Gas bill", "bill", owner="you", refs=[f"task:{his}"], state="ready")
    ledger.close(store, lid, NOW, "odie", "paid: confirmation")
    assert store.one("select status from tasks where id=?", (his,))["status"] == "open"


async def test_the_toolsets_pass_on_the_apps_instructions_and_declare_each_name_once(store):
    from google.adk.tools.base_toolset import BaseToolset

    from odie.agent.free import FreedToolset, KeptToolset, declared_once

    class Tool:
        def __init__(self, name, owner):
            self.name, self.owner = name, owner

    class Inner(BaseToolset):
        async def get_tools(self, readonly_context=None):
            return [Tool("calendar_create_event", "app"), Tool("report", "app"), Tool("gmail_send", "app")]

        async def process_llm_request(self, *, tool_context, llm_request):
            llm_request.said = "the calendar app's skill text"
    wrapped = FreedToolset(KeptToolset(Inner(), check.stage1_keeps), frozenset({"calendar_create_event"}))
    request = SimpleNamespace()
    await wrapped.process_llm_request(tool_context=None, llm_request=request)
    assert request.said == "the calendar app's skill text"
    own = [Tool("report", "watch")]
    names = await declared_once(own, [wrapped], None)
    assert sorted(t.name for t in names) == ["calendar_create_event", "report"]
    assert next(t for t in names if t.name == "report").owner == "watch"


def test_the_eval_never_hands_stage_one_a_tool_of_this_mac(store):
    from odie import loops_eval
    assert loops_eval.keeps_for_eval("mac_calendar_add") is False
    assert loops_eval.keeps_for_eval("mac_mail_new") is False
    assert loops_eval.keeps_for_eval("calendar_create_event") is True
    assert Path  # (imported for the other tests)


def test_of_two_apps_naming_one_tool_the_loaded_skills_own_is_used():
    from odie.skills import app_tool
    work = SimpleNamespace(name="calendar_create_event", _odie_server="work")
    home = SimpleNamespace(name="calendar_create_event", _odie_server="home")
    by_name = {"calendar_create_event": home}  # home listed first
    by_app = {("mcp-home", "calendar_create_event"): home, ("mcp-work", "calendar_create_event"): work}
    assert app_tool(by_app, by_name, "mcp-work", "calendar_create_event") is work
    assert app_tool(by_app, by_name, "mcp-home", "calendar_create_event") is home
    assert app_tool({}, by_name, "mcp-other", "calendar_create_event") is home


def test_a_carried_reminder_that_rang_never_closes_its_loop_on_a_later_run(store):
    rent = task(store, "Pay rent", "mail:rent-nov", due="2026-11-25T09:00+05:30", created=1)
    migrate.run(store, NOW)
    lid = ledger.pointing_at(store, rent)["id"]
    store.update_task(rent, status="done")  # it rang and he acted on it; the loop stays open
    migrate.before_rollback(store, NOW)
    migrate.run_once(store, NOW + timedelta(hours=1))
    assert ledger.get(store, lid)["state"] in ledger.OPEN
