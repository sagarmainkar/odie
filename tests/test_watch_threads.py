"""The watch's own threads: orders, bills, replies owed and deadlines it tracks in the tasks table until they close."""
import json
from datetime import UTC, datetime

import pytest

from odie.store.db import Store
from odie.watch import threads

NOW = datetime(2026, 10, 22, 9, 0, tzinfo=UTC)


@pytest.fixture
def store(isolated_settings, tmp_path):
    s = Store(tmp_path / "a.db")
    s.init_schema()
    return s


def row_for(store, ref):
    return store.one("select * from tasks where source_kind = 'watch' and source_ref = ?", (ref,))


def test_track_opens_then_moves_then_closes_a_thread(store):
    said = threads.track(store, "mail:o1", "order", "Order: desk lamp", "placed", due="2026-10-24",
                         mail_thread="t1", mail_source="mail:gmail-calendar")
    assert "Tracking" in said
    row = row_for(store, "mail:o1")
    assert row["kind"] == "waiting" and row["detail"] == "placed" and row["status"] == "open"
    assert row["origin"] == "agent" and row["due_at"] is None  # an order's date never fires a reminder
    facts = json.loads(row["notes"])
    assert facts["thread"] == "t1" and facts["source"] == "mail:gmail-calendar" and facts["kind"] == "order"
    assert facts["due"].startswith("2026-10-24")
    threads.track(store, "mail:o1", "order", "Order: desk lamp", "shipped", due="2026-10-23")
    row = row_for(store, "mail:o1")
    assert row["detail"] == "shipped" and json.loads(row["notes"])["due"].startswith("2026-10-23")
    assert store.one("select count(*) n from tasks")["n"] == 1  # moved, not a second row
    threads.track(store, "mail:o1", "order", "Order: desk lamp", "done", why="delivered: mail 23 Oct")
    row = row_for(store, "mail:o1")
    assert row["status"] == "done"
    assert row["notes"].startswith("Closed by the watch: delivered: mail 23 Oct\nKept for a reopen: ")


def test_track_never_touches_the_users_own_tasks(store):
    mine = store.add_task("Call the plumber", "todo", source_kind="ref", source_ref="mail:x1", origin="user")
    said = threads.track(store, "mail:x1", "reply", "Reply: plumber", "done", why="replied")
    assert store.one("select status from tasks where id = ?", (mine,))["status"] == "open"
    assert "no open thread" in said.lower() and row_for(store, "mail:x1") is None


def test_closing_needs_a_reason(store):
    threads.track(store, "mail:r1", "reply", "Reply: workshop invite", "owed", due="2026-10-24")
    said = threads.track(store, "mail:r1", "reply", "Reply: workshop invite", "done")
    assert "why" in said.lower() and row_for(store, "mail:r1")["status"] == "open"


def test_an_unknown_kind_is_refused(store):
    said = threads.track(store, "mail:z", "party", "Something", "new")
    assert "kind" in said.lower() and row_for(store, "mail:z") is None


def test_open_threads_lists_overdue_replies(store):
    threads.track(store, "mail:r1", "reply", "Reply: workshop invite", "owed", due="2026-10-21",
                  mail_thread="t9", mail_source="mail:gmail-calendar")
    threads.track(store, "mail:o2", "order", "Order: kettle", "shipped", due="2026-10-30")
    got = {t["ref"]: t for t in threads.open_threads(store, NOW)}
    assert got["mail:r1"]["overdue"] is True and got["mail:r1"]["kind"] == "reply" and got["mail:r1"]["thread"] == "t9"
    assert got["mail:o2"]["overdue"] is False
    assert threads.open_refs(store) == {"mail:r1", "mail:o2"}
    threads.track(store, "mail:o2", "order", "Order: kettle", "done", why="delivered")
    assert threads.open_refs(store) == {"mail:r1"}


async def test_open_threads_makes_older_mail_readable(store, tmp_path):
    # A reply owed from an older check: its mail isn't in this check, but read_thread must still answer for it.
    from odie.plugins import mcp
    from odie.watch import fetch, sources
    from odie.watch.tools import Check, watch_tools
    from tests.test_watch_calls import spec_for
    mcp.write_config({"gmail-calendar": spec_for("gmailmcp", tmp_path, threads={"t9": [
        {"from": "A Person <a.person@example.com>", "date": "2026-10-20T08:00:00Z", "body": "Can you send your fee?"},
        {"from": "Me <me@example.com>", "date": "2026-10-21T08:00:00Z", "body": "My fee is attached."}]})})
    await sources.detect_and_save(store)
    threads.track(store, "mail:r1", "reply", "Reply: fee", "owed", due="2026-10-24", mail_thread="t9",
                  mail_source="mail:gmail-calendar")
    check = Check(fetch.Fetcher(store, NOW))
    tools = {t.name: t for t in watch_tools(check)}
    listed = tools["open_threads"].func()
    assert "mail:r1" in listed["result"]
    got = await tools["read_thread"].func(mail_id="r1")
    assert "My fee is attached." in got["result"]



def test_only_bills_and_deadlines_fire_a_reminder(store):
    threads.track(store, "mail:b1", "bill", "Pay card bill — ₹12,400", "due", due="2026-10-21")
    threads.track(store, "mail:r1", "reply", "Reply: fee", "owed", due="2026-10-21")
    threads.track(store, "mail:o1", "order", "Order: lamp", "shipped", due="2026-10-21")
    fired = {r["source_ref"] for r in store.due_tasks("2026-10-22T09:00+05:30")}
    assert fired == {"mail:b1"}
    assert {t["ref"]: t["overdue"] for t in threads.open_threads(store, NOW)} == {"mail:b1": True, "mail:r1": True,
                                                                                "mail:o1": True}


def test_a_moved_bill_fires_again(store):
    threads.track(store, "mail:b1", "bill", "Pay card bill", "due", due="2026-10-21")
    tid = row_for(store, "mail:b1")["id"]
    store.mark_delivered(tid)
    threads.track(store, "mail:b1", "bill", "Pay card bill", "due", due="2026-10-25")
    assert row_for(store, "mail:b1")["delivered_at"] is None


def test_closing_a_thread_takes_its_card_item_off(store):
    from odie.watch import report
    store.set_setting(report.CARD, {"needs_you": [{"ref": "mail:r1", "title": "Reply: fee", "why": "x", "done": False}]})
    threads.track(store, "mail:r1", "reply", "Reply: fee", "owed")
    threads.track(store, "mail:r1", "reply", "Reply: fee", "done", why="replied 21 Oct")
    assert store.get_setting(report.CARD)["needs_you"] == []


async def test_read_thread_and_read_mail_take_a_ref_too(store, tmp_path):
    # The instructions say "read_thread on its ref": "mail:r1" works like "r1".
    from tests.test_watch_fetch import gmail_check
    _check, tools = await gmail_check(store, tmp_path, threads={"t1": [{"from": "A", "date": "x", "body": "Hello"}]})
    assert "Hello" in (await tools["read_thread"].func(mail_id="mail:g1"))["result"]
    assert "error" not in await tools["read_mail"].func(mail_id="mail:g1")


def test_a_reopened_thread_still_knows_its_mail(store):
    """Undoing the watch's close on Today must bring the thread back whole: its mail thread and app, so the next check
    can read the thread again. The closing reason alone shows under "Done while you were away"."""
    from odie.watch import bills
    threads.track(store, "mail:o1", "order", "Order: desk lamp", "placed", due="2026-10-24",
                  mail_thread="t1", mail_source="mail:gmail-calendar")
    threads.track(store, "mail:o1", "order", "Order: desk lamp", "done", why="delivered: mail 23 Oct")
    closed = bills.closed_by_watch(store, datetime(2000, 1, 1, tzinfo=UTC))
    assert [c["why"] for c in closed] == ["delivered: mail 23 Oct"]
    bills.reopen(store, row_for(store, "mail:o1")["id"])
    row = row_for(store, "mail:o1")
    facts = json.loads(row["notes"])
    assert row["status"] == "open"
    assert facts["thread"] == "t1" and facts["source"] == "mail:gmail-calendar" and facts["kind"] == "order"
