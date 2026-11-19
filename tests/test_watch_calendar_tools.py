"""The watch can write to a connected calendar app: its check starts with that app's skill loaded, so the app's
calendar tools (calendar_create_event, calendar_update_event) are there from the first request; before, they joined only
after load_skill, which the watch never calls, so a bill never reached Google Calendar. And mail is sorted by when it
came, whatever the app's date format ("Wed, 21 Oct 2026 10:00:00 +0530" sorted as text put Wednesday first)."""
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from odie.store.db import Store
from odie.watch import check, fetch, sources
from tests.test_append_only import Scripted
from tests.test_lighter_tools import APP_TOOLS, TESTER, _tool_names

NOW = datetime(2026, 10, 21, 19, 30, tzinfo=ZoneInfo("Asia/Kolkata"))


@pytest.fixture
def store(isolated_settings, tmp_path):
    s = Store(tmp_path / "assistant.db")
    s.init_schema()
    return s


async def test_a_background_turn_can_start_with_an_apps_skill_loaded(store, monkeypatch):
    from odie.app import runner as runner_mod
    from odie.plugins import mcp
    mcp.write_config({"tester": TESTER})
    Scripted.seen = []
    Scripted.script = {"It is ": [("echo", {"text": "x"}), "Done."]}  # no load_skill: the app is already there
    monkeypatch.setattr(runner_mod, "model_for", lambda selection, thinking: Scripted(model="scripted"))
    r = runner_mod.OdieRunner(store)
    await r.load_plugins()
    try:
        said = await r.background_turn("Check the thing", skills=("mcp-tester",))
    finally:
        await r.close()
    assert said.endswith("Done.")
    assert APP_TOOLS <= _tool_names(Scripted.seen[0])  # from the first request
    echoed = [m for m in Scripted.seen[-1]["messages"] for p in m["parts"] if p.get("function_response", {}).get("name") == "echo"]
    assert echoed


def test_the_watch_loads_the_calendar_apps_it_writes_to(store):
    store.set_setting(sources.KEY, {"v": sources.VERSION, "sources": [
        sources.Source("mail", "gmail-calendar", "Gmail and Calendar", "plain", "gmail_search", {}).as_dict(),
        sources.Source("calendar", "gmail-calendar", "Gmail and Calendar", "plain", "calendar_list_events", {},
                       start_param="date_from", end_param="date_to").as_dict(),
        sources.Source("calendar", "mac", "Calendar", "native", "mac_calendar_events", {}).as_dict(),
    ]})
    assert check.calendar_skills(store) == ["mcp-gmail-calendar"]  # the Mac's calendar tools are always there


def test_no_calendar_app_means_no_skill_to_load(store):
    store.set_setting(sources.KEY, {"v": sources.VERSION, "sources": [
        sources.Source("mail", "gmail-calendar", "Gmail and Calendar", "plain", "gmail_search", {}).as_dict()]})
    assert check.calendar_skills(store) == []


def test_mail_is_sorted_by_when_it_came_whatever_the_date_format():
    mails = [fetch.Mail("tue", "a@b.c", "Shipped", "Tue, 20 Oct 2026 09:00:00 +0530", "", [], "mail:g"),
             fetch.Mail("wed", "a@b.c", "Bill", "Wed, 21 Oct 2026 08:00:00 +0530", "", [], "mail:g"),
             fetch.Mail("thu", "a@b.c", "Old", "Thu, 15 Oct 2026 10:00:00 +0530", "", [], "mail:g"),
             fetch.Mail("mac", "a@b.c", "Newest", "2026-10-21T12:00:00+05:30", "", [], "mail:mac"),
             fetch.Mail("odd", "a@b.c", "No date", "sometime", "", [], "mail:g")]
    assert [m.id for m in fetch.newest_first(mails)] == ["mac", "wed", "tue", "thu", "odd"]


async def test_a_personalitys_watch_turn_uses_its_own_app_and_brain(store, monkeypatch):
    """Real classes: the app on for Mira alone is listed and runs in her watch's turn, which thinks with her brain;
    in everyday Odie's background turn the same call is refused before it runs."""
    from odie import brains, personalities
    from odie.app import runner as runner_mod
    from odie.plugins import access, mcp
    mcp.write_config({"tester": TESTER})
    mira = personalities.create(store, "Mira").id
    access.set_allowed(store, "tester", access.ODIE, False)
    access.set_allowed(store, "tester", mira, True)
    picked = []
    real_for_personality = brains.for_personality

    def for_personality(store_, pid):
        picked.append(pid)
        return real_for_personality(store_, pid)
    monkeypatch.setattr(brains, "for_personality", for_personality)
    monkeypatch.setattr(runner_mod, "model_for", lambda selection, thinking: Scripted(model="scripted"))
    r = runner_mod.OdieRunner(store)
    await r.load_plugins()
    try:
        Scripted.seen = []
        Scripted.script = {"It is ": [("echo", {"text": "x"}), "Done."]}
        await r.background_turn("Check the thing", skills=("mcp-tester",), owner=mira)
        hers = [p["function_response"]["response"] for m in Scripted.seen[-1]["messages"] for p in m["parts"]
                if p.get("function_response", {}).get("name") == "echo"]
        Scripted.seen = []
        Scripted.script = {"It is ": [("echo", {"text": "x"}), "Done."]}
        await r.background_turn("Check the thing", skills=("mcp-tester",))
        odies = [p["function_response"]["response"] for m in Scripted.seen[-1]["messages"] for p in m["parts"]
                 if p.get("function_response", {}).get("name") == "echo"]
    finally:
        await r.close()
    assert picked == [mira]
    assert hers and "switched off" not in str(hers[0])
    assert not odies or "switched off" in str(odies[0])  # never listed for Odie, or refused before it runs
    assert personalities.of_session(store, "anything") == ""  # nothing left belonging to her
