"""Chat acting on a Desk card: desk_item shows an item and its drafted reply; desk_close takes it off and closes its thread."""
import pytest

from odie.store.db import Store
from odie.watch import report, threads

ITEM = {"ref": "mail:m1", "title": "Workshop invite", "why": "Asks your fee by Friday", "pile": "alerts", "done": False,
        "from": "Tom Reyes", "subject": "Quick note", "due": "2026-10-24",
        "suggestion": {"label": "Reply with your fee", "run": "Show the draft for desk item mail:m1"},
        "escape": {"label": "Not interested", "run": "Close desk item mail:m1: not interested"},
        "draft": {"to": "tom@learnhub.example.org", "subject": "Re: Quick note", "body": "Hi Tom, my fee is [fee]."}}


@pytest.fixture
def store(isolated_settings, tmp_path):
    s = Store(tmp_path / "a.db")
    s.init_schema()
    s.set_setting(report.CARD, {"needs_you": [ITEM, {**ITEM, "ref": "mail:m2", "title": "Other"}]})
    return s


def tools_for(store):
    from odie.agent.tools.desk import make_desk_tools
    return {t.name: t.func for t in make_desk_tools(store)}


def test_desk_item_shows_the_item_and_its_draft(store):
    text = tools_for(store)["desk_item"](ref="mail:m1")
    assert "Workshop invite" in text and "Asks your fee by Friday" in text and "2026-10-24" in text
    assert "tom@learnhub.example.org" in text and "Hi Tom, my fee is [fee]." in text
    assert "UNTRUSTED" in text  # what came from mail is fenced
    assert "isn't on the Desk" in tools_for(store)["desk_item"](ref="mail:zz")


def test_desk_close_takes_it_off_and_closes_its_thread(store):
    threads.track(store, "mail:m1", "reply", "Reply: workshop invite", "owed", due="2026-10-24")
    said = tools_for(store)["desk_close"](ref="mail:m1", why="not interested")
    assert "Closed" in said
    assert [i["ref"] for i in store.get_setting(report.CARD)["needs_you"]] == ["mail:m2"]
    assert threads.open_refs(store) == set()
    row = store.one("select status, notes from tasks where source_ref = 'mail:m1'")
    assert row["status"] == "done" and "not interested" in row["notes"]


def test_desk_close_needs_a_reason_and_a_known_item(store):
    tools = tools_for(store)
    assert "why" in tools["desk_close"](ref="mail:m1", why="").lower()
    assert "isn't on the Desk" in tools["desk_close"](ref="mail:zz", why="done")


def test_a_reminder_card_points_to_task_update(store):
    assert "task_update" in tools_for(store)["desk_item"](ref="task:7")


def test_threads_close_by_ref(store):
    threads.track(store, "mail:o1", "order", "Order: lamp", "shipped")
    assert "Closed" in threads.close(store, "mail:o1", "delivered")
    assert "No open thread" in threads.close(store, "mail:o1", "delivered")



def test_everything_the_watch_wrote_is_inside_the_fence(store):
    text = tools_for(store)["desk_item"](ref="mail:m1")
    fence = text.index("<<<UNTRUSTED")
    assert text.index("Workshop invite") > fence and text.index("Reply with your fee") > fence


def test_closing_on_the_desk_is_the_users_not_the_watchs(store):
    from datetime import datetime, timedelta

    from odie.jobs.brief import done_lines
    threads.track(store, "mail:m1", "reply", "Reply: workshop invite", "owed")
    tools_for(store)["desk_close"](ref="mail:m1", why="not interested")
    assert done_lines(store, datetime.now().astimezone() + timedelta(minutes=1)) == []
