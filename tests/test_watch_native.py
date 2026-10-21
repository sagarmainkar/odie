"""The Mac's apps as watch sources: found only on a Mac with the permission, read through odie.mac.native, their
mail and events folded with a connector's copies, attachments saved through Mail."""
import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from odie.mac import native, scripts
from odie.store.db import Store
from odie.watch import fetch, sources
from odie.watch.calls import Result
from odie.watch.fetch import Event, Mail, fold_events, fold_mail
from tests.test_watch_calls import spec_for
from tests.test_watch_fetch import EVENTS, ZAP_MAIL

NOW = datetime(2026, 10, 21, 13, 0, tzinfo=ZoneInfo("Asia/Kolkata"))


@pytest.fixture
def store(isolated_settings, tmp_path):
    s = Store(tmp_path / "a.db")
    s.init_schema()
    return s


def test_mac_sources_need_a_mac_and_the_permission():
    real = sources.find_native_sources
    assert real(available=lambda: False, status=lambda a: "granted") == []
    only_mail = real(available=lambda: True, status=lambda a: "granted" if a == "mail" else "unknown")
    assert [(s.id, s.style, s.app) for s in only_mail] == [("mail:mac", "native", "Apple Mail")]
    both = real(available=lambda: True, status=lambda a: "granted")
    assert [s.id for s in both] == ["mail:mac", "calendar:mac"] and both[1].start_param == "start"


def test_the_same_mail_through_gmail_and_apple_mail_is_one_row():
    g = Mail("g1", "Axis Bank <cc.statements@axis.bank.in>", "Your statement", "2026-10-21T13:47:36+05:30", "Dear", [], "mail:gmail", sources=["mail:gmail"])
    m = Mail("mac:12", "cc.statements@axis.bank.in", "Your Statement", "2026-10-21T13:47:50+05:30", "Dear", [], "mail:mac", sources=["mail:mac"])
    other = Mail("mac:13", "a@b.c", "Hi", "2026-10-21T13:50:00+05:30", "", [], "mail:mac", sources=["mail:mac"])
    out = fold_mail([m, g, other])
    assert [x.id for x in out] == ["g1", "mac:13"] and out[0].sources == ["mail:mac", "mail:gmail"]
    assert fold_mail([other]) == [other]


def test_the_same_event_in_both_calendars_is_one_row_with_the_connectors_id():
    g = Event("e1", "Dentist", "2026-10-22T10:00:00+05:30", "2026-10-22T10:30:00+05:30", "", [], "calendar:google", sources=["calendar:google"])
    m = Event("u7", "dentist", "2026-10-22T10:02:00+05:30", "2026-10-22T10:30:00+05:30", "", [], "calendar:mac", sources=["calendar:mac"])
    far = Event("u8", "Dentist", "2026-10-22T16:00:00+05:30", "", "", [], "calendar:mac", sources=["calendar:mac"])
    twin_same_source = Event("u9", "Dentist", "2026-10-22T10:01:00+05:30", "", "", [], "calendar:mac", sources=["calendar:mac"])
    out = fold_events([m, g, far, twin_same_source])
    assert [e.id for e in out] == ["e1", "u8", "u9"]
    assert out[0].sources == ["calendar:mac", "calendar:google"] and out[0].brief()["sources"] == ["calendar:mac", "calendar:google"]


async def test_native_call_reads_mail_and_events_and_says_when_not_allowed(monkeypatch):
    from odie.mac import calendar, mail, permissions

    async def fake_mail(since, limit=25, run=None):
        assert since == datetime(2026, 10, 21, 12, 30) and limit == 25
        return [{"id": "mac:1", "from": "a@b.c", "subject": "s", "at": "2026-10-21T12:45:00+05:30", "snippet": "", "attachments": []}]
    monkeypatch.setattr(mail, "new_mail", fake_mail)
    got = await native.call("mac_mail_new", {"since": "2026-10-21T12:30:00+05:30", "limit": 25})
    assert not got.is_error and json.loads(got.text)[0]["id"] == "mac:1"

    async def refused(start, end, run=None):
        raise scripts.MacPermission("Calendar")
    monkeypatch.setattr(calendar, "events", refused)
    remembered = {}
    monkeypatch.setattr(permissions, "remember", lambda a, w: remembered.update({a: w}))
    got = await native.call("mac_calendar_events", {"start": "2026-10-21T13:00:00+05:30", "end": "2026-10-22T13:00:00+05:30"})
    assert got.is_error and "Settings → Mac apps" in got.text and remembered == {"calendar": "denied"}
    assert (await native.call("mac_other", {})).is_error


async def test_the_fetcher_reads_the_mac_beside_a_connector(store, tmp_path, monkeypatch):
    from odie.plugins import mcp
    mcp.write_config({"zapier": spec_for("zapier", tmp_path, mail=ZAP_MAIL, events=EVENTS)})
    monkeypatch.setattr(sources, "native_sources", lambda available=None, status=None: [
        sources.Source("mail", "mac", "Apple Mail", "native", "mac_mail_new", {}),
        sources.Source("calendar", "mac", "Calendar", "native", "mac_calendar_events", {}, start_param="start", end_param="end")])
    await sources.detect_and_save(store)
    assert {s.id for s in sources.saved(store)} >= {"mail:mac", "calendar:mac", "mail:zapier"}
    calls = []

    async def fake_call(tool, args):
        calls.append((tool, sorted(args)))
        if tool == "mac_mail_new":
            return Result(json.dumps([{"id": "mac:5", "from": "Bakliwal <bt@x.in>", "subject": "Batch", "at": "2026-10-21T12:50:00+05:30",
                                       "snippet": "Hi", "attachments": [{"name": "list.pdf", "size": 10}]}]), False)
        return Result(json.dumps([{"id": "u1", "title": "Udo birthday", "start": "2026-10-22T00:00:00+05:30", "end": "2026-10-23T00:00:00+05:30",
                                   "where": "", "attendees": [], "calendar": "Home", "all_day": True}]), False)
    monkeypatch.setattr(native, "call", fake_call)
    f = fetch.Fetcher(store, NOW)
    mails = await f.new_mail()
    assert "mac:5" in [m.id for m in mails] and f.statuses["mail:mac"]["ok"] is True
    assert ("mac_mail_new", ["limit", "since"]) in calls
    events = await f.upcoming_events(hours=48)
    assert any(e.id == "u1" and e.sources == ["calendar:mac"] for e in events)
    assert ("mac_calendar_events", ["end", "start"]) in calls

    from odie.mac import mail as mac_mail
    saved_to = {}

    async def fake_save(mail_id, name, into, run=None):
        saved_to.update({"id": mail_id, "name": name, "into": into})
        into.mkdir(parents=True, exist_ok=True)
        (into / name).write_bytes(b"%PDF")
        return into / name
    monkeypatch.setattr(mac_mail, "save_attachment", fake_save)
    path = await f.save_attachment("mac:5", "list.pdf")
    assert path.read_bytes() == b"%PDF" and saved_to["id"] == "mac:5" and "watch" in str(saved_to["into"])


def test_badges_say_where_an_item_came_from():
    from odie.watch.report import badge_of, badges_of
    statuses = {"mail:gmail-calendar": {"app": "Gmail and Calendar", "kind": "mail"}, "mail:zapier": {"app": "Zapier", "kind": "mail"}}
    assert badge_of("mail:mac", statuses) == {"kind": "icloud", "app": "Apple Mail"}
    assert badge_of("calendar:mac", statuses) == {"kind": "icloud", "app": "Calendar"}
    assert badge_of("mail:gmail-calendar", statuses) == {"kind": "gmail", "app": "Gmail and Calendar"}
    assert badge_of("mail:zapier", statuses) == {"kind": "app", "app": "Zapier"}
    assert [b["kind"] for b in badges_of(["calendar:mac", "calendar:gmail-calendar", "calendar:mac"], statuses)] == ["icloud", "gmail"]


def test_the_card_carries_badges_on_items_and_events(store):
    from odie.watch import report
    statuses = {"mail:mac": {"ok": True, "app": "Apple Mail", "kind": "mail"}, "calendar:gmail-calendar": {"ok": True, "app": "Gmail and Calendar", "kind": "calendar"},
                "calendar:mac": {"ok": True, "app": "Calendar", "kind": "calendar"}}
    mails = [Mail("mac:5", "Bakliwal <bt@x.in>", "Batch", "2026-10-21T12:50:00+05:30", "Hi", [], "mail:mac", sources=["mail:mac"])]
    events = [Event("e1", "Dentist", "2026-10-22T10:00:00+05:30", "", "", [], "calendar:gmail-calendar", sources=["calendar:gmail-calendar", "calendar:mac"])]
    report.apply(store, NOW, [{"ref": "mail:mac:5", "title": "Batch choice", "why": "by 25 Oct"}, {"ref": "event:e1", "title": "Dentist", "why": "moved"}],
                 "two things", mails, events, statuses, first=True)
    card = store.get_setting(report.CARD)
    by_ref = {i["ref"]: i for i in card["needs_you"]}
    assert by_ref["mail:mac:5"]["badges"] == [{"kind": "icloud", "app": "Apple Mail"}]
    assert [b["kind"] for b in by_ref["event:e1"]["badges"]] == ["gmail", "icloud"]
    assert [b["kind"] for b in card["events"][0]["badges"]] == ["gmail", "icloud"]


async def test_up_next_keeps_the_events_badges(store, monkeypatch):
    from odie import upcoming
    store.set_setting("watch.card", {"events": [{"id": "e1", "title": "Dentist", "start": "2026-10-22T10:00:00+05:30", "end": "2026-10-22T10:30:00+05:30",
                                                 "badges": [{"kind": "gmail", "app": "Gmail and Calendar"}, {"kind": "icloud", "app": "Calendar"}]}]})
    got = await upcoming.build(store, NOW)
    row = next(i for i in got["items"] if i["id"] == "cal:watch:e1")
    assert [b["kind"] for b in row["badges"]] == ["gmail", "icloud"]


def test_the_watch_may_add_to_the_macs_calendar():
    from types import SimpleNamespace
    from odie.watch import check
    assert check.guard(SimpleNamespace(name="mac_calendar_add", _require_confirmation=True), {}, None) is None
    assert check.guard(SimpleNamespace(name="mac_reminder_add", _require_confirmation=True), {}, None) is not None
