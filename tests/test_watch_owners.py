"""Whose watch it is (18 Nov 2026): everyday Odie's watch as it always was, and a personality's own when its
"Proactive intelligence" switch is on, reading only its own mail and calendar apps, once per inbox, its state kept
apart."""
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from odie import personalities
from odie.plugins import access
from odie.store.db import Store
from odie.watch import owner

DAY = datetime(2026, 11, 18, 10, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
CONFIGURED = {"home": {"command": "home"}, "work": {"command": "work"}, "shop": {"command": "shop"}}


@pytest.fixture
def store(isolated_settings, tmp_path):
    s = Store(tmp_path / "a.db")
    s.init_schema()
    return s


def made(store, name):
    return personalities.create(store, name).id


def only_for(store, server, *pids):
    """The server on for these ones alone (everyday Odie is ODIE)."""
    everyone = [access.ODIE] + [p.id for p in personalities.list_all(store)]
    for who in everyone:
        access.set_allowed(store, server, who, who in pids)


def test_odies_keys_stay_as_they_were_and_a_personalitys_carry_its_id():
    assert owner.key("watch.card", "") == "watch.card"
    assert owner.key("watch.card", "ab12cd34ef56") == "watch.card:ab12cd34ef56"


def test_proactive_is_off_until_switched_on(store):
    mira = made(store, "Mira")
    assert owner.is_proactive(store, mira) is False
    owner.set_proactive(store, mira, True)
    assert owner.is_proactive(store, mira) is True
    assert owner.proactive_owners(store) == [mira]


def test_each_inbox_is_checked_once(store):
    mira, coach = made(store, "Mira"), made(store, "Coach")
    only_for(store, "work", mira)
    only_for(store, "shop", mira, coach)
    owner.set_proactive(store, mira, True)
    owner.set_proactive(store, coach, True)
    assert set(owner.watch_servers(store, CONFIGURED, access.ODIE)) == {"home"}  # as it always was
    assert set(owner.watch_servers(store, CONFIGURED, mira)) == {"work", "shop"}  # home is Odie's inbox: never again
    assert set(owner.watch_servers(store, CONFIGURED, coach)) == set()  # shop is checked by Mira, the older one
    owner.set_proactive(store, mira, False)
    assert set(owner.watch_servers(store, CONFIGURED, coach)) == {"shop"}


def test_the_switch_is_offered_only_with_a_mail_or_calendar_app_of_its_own(store):
    mira, coach, sam = made(store, "Mira"), made(store, "Coach"), made(store, "Sam")
    access.remember_tools(store, {"home": ["gmail_search", "gmail_read"], "work": ["gmail_search"],
                                  "notes": ["search_notes"], "cal": ["calendar_list_events"]})
    configured = {**CONFIGURED, "notes": {"command": "notes"}, "cal": {"command": "cal"}}
    only_for(store, "work", mira)
    only_for(store, "notes", coach)
    only_for(store, "cal", sam)
    assert owner.own_inbox_apps(store, configured, mira) == ["work"]
    assert owner.own_inbox_apps(store, configured, coach) == []  # notes only, and Odie's mail is Odie's to check
    assert owner.own_inbox_apps(store, configured, sam) == ["cal"]
    assert owner.own_inbox_apps(store, configured, access.ODIE) == []


def test_the_next_personality_due_is_the_one_waiting_longest(store):
    mira, coach = made(store, "Mira"), made(store, "Coach")
    assert owner.next_due(store, DAY) is None  # none switched on
    owner.set_proactive(store, mira, True)
    owner.set_proactive(store, coach, True)
    store.set_setting(owner.key("watch.state", mira), {"last_check": "2026-11-18T09:00:00+05:30"})
    store.set_setting(owner.key("watch.state", coach), {"last_check": "2026-11-18T09:20:00+05:30"})
    assert owner.next_due(store, DAY) == mira
    store.set_setting(owner.key("watch.state", mira), {"last_check": "2026-11-18T09:50:00+05:30"})
    assert owner.next_due(store, DAY) == coach  # 40 minutes since Coach's check; 10 since Mira's
    store.set_setting(owner.key("watch.state", coach), {"last_check": "2026-11-18T09:45:00+05:30"})
    assert owner.next_due(store, DAY) is None
    owner.set_proactive(store, mira, False)
    store.set_setting(owner.key("watch.state", mira), {"last_check": "2026-11-18T08:00:00+05:30"})
    assert owner.next_due(store, DAY) is None  # switched off: never checked in the background


# ── the sources, the place in the mail and the check, per owner ──

async def test_a_personalitys_sources_are_its_own_apps(store, tmp_path):
    from odie.plugins import mcp
    from odie.watch import sources
    from tests.test_watch_calls import spec_for
    mira = made(store, "Mira")
    (tmp_path / "h").mkdir()
    (tmp_path / "w").mkdir()
    mcp.write_config({"home": spec_for("plain", tmp_path / "h"), "work": spec_for("plain", tmp_path / "w")})
    only_for(store, "work", mira)
    owner.set_proactive(store, mira, True)
    odies = await sources.detect_and_save(store)
    miras = await sources.detect_and_save(store, mira)
    assert {s.server for s in odies} == {"home"}  # as it always was
    assert {s.server for s in miras} == {"work"}  # her own inbox only, never Odie's again
    assert {s.server for s in sources.saved(store)} == {"home"}
    assert {s.server for s in sources.saved(store, mira)} == {"work"}
    assert store.get_setting("watch.sources:" + mira)  # kept apart, under her id
    assert not sources.stale(store, DAY, mira)


def test_the_fetcher_keeps_its_place_per_owner(store):
    from odie.watch.fetch import Fetcher
    mira = made(store, "Mira")
    store.set_setting("watch.state", {"last_check": "2026-11-18T09:00:00+05:30", "seen": ["m1"], "events": {},
                                      "sources": {}})
    odies, miras = Fetcher(store, DAY), Fetcher(store, DAY, mira)
    assert odies.state["seen"] == ["m1"] and miras.state["seen"] == []
    miras.commit()
    assert store.get_setting("watch.state")["seen"] == ["m1"]  # Odie's place in the mail untouched
    assert store.get_setting("watch.state:" + mira)["last_check"].startswith("2026-11-18T10:00")


def test_a_fetcher_never_calls_an_app_off_for_its_owner(store):
    from odie.watch.calls import CallError
    from odie.watch.fetch import Fetcher
    from odie.watch.sources import Source
    mira = made(store, "Mira")
    only_for(store, "work", mira)
    f = Fetcher(store, DAY)
    f._servers = {"work": {"command": "work"}}
    with pytest.raises(CallError):
        f._spec(Source("mail", "work", "Work", "plain", "search_emails", {}))
    g = Fetcher(store, DAY, mira)
    g._servers = {"work": {"command": "work"}}
    assert g._spec(Source("mail", "work", "Work", "plain", "search_emails", {})) == {"command": "work"}


async def test_a_personalitys_check_writes_its_own_card_and_threads(store, tmp_path):
    import json as _json
    from types import SimpleNamespace

    from odie.plugins import mcp
    from odie.watch import check, report
    from tests.test_watch_calls import spec_for
    from tests.test_watch_fetch import EVENTS, ZAP_MAIL
    mira = made(store, "Mira")
    mcp.write_config({"work": spec_for("plain", tmp_path, mail=ZAP_MAIL, events=EVENTS)})
    only_for(store, "work", mira)
    owner.set_proactive(store, mira, True)

    async def call(tools, name, **args):
        t = next(t for t in tools if t.name == name)
        return await t.run_async(args=args, tool_context=SimpleNamespace())

    async def turn(prompt, tools, instruction):
        mails = _json.loads((await call(tools, "new_mail"))["result"])
        assert mails[0]["id"] == "m1"
        await call(tools, "track_thread", ref="mail:m1", kind="reply", title="Reply to Xyz", stage="owed")
        await call(tools, "report", needs_you=[{"ref": "mail:m1", "title": "Reply to Xyz", "why": "asks for the deck"}],
                   line="1 new email")
    assert await check.run_check(store, DAY, turn, lambda t, b: None, owner=mira) == "ok"
    assert store.get_setting(report.CARD) is None  # Odie's card untouched
    assert store.get_setting("watch.card:" + mira)["line"] == "1 new email"
    from odie.loops import ledger
    assert ledger.open_loops(store, "") == []  # Odie's loops untouched
    [hers] = ledger.open_loops(store, mira)  # the thread and the item about one mail: one loop, hers
    assert "mail:m1" in hers["refs"] and hers["state"] == "ready" and hers["kind"] == "reply owed"


async def test_nothing_new_means_no_model_call(store, tmp_path):
    from odie.plugins import mcp
    from odie.watch import check, report
    from tests.test_watch_calls import spec_for
    from odie.watch import bills
    mcp.write_config({"home": spec_for("plain", tmp_path)})  # an inbox with nothing in it, a calendar with nothing on
    store.set_setting("watch.state", {"last_check": None, "seen": [], "events": {}, "sources": {},
                                      "caught_up": bills.CATCH_UP})  # the one-time catch-up already done

    async def turn(prompt, tools, instruction):
        raise AssertionError("no model call when nothing is new")
    assert await check.run_check(store, DAY, turn, lambda t, b: None) == "quiet"
    card = store.get_setting(report.CARD)
    assert card["checked_at"].startswith("2026-11-18T10:00") and card["line"] == ""
    assert store.get_setting("watch.state")["last_check"].startswith("2026-11-18T10:00")  # the check counts as done


async def test_new_mail_still_runs_the_turn(store, tmp_path):
    from odie.plugins import mcp
    from odie.watch import check
    from tests.test_watch_calls import spec_for
    from tests.test_watch_fetch import ZAP_MAIL
    mcp.write_config({"home": spec_for("plain", tmp_path, mail=ZAP_MAIL)})
    ran = []

    async def turn(prompt, tools, instruction):
        ran.append(prompt)
    await check.run_check(store, DAY, turn, lambda t, b: None)
    assert ran  # new mail: the model reads it


def test_deleting_a_personality_forgets_its_watch(store):
    mira = made(store, "Mira")
    owner.set_proactive(store, mira, True)
    store.set_setting(owner.key("watch.card", mira), {"needs_you": []})
    store.set_setting("watch.card", {"needs_you": [{"ref": "mail:1"}]})
    owner.forget(store, mira)
    assert store.get_setting(owner.key("watch.card", mira)) is None
    assert owner.is_proactive(store, mira) is False
    assert store.get_setting("watch.card") == {"needs_you": [{"ref": "mail:1"}]}  # Odie's stays


def test_a_background_session_belongs_to_its_owner_while_it_runs(store):
    mira = made(store, "Mira")
    assert personalities.of_session(store, "bg-1") == ""
    personalities.running_for("bg-1", mira)
    assert personalities.of_session(store, "bg-1") == mira
    assert access.allowed_in(store, "work", "bg-1") is True
    only_for(store, "work", mira)
    assert access.allowed_in(store, "work", "bg-1") is True  # her own app, in her watch's turn
    personalities.done_running("bg-1")
    assert personalities.of_session(store, "bg-1") == ""
    assert access.allowed_in(store, "work", "bg-1") is False  # as everyday Odie again


async def test_the_personalities_watch_part_runs_only_when_one_is_switched_on(store, tmp_path, monkeypatch):
    from odie.app import main
    mira = made(store, "Mira")
    ran = []

    class Runner:
        async def background_turn(self, *a, **k):
            ran.append(k.get("owner"))

        def memory_of(self, pid):
            return None

        def memory_index(self, pid):
            return ""

    async def fake_run_check(store_, now, turn, push, memory=None, memory_index="", owner="", think=None):
        await turn("Run the watch check.", [], "")
        return "ok"
    monkeypatch.setattr("odie.watch.check.run_check", fake_run_check)
    part = next(p for p in main.background_for(store, Runner()).parts if p.name == "watch:personalities")
    assert part.due(DAY) is False
    assert await main.personality_watch(store, Runner(), DAY) is None
    owner.set_proactive(store, mira, True)
    assert part.due(DAY) is True
    assert await main.personality_watch(store, Runner(), DAY) == mira
    assert ran == [mira]  # the turn runs as hers: her brain, her apps
