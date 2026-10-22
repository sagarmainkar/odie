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
    assert row["origin"] == "agent" and row["due_at"].startswith("2026-10-24")
    assert json.loads(row["notes"]) == {"thread": "t1", "source": "mail:gmail-calendar", "kind": "order"}
    threads.track(store, "mail:o1", "order", "Order: desk lamp", "shipped", due="2026-10-23")
    row = row_for(store, "mail:o1")
    assert row["detail"] == "shipped" and row["due_at"].startswith("2026-10-23")
    assert store.one("select count(*) n from tasks")["n"] == 1  # moved, not a second row
    threads.track(store, "mail:o1", "order", "Order: desk lamp", "done", why="delivered: mail 23 Oct")
    row = row_for(store, "mail:o1")
    assert row["status"] == "done" and row["notes"] == "Closed by the watch: delivered: mail 23 Oct"


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
