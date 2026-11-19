"""Phase 3's third pass (19 Nov 2026, from the re-review): a regression of the allow-list (stage 1 had lost its
calendar tools), stage 1's remaining ways round its rails, his Done in chat always needing his tap, two upgrade joins
that lost live bills, findings about two things in one mail, and a rollback followed by a second upgrade. Each test
asserts the right outcome of one of the reviewer's probes."""
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
from odie.watch.fetch import Event, Mail
from tests.test_phase3_data_safety import loops, task

TZ = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 11, 19, 12, 0, tzinfo=TZ)
STRANGER = Mail(id="s1", frm="Mallory <m@evil.example>", subject="Hi", at="2026-11-19T04:00:00Z", snippet="",
                attachments=[], source="gmail", thread="tEvil")


@pytest.fixture
def store(isolated_settings, tmp_path):
    s = Store(tmp_path / "a.db")
    s.init_schema()
    return s


class FakeFetcher:
    def __init__(self, store, mails):
        self.store, self.owner, self.now, self.statuses = store, "", NOW, {}
        self._m = {m.id: m for m in mails}

    def read_mail(self, mid):
        return self._m.get(mid)


def fake_check(store, mails, items, events=()):
    return SimpleNamespace(fetcher=FakeFetcher(store, mails), sent=[], events=list(events), ahead=[],
                           threads_found=[], mails=mails, report={"findings": items, "line": "", "done": []})


# ── A: stage 1 gets its calendar tools, through the runner's own path ──

async def declared(tools, state) -> set[str]:
    """The tool names a model is told about, from an agent's tool list (toolsets asked as ADK asks them)."""
    from google.adk.tools.base_toolset import BaseToolset
    ctx = SimpleNamespace(state=state, agent_name="odie_tracker", invocation_id="inv-1")
    out = set()
    for t in tools:
        if isinstance(t, BaseToolset):
            out |= {x.name for x in await t.get_tools(ctx)}
        else:
            out.add(t.name)
    return out


def a_runner(store):
    from odie.app.runner import OdieRunner
    return OdieRunner(store)


async def test_stage_one_is_handed_its_calendar_writes_and_nothing_outside_its_list(store, tmp_path):
    from odie.plugins import mcp
    from odie.skills import loaded_skills_state
    from odie.watch.sources import KEY, Source
    from odie.watch.tools import Check, watch_tools
    from tests.test_watch_calls import spec_for
    mcp.write_config({"gmail-calendar": spec_for("gmailmcp", tmp_path)})
    calendar = Source("calendar", "gmail-calendar", "Gmail and Calendar", "plain", "calendar_list_events", {})
    store.set_setting(KEY, {"sources": [calendar.as_dict()]})
    runner = a_runner(store)
    await runner.load_plugins()
    try:
        skills = check.calendar_skills(store)
        assert skills == ["mcp-gmail-calendar"]
        check.STAGE1.reset(store, "")
        fetcher = SimpleNamespace(store=store, owner="", now=NOW, statuses={})
        tools = runner.stage_tools(watch_tools(Check(fetcher)), check.MAY_WRITE, check.stage1_keeps)
        names = await declared(tools, loaded_skills_state("odie_tracker", skills))
    finally:
        await runner.close()
    assert {"calendar_create_event", "calendar_update_event", "new_mail", "report"} <= names
    allowed = check.WATCH_TOOLS | check.MAY_WRITE | check.MAYBE
    assert names <= allowed, sorted(names - allowed)  # never gmail_send, recall, make_research, …


async def test_with_no_calendar_app_stage_one_still_gets_its_own_tools(store):
    from odie.watch.tools import Check, watch_tools
    runner = a_runner(store)
    try:
        check.STAGE1.reset(store, "")
        fetcher = SimpleNamespace(store=store, owner="", now=NOW, statuses={})
        tools = runner.stage_tools(watch_tools(Check(fetcher)), check.MAY_WRITE, check.stage1_keeps)
        names = await declared(tools, {})
    finally:
        await runner.close()
    assert {"new_mail", "report", "track_thread"} <= names
    assert names <= check.WATCH_TOOLS | check.MAY_WRITE | check.MAYBE


async def test_read_note_is_handed_when_his_vault_is_odies_own_folder(store, tmp_path):
    from odie.vault import settings as vault_settings
    from odie.watch.tools import Check, watch_tools
    vault = tmp_path / "vault"
    (vault / "Inbox").mkdir(parents=True)
    vault_settings.put(store, dir=str(vault))
    runner = a_runner(store)
    try:
        fetcher = SimpleNamespace(store=store, owner="", now=NOW, statuses={})
        tools = runner.stage_tools(watch_tools(Check(fetcher)), check.MAY_WRITE, check.stage1_keeps)
        names = await declared(tools, {})
    finally:
        await runner.close()
    assert "read_note" in names


# ── B1: a finding's own ref is checked like any other ──

def test_a_finding_can_never_point_at_his_task_nor_an_unread_thread(store):
    bill = store.add_task("Pay electricity Rs 4,280", "reminder", due_at="2026-11-25T09:00:00+05:30",
                          source_kind="watch", source_ref="mail:b1", origin="agent")
    victim = ledger.open_loop(store, "", NOW, "Reply to Asha: kitchen quote", "reply owed", owner="you",
                              refs=["mail:a1", "thread:tAsha"], state="ready", fact="asked")
    found = findings.collect(fake_check(store, [STRANGER], [
        {"ref": f"task:{bill}", "title": "Weekly deals", "owner": "you"},
        {"ref": "thread:tAsha", "title": "Kitchen quote", "done": "you replied"},
        {"ref": "mail:s1", "title": "Hi", "refs": [f"task:{bill}", "thread:tAsha"]}]))
    assert [f["ref"] for f in found] == ["mail:s1"]
    assert not any(r.startswith(("task:", "thread:tAsha")) for f in found for r in f["refs"])
    consolidate.apply(store, "", NOW, found, {}, consolidate.hints(store, "", found, NOW))
    assert ledger.get(store, victim)["state"] == "ready"


def test_a_loop_never_hides_his_own_task(store):
    own = store.add_task("Renew passport", "todo", due_at="2026-11-20T09:00:00+05:30")
    ledger.open_loop(store, "", NOW, "Shipping update", "order", owner="them", refs=[f"task:{own}"], state="waiting")
    assert own not in needs.loops_reminders(store, "")
    assert f"task:{own}" in [c["ref"] for c in needs.cards(store, NOW)]


# ── B2: a pull request's name only as code reads it ──

def test_a_comment_naming_another_pr_gives_no_ref(store):
    gh = Mail(id="g1", frm="Asha <notifications@github.com>", subject="[example/app] Fix crash (PR #49)", at="",
              snippet="also closes example/app#46", attachments=[], source="gmail", thread="tGh")
    found = findings.collect(fake_check(store, [gh], [
        {"ref": "mail:g1", "title": "app #49", "kind": "pull request", "refs": ["example/app#46", "example/app#49"]}]))
    assert "example/app#49" in found[0]["refs"] and "example/app#46" not in found[0]["refs"]


# ── B3: close_reminder only for what bills_and_orders listed ──

def test_close_reminder_only_closes_a_bill_this_check_listed(store):
    from odie.watch.tools import Check, watch_tools
    own = store.add_task("Renew passport", "todo", due_at="2026-11-20T09:00:00+05:30")
    gas = store.add_task("Pay gas bill Rs 900", "reminder", due_at="2026-11-25T09:00:00+05:30")

    async def no_events(days):
        return []
    fetcher = SimpleNamespace(store=store, owner="", now=NOW, statuses={}, read_mail=lambda mid: None,
                              events_ahead=no_events)
    tools = {t.name: t for t in watch_tools(Check(fetcher))}
    ctx = SimpleNamespace(state={})

    def run(name, args):
        return asyncio.run(tools[name].run_async(args=args, tool_context=ctx))["result"]
    assert "bills_and_orders" in run("close_reminder", {"task_id": gas, "why": "paid"})  # not listed yet
    listed = json.loads(run("bills_and_orders", {}))
    assert [r["id"] for r in listed["reminders"]] == [gas]
    assert run("close_reminder", {"task_id": gas, "why": "paid: confirmation"}).startswith("Closed")
    assert "bills_and_orders" in run("close_reminder", {"task_id": own, "why": "paid"})
    assert store.one("select status from tasks where id=?", (own,))["status"] == "open"


# ── B4: calendar writes never invite anyone, never touch a meeting it didn't list ──

def test_calendar_writes_are_scanned_deep_and_updates_only_for_its_bill_events():
    ctx = SimpleNamespace(state={})
    create = SimpleNamespace(name="calendar_create_event")
    for args in ({"summary": "x", "Attendees": ["a@b"]}, {"summary": "x", "event": {"attendees": ["a@b"]}},
                 {"summary": "x", "people": ["a@b"]}, {"summary": "x", "recipients": "a@b"},
                 {"summary": "x", "add_people": "a@b"}, {"summary": "x", "conferenceData": {"x": 1}},
                 {"summary": "x", "visibility": "public"}, {"summary": "x", "sendUpdates": "all"},
                 {"summary": "x", "options": [{"guests": ["a@b"]}]}):
        assert check.guard(create, args, ctx) is not None, args
    assert check.guard(create, {"summary": "Pay bill", "start": "2026-11-25"}, ctx) is None
    update = SimpleNamespace(name="calendar_update_event")
    check.STAGE1.events = {"bill-ev-1"}
    try:
        assert check.guard(update, {"event_id": "bill-ev-1", "summary": "✓ Paid · Pay bill"}, ctx) is None
        assert check.guard(update, {"event_id": "existing-meeting", "description": "pasted mail"}, ctx) is not None
        assert check.guard(update, {"summary": "no id at all"}, ctx) is not None
    finally:
        check.STAGE1.events = set()


# ── B5: a note is named only as he wrote it ──

@pytest.fixture
def vault(tmp_path):
    root = tmp_path / "vault"
    for folder in ("2-Areas/My Money", "2-Areas/Health", "0-Inbox/iCloud", "People", "Inbox"):
        (root / folder).mkdir(parents=True, exist_ok=True)
    (root / "2-Areas/My Money/budget.md").write_text("x")
    (root / "2-Areas/Health/blood.md").write_text("x")
    (root / "0-Inbox/iCloud/2026-11-14 0013 digest.md").write_text("x")
    (root / "0-Inbox/other.md").write_text("x")
    (root / "People/Asha.md").write_text("x")
    (root / "People/Ravi.md").write_text("x")
    return root


def allowed(vault, watch, note):
    check.STAGE1.vault = vault
    check.STAGE1.notes = check.notes_named(watch, vault)
    try:
        return check.note_allowed({"note": note})
    finally:
        check.STAGE1.vault, check.STAGE1.notes = None, set()


def test_a_path_with_a_space_counts_only_quoted(vault):
    assert not allowed(vault, "- watch 2-Areas/My Money/ weekly", "2-Areas/Health/blood.md")
    assert not allowed(vault, "- watch 2-Areas/My Money/ weekly", "2-Areas/My Money/budget.md")
    assert allowed(vault, '- watch "2-Areas/My Money/" weekly', "2-Areas/My Money/budget.md")
    assert not allowed(vault, '- watch "2-Areas/My Money/" weekly', "2-Areas/Health/blood.md")


def test_a_folder_named_grants_that_folder_only(vault):
    assert allowed(vault, "- notes under 0-Inbox/iCloud", "0-Inbox/iCloud/2026-11-14 0013 digest.md")
    assert not allowed(vault, "- notes under 0-Inbox/iCloud", "0-Inbox/other.md")


def test_a_file_named_grants_that_file_only(vault):
    assert allowed(vault, "- relay `0-Inbox/iCloud/2026-11-14 0013 digest.md`",
                   "0-Inbox/iCloud/2026-11-14 0013 digest.md")
    assert not allowed(vault, "- relay 0-Inbox/iCloud/2026-11-14 0013 digest.md", "0-Inbox/other.md")
    assert allowed(vault, "- who is People/Asha.md", "People/Asha.md")
    assert not allowed(vault, "- who is People/Asha.md", "People/Ravi.md")


def test_words_that_only_look_like_paths_grant_nothing(vault):
    assert check.notes_named("- and/or 24/7 ./ Inbox", vault) == {"Inbox/"}
    assert check.notes_named("- and/or 24/7 ./", vault) == set()


# ── C: any change the model makes to a loop from chat needs his tap ──

def chat_ctx(session_id):
    return SimpleNamespace(session=SimpleNamespace(id=session_id), state={})


def test_watch_close_always_asks_for_his_tap(store):
    from odie.agent.tools.watch_items import make_watch_item_tools
    lid = ledger.open_loop(store, "", NOW, "Reply to Asha", "reply owed", owner="you", state="ready", fact="x")
    tool = next(t for t in make_watch_item_tools(store) if t.name == "watch_close")
    assert tool._require_confirmation(ref=f"loop:{lid}", why="done", tool_context=chat_ctx("clean")) is True


async def test_task_update_on_a_loops_reminder_always_asks_his_own_task_never(store):
    from odie.agent.tools.local import make_local_tools
    lid = ledger.open_loop(store, "", NOW, "Reply to Asha", "reply owed", owner="you", state="ready", fact="x")
    tid = consolidate.make_reminder(store, "", NOW, lid, "Reply to Asha", "2026-11-20T09:00+05:30")
    own = store.add_task("Call the plumber", "todo")
    tool = next(t for t in make_local_tools(store, "Asia/Kolkata") if t.name == "task_update")
    asks = tool._require_confirmation
    ctx = chat_ctx("clean")
    for args in ({"status": "done"}, {"status": "dropped"}, {"snooze_until": "2026-11-21T09:00"},
                 {"next_check": "2026-11-21T09:00"}):
        assert asks(task_id=tid, tool_context=ctx, **args) is True, args
    assert asks(task_id=tid, notes="called", tool_context=ctx) is False
    assert asks(task_id=own, status="done", tool_context=ctx) is False


# ── D: upgrade joins ──

def test_an_open_bill_never_joins_last_months_closed_loop_by_its_thread(store):
    kept = json.dumps({"thread": "tBill", "kind": "bill", "sender": "bills@power.example"})
    task(store, "Pay electricity bill (Oct)", "mail:b-oct", status="done", source_kind="watch", kind="followup",
         notes="Closed by the user: paid\nKept for a reopen: " + kept, created=12, closed=8)
    nov = task(store, "Pay electricity bill (Nov)", "mail:b-nov", source_kind="watch", kind="followup", notes=kept,
               created=1, due="2026-11-25T09:00+05:30")
    store.set_setting("watch.card", {"needs_you": [
        {"ref": "mail:gas-nov", "thread": "tBill", "title": "Gas bill Rs 900 due 28 Nov", "pile": "bills",
         "at": (NOW - timedelta(days=1)).isoformat(timespec="seconds")}]})
    migrate.run(store, NOW)
    titles = {c["title"] for c in needs.cards(store, NOW)}
    assert "Pay electricity bill (Nov)" in titles and "Gas bill Rs 900 due 28 Nov" in titles
    assert store.one("select status from tasks where id=?", (nov,))["status"] == "open"


def test_two_banks_bills_with_one_title_and_due_stay_two(store):
    task(store, "Pay credit card bill", "mail:bank-a-nov", status="done", due="2026-11-22T09:00+05:30", created=4,
         closed=2)
    b = task(store, "Pay credit card bill", "mail:bank-b-nov", due="2026-11-22T09:00+05:30", created=1)
    lines = migrate.run(store, NOW)
    assert store.one("select status from tasks where id=?", (b,))["status"] == "open"
    assert not any("re-made" in line for line in lines)
    assert ledger.pointing_at(store, b)["state"] == "ready"


def test_two_finished_things_with_a_prefix_title_stay_two(store):
    store.set_setting("watch.card", {"needs_you": [
        {"ref": "mail:e1", "title": "Pay electricity bill", "done": True,
         "at": (NOW - timedelta(days=3)).isoformat(timespec="seconds")}]})
    task(store, "Pay electricity bill for the shop", "mail:e2", status="done", created=3, closed=2.5)
    migrate.run(store, NOW)
    assert len(loops(store)) == 2


# ── E: track_thread's note and a report finding about another thing in the same mail ──

def test_a_thread_note_and_a_report_finding_about_two_things_stay_two(store):
    school = Mail(id="m9", frm="School <office@school.example>", subject="Term fee and PTM", at="", snippet="",
                  attachments=[], source="gmail", thread="tS")
    chk = fake_check(store, [school], [{"ref": "mail:m9", "title": "PTM on Saturday 10:00", "owner": "you",
                                       "due": "2026-11-22T10:00", "kind": "event"}])
    chk.threads_found.append(findings.from_thread("mail:m9", "bill", "Pay term fee Rs 12,000", "due", "2026-11-30", ""))
    assert {f["title"] for f in findings.collect(chk)} == {"PTM on Saturday 10:00", "Pay term fee Rs 12,000"}
    same = fake_check(store, [school], [{"ref": "mail:m9", "title": "Term fee due 30 Nov", "kind": "bill"}])
    same.threads_found.append(findings.from_thread("mail:m9", "bill", "Pay term fee Rs 12,000", "due", "2026-11-30", ""))
    assert len(findings.collect(same)) == 1  # the same kind: the thread's own update


# ── F: rollback, then the upgrade again ──

def test_a_rollback_then_a_second_upgrade_keeps_everything_straight(store):
    fee = task(store, "Pay the school fee", "event:uid9", due="2026-11-28T09:00+05:30", created=1)
    rent = task(store, "Pay rent", "mail:rent-nov", due="2026-11-25T09:00+05:30", created=1)
    store.set_setting("watch.card", {"needs_you": [
        {"ref": "mail:z1", "title": "Sign the lease", "why": "by Friday", "pile": "alerts", "at": NOW.isoformat(),
         "done": False}]})
    migrate.run(store, NOW)
    lease = [lp for lp in loops(store) if "mail:z1" in lp["refs"]][0]
    ledger.done(store, lease["id"], NOW)  # his Done under the new code
    migrate.before_rollback(store, NOW)
    assert store.get_setting(migrate.KEY) is None  # the next start upgrades again
    put_aside = [lp for lp in loops(store) if lp["closed_by"] == migrate.ROLLBACK_CLOSER]
    assert put_aside and all(not ledger.remembered(lp, NOW) for lp in put_aside)
    from odie.loops import cards
    assert cards.done_today(store, "", NOW) == []
    # the old code runs a while: he ticks the rent reminder; the old watch adds a card item
    store.update_task(rent, status="done")
    card = store.get_setting("watch.card")
    card["needs_you"].append({"ref": "mail:n1", "title": "New invoice", "why": "due 2 Dec", "pile": "bills",
                              "at": NOW.isoformat(), "done": False})
    store.set_setting("watch.card", card)
    later = NOW + timedelta(days=1)
    migrate.run_once(store, later)
    by_task = {t: ledger.pointing_at(store, t) for t in (fee, rent)}
    assert by_task[fee]["state"] == "ready"  # still open: back on Pulse
    assert by_task[rent]["state"] == "closed" and by_task[rent]["closed_by"] == "you"
    assert ledger.get(store, lease["id"])["closed_by"] == "you"  # his Done stays his
    new = [lp for lp in loops(store) if "mail:n1" in lp["refs"]]
    assert len(new) == 1 and new[0]["state"] == "ready"
    titles = [c["title"] for c in needs.cards(store, later)]
    assert sorted(titles) == sorted(set(titles))  # nothing twice
    assert Path and Event  # (imported for the other tests)
