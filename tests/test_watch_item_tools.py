"""Chat acting on a loop's card: watch_item shows the loop, its drafted reply and its evidence; watch_close is the
user's Done said in chat (remembered: closed by him, not by Odie)."""
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from odie.loops import ledger
from odie.store.db import Store

NOW = datetime(2026, 11, 19, 10, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
CARD = {"pile": "alerts", "from": "Tom Reyes", "subject": "Quick note", "due": "2026-10-24",
        "suggestion": "Reply with your fee",
        "draft": {"to": "tom@learnhub.example.org", "subject": "Re: Quick note", "body": "Hi Tom, my fee is [fee]."}}


@pytest.fixture
def store(isolated_settings, tmp_path):
    s = Store(tmp_path / "a.db")
    s.init_schema()
    return s


def a_loop(store, **kw):
    return ledger.open_loop(store, "", NOW, kw.pop("title", "Workshop invite"), "reply owed", owner="you",
                            refs=kw.pop("refs", ["mail:m1", "thread:t1"]), state="ready",
                            result="Asks your fee by Friday", due_at="2026-10-24T09:00+05:30", source="mail",
                            ref="mail:m1", fact="Workshop invite: asks your fee", card=kw.pop("card", CARD))


def tools_for(store):
    from odie.agent.tools.watch_items import make_watch_item_tools
    return {t.name: t.func for t in make_watch_item_tools(store)}


def test_watch_item_shows_the_loop_its_draft_and_why(store):
    lid = a_loop(store)
    for ref in (f"loop:{lid}", f"#{lid}", str(lid), "mail:m1"):
        text = tools_for(store)["watch_item"](ref=ref)
        assert f"Loop #{lid}" in text and "Workshop invite" in text and "Asks your fee by Friday" in text
    assert "tom@learnhub.example.org" in text and "Hi Tom, my fee is [fee]." in text and "2026-10-24" in text
    assert "asks your fee" in text  # its evidence
    assert "UNTRUSTED" in text  # what came from mail is fenced
    assert ledger.get(store, lid)["tapped"] == "ask"
    assert "isn't on Pulse" in tools_for(store)["watch_item"](ref="mail:zz")


def test_watch_close_is_his_done_remembered_and_shown_in_done_today(store):
    from types import SimpleNamespace
    lid = a_loop(store)
    in_the_app = SimpleNamespace(session=SimpleNamespace(id="chat-1"), state={})
    said = tools_for(store)["watch_close"](ref=f"loop:{lid}", why="not interested", tool_context=in_the_app)
    assert "Closed" in said
    loop = ledger.get(store, lid)
    assert loop["state"] == "closed" and loop["closed_by"] == ledger.CLOSED_IN_CHAT
    assert loop["closed_why"] == "not interested"
    assert [lp["id"] for lp in ledger.closed_since(store, "", NOW.replace(hour=0))] == [lid]  # Done today, Reopen
    assert ledger.find_done_by_user(store, "", ["mail:m1"], NOW)["id"] == lid  # remembered as his


def test_watch_close_needs_a_reason_and_a_known_card(store):
    tools = tools_for(store)
    lid = a_loop(store)
    assert "why" in tools["watch_close"](ref=f"loop:{lid}", why="").lower()
    assert "isn't on Pulse" in tools["watch_close"](ref="loop:999", why="done")


def test_a_reminder_card_points_to_task_update(store):
    assert "task_update" in tools_for(store)["watch_item"](ref="task:7")


def test_everything_the_watch_wrote_is_inside_the_fence(store):
    lid = a_loop(store)
    text = tools_for(store)["watch_item"](ref=f"loop:{lid}")
    fence = text.index("<<<UNTRUSTED")
    assert text.index("Workshop invite") > fence and text.index("Reply with your fee") > fence


def test_watch_item_names_the_app_that_holds_the_mail(store):
    """Chat opens a mail by its id in the right app (Gmail's connector, not Apple Mail): the loop says which."""
    lid = a_loop(store, card={**CARD, "app": "Mail Connector"})
    text = tools_for(store)["watch_item"](ref=f"loop:{lid}")
    assert "in Mail Connector, id m1" in text


def test_a_personalitys_loop_is_not_everyday_chats(store):
    from odie import personalities
    mira = personalities.create(store, "Mira").id
    hers = ledger.open_loop(store, mira, NOW, "Mira's", "reply owed", owner="you", state="ready")
    assert "isn't on Pulse" in tools_for(store)["watch_item"](ref=f"loop:{hers}")
