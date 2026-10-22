"""Reading mail and events through each kind of app, and what changed since the last check."""
import json
from datetime import datetime, timedelta, timezone, UTC

import pytest

from odie.store.db import Store
from odie.watch import fetch, sources
from tests.test_watch_calls import spec_for

NOW = datetime(2026, 10, 8, 9, 0, tzinfo=UTC)
ZAP_MAIL = [{"id": "m1", "from": {"email": "xyz@example.com", "name": "Xyz"}, "subject": "The deck", "date": "2026-10-08T08:40:00Z",
             "body_plain": "Please see the attached PDF." + " more" * 400, "raw": {"headers": "x" * 9000},
             "all_attachments": [{"file_name": "q3.pdf", "mime_type": "application/pdf", "size": 120000}]},
            {"id": "m0", "from": "old@example.com", "subject": "Old", "date": "2026-10-07T07:00:00Z", "body_plain": "seen before"}]
EVENTS = [{"id": "e1", "summary": "Standup", "start": {"dateTime": "2026-10-08T15:00:00+05:30"}, "end": {"dateTime": "2026-10-08T15:15:00+05:30"},
           "location": "Meet", "attendees": [{"email": "a@example.com"}]}]


@pytest.fixture
def store(isolated_settings, tmp_path):
    s = Store(tmp_path / "a.db")
    s.init_schema()
    return s


def test_parsers_know_the_common_shapes():
    m = fetch.parse_mail(json.dumps({"results": ZAP_MAIL}), "mail:zapier")
    assert [x.id for x in m] == ["m1", "m0"] and m[0].frm == "Xyz <xyz@example.com>" and m[0].subject == "The deck"
    assert len(m[0].snippet) <= 300 and m[0].attachments == [{"name": "q3.pdf", "type": "application/pdf", "size": 120000}]
    assert "raw" not in json.dumps(m[0].brief()) and "x" * 100 not in json.dumps(m[0].brief())
    comp = fetch.parse_mail(json.dumps({"data": {"messages": [{"messageId": "c1", "sender": "a@b.c", "subject": "S",
                                                               "messageTimestamp": "2026-10-08T08:00:00Z", "messageText": "t"}]}}), "mail:c")
    assert comp[0].id == "c1" and comp[0].frm == "a@b.c"
    e = fetch.parse_events(json.dumps({"events": EVENTS}), "calendar:x")
    assert e[0].title == "Standup" and e[0].start.startswith("2026-10-08T15:00") and e[0].attendees == ["a@example.com"]
    assert fetch.parse_mail("not json", "s") == [] and fetch.parse_events("[]", "s") == []


async def test_new_mail_through_zapier_since_the_last_check(store, tmp_path):
    from odie.plugins import mcp
    mcp.write_config({"zapier": spec_for("zapier", tmp_path, mail=ZAP_MAIL, events=EVENTS)})
    await sources.detect_and_save(store)
    f = fetch.Fetcher(store, NOW)
    got = await f.new_mail()
    assert [m.id for m in got] == ["m1", "m0"] and "mail:zapier" in f.first
    calls = [json.loads(line) for line in (tmp_path / "calls.log").read_text().splitlines()]
    q = next(c for c in calls if c["tool"] == "execute_zapier_read_action" and c["args"]["tool_name"] == "gmail_find_email")
    assert q["args"]["params"]["query"] == f"after:{int((NOW - timedelta(hours=24)).timestamp())}"  # the first check: 24 h back
    f.commit()
    again = fetch.Fetcher(store, NOW + timedelta(minutes=30))
    assert await again.new_mail() == []  # both seen now
    assert not again.first and again.statuses["mail:zapier"]["ok"] is True


async def test_events_say_what_changed(store, tmp_path):
    from odie.plugins import mcp
    data = tmp_path / "mail.json"
    mcp.write_config({"cal": spec_for("plain", tmp_path, events=EVENTS)})
    await sources.detect_and_save(store)
    f = fetch.Fetcher(store, NOW)
    assert [e.change for e in await f.upcoming_events()] == ["new"]
    f.commit()
    moved = [{**EVENTS[0], "start": {"dateTime": "2026-10-08T16:00:00+05:30"}}, {**EVENTS[0], "id": "e2", "summary": "Lunch"}]
    data.write_text(json.dumps({"mail": [], "events": moved}))
    f2 = fetch.Fetcher(store, NOW + timedelta(minutes=30))
    assert {e.id: e.change for e in await f2.upcoming_events()} == {"e1": "moved", "e2": "new"}
    f2.commit()
    data.write_text(json.dumps({"mail": [], "events": []}))
    f3 = fetch.Fetcher(store, NOW + timedelta(minutes=60))
    got = await f3.upcoming_events()
    assert {e.id: e.change for e in got} == {"e1": "cancelled"}  # e2 (09:30 UTC) has started: over, not cancelled


async def test_a_failing_source_is_recorded_and_the_rest_still_read(store, tmp_path):
    from odie.plugins import mcp
    mcp.write_config({"mymail": spec_for("plain", tmp_path, mail=ZAP_MAIL)})
    await sources.detect_and_save(store)
    good = sources.saved(store)
    broken = sources.Source("mail", "gone", "Gone", "plain", "search_emails", {}, query_param="query")
    store.set_setting(sources.KEY, {**store.get_setting(sources.KEY), "sources": [s.as_dict() for s in [broken, *good]]})
    mcp.write_config({"mymail": spec_for("plain", tmp_path, mail=ZAP_MAIL), "gone": {"command": str(tmp_path / "missing")}})
    f = fetch.Fetcher(store, NOW)
    assert [m.id for m in await f.new_mail()] == ["m1", "m0"]
    assert f.statuses["mail:gone"]["ok"] is False and f.statuses["mail:gone"]["reason"]
    f.commit()
    assert store.get_setting(fetch.STATE)["sources"]["mail:gone"]["fails"] == 1


async def test_save_attachment_base64_and_refusal(store, tmp_path):
    from odie.plugins import mcp
    mcp.write_config({"mymail": spec_for("plain", tmp_path, mail=ZAP_MAIL)})
    await sources.detect_and_save(store)
    f = fetch.Fetcher(store, NOW)
    await f.new_mail()
    path = await f.save_attachment("m1", "q3.pdf")
    assert path.read_bytes() == b"PDF" and path.name == "q3.pdf" and "watch" in str(path)
    with pytest.raises(fetch.CallError):
        await f.save_attachment("m1", "../../etc/passwd")



async def test_zapier_events_send_the_calendar(store, tmp_path):
    from odie.plugins import mcp
    mcp.write_config({"zapier": spec_for("zapier", tmp_path, events=EVENTS)})
    await sources.detect_and_save(store)
    f = fetch.Fetcher(store, NOW)
    assert [e.title for e in await f.upcoming_events()] == ["Standup"] and f.statuses["calendar:zapier"]["ok"] is True
    calls = [json.loads(line) for line in (tmp_path / "calls.log").read_text().splitlines()]
    q = next(c for c in calls if c["tool"] == "execute_zapier_read_action" and c["args"]["tool_name"] == "google_calendar_find_events")
    assert q["args"]["params"]["calendarid"] == "me@example.com" and "end_time" in q["args"]["params"]


# A line-style calendar server: its calendar wants days ("YYYY-MM-DD") and answers in lines, not JSON. The watch
# sent no date_from and the card said "MCP error -32602 … received undefined at date_from".
IST = timezone(timedelta(hours=5, minutes=30))
GM_NOW = datetime(2026, 10, 9, 18, 0, tzinfo=IST)
GM_EVENTS = [
    {"id": "done1", "start": "2026-10-09T09:00:00+05:30", "end": "2026-10-09T09:30:00+05:30", "summary": "Standup"},
    {"id": "eve1", "start": "2026-10-09T18:30:00+05:30", "end": "2026-10-09T19:00:00+05:30", "summary": "Call with Ravi",
     "attendees": ["ravi@example.com", "me@example.com"], "location": "Zoom"},
    {"id": "late1", "start": "2026-10-09T23:30:00+05:30", "end": "2026-10-10T00:30:00+05:30", "summary": "Deploy window"},
    {"id": "day1", "start": "2026-10-10", "end": "2026-10-11", "allDay": True, "summary": "Diwali shopping"},
    {"id": "tom1", "start": "2026-10-10T10:00:00+05:30", "end": "2026-10-10T11:00:00+05:30", "summary": "Dentist", "location": "Baner"},
]


async def test_gmail_mcp_calendar_gets_days_and_its_lines_are_read(store, tmp_path):
    from odie.plugins import mcp
    mcp.write_config({"gmail-calendar": spec_for("gmailmcp", tmp_path, events=GM_EVENTS)})
    await sources.detect_and_save(store)
    f = fetch.Fetcher(store, GM_NOW)
    got = {e.id: e for e in await f.upcoming_events()}
    calls = [json.loads(line) for line in (tmp_path / "calls.log").read_text().splitlines()]
    assert calls[-1] == {"tool": "calendar_list_events", "args": {"date_from": "2026-10-09", "date_to": "2026-10-10"}}
    assert f.statuses["calendar:gmail-calendar"]["ok"] is True
    assert set(got) == {"eve1", "late1", "day1", "tom1"}  # the 09:00 standup is over
    call = got["eve1"]
    assert (call.title, call.start, call.end) == ("Call with Ravi", "2026-10-09T18:30:00+05:30", "2026-10-09T19:00:00+05:30")
    assert call.attendees == ["ravi@example.com", "me@example.com"] and call.where == "Zoom"
    assert got["late1"].end == "2026-10-10T00:30:00+05:30"           # past midnight: the next day
    assert (got["day1"].start, got["day1"].end) == ("2026-10-10", "")  # all day
    assert (got["tom1"].start, got["tom1"].where) == ("2026-10-10T10:00:00+05:30", "Baner")  # its day from the "## 2026-10-10" line


def test_gmail_mcp_lines_on_one_day_and_none():
    one = "a1 | 07:00-07:45 | Run @ Park\nb2 | all day 2026-10-09 | Holiday | x@example.com"
    got = fetch.parse_events(one, "calendar:g", "2026-10-09", IST)
    assert [(e.id, e.title, e.start, e.where, e.attendees) for e in got] == [
        ("a1", "Run", "2026-10-09T07:00:00+05:30", "Park", []), ("b2", "Holiday", "2026-10-09", "", ["x@example.com"])]
    assert fetch.parse_events("No events on 2026-10-09.", "calendar:g", "2026-10-09", IST) == []


async def test_a_failed_turn_leaves_its_mail_for_the_next_check(store, tmp_path):
    """The model's turn timed out: nobody looked at the mail, so the next check reads it again (and the source's last
    good read stays put so it comes back); after MAX_RETRIES such checks it is marked seen after all."""
    from odie.plugins import mcp
    mcp.write_config({"zapier": spec_for("zapier", tmp_path, mail=ZAP_MAIL, events=EVENTS)})
    await sources.detect_and_save(store)
    f = fetch.Fetcher(store, NOW)
    assert [m.id for m in await f.new_mail()] == ["m1", "m0"]
    f.commit(turn_failed=True)
    state = store.get_setting(fetch.STATE)
    assert state["seen"] == [] and state["retries"] == {"m1": 1, "m0": 1}
    assert state["sources"]["mail:zapier"]["last_ok"] is None and state["sources"]["mail:zapier"]["fails"] == 0

    again = fetch.Fetcher(store, NOW + timedelta(minutes=30))
    assert [m.id for m in await again.new_mail()] == ["m1", "m0"]  # read again, a day back as before
    again.commit(turn_failed=True)
    assert store.get_setting(fetch.STATE)["retries"] == {"m1": 2, "m0": 2}

    third = fetch.Fetcher(store, NOW + timedelta(minutes=60))
    assert [m.id for m in await third.new_mail()] == ["m1", "m0"]
    third.commit(turn_failed=True)
    state = store.get_setting(fetch.STATE)
    assert sorted(state["seen"]) == ["m0", "m1"] and state["retries"] == {}  # enough: seen after all
    assert state["sources"]["mail:zapier"]["last_ok"] == third.statuses["mail:zapier"]["at"]

    fourth = fetch.Fetcher(store, NOW + timedelta(minutes=90))
    assert await fourth.new_mail() == []


async def test_a_good_turn_after_a_failed_one_clears_the_retries(store, tmp_path):
    from odie.plugins import mcp
    mcp.write_config({"zapier": spec_for("zapier", tmp_path, mail=ZAP_MAIL, events=EVENTS)})
    await sources.detect_and_save(store)
    f = fetch.Fetcher(store, NOW)
    await f.new_mail()
    f.commit(turn_failed=True)
    g = fetch.Fetcher(store, NOW + timedelta(minutes=30))
    await g.new_mail()
    g.commit()
    state = store.get_setting(fetch.STATE)
    assert sorted(state["seen"]) == ["m0", "m1"] and state["retries"] == {}


GM_INVITE = [{"id": "g1", "threadId": "t1", "from": "A Person <a.person@example.com>", "subject": "New consultation",
              "date": "2026-10-08T08:30:00Z", "snippet": "Thanks for being part of our network!"}]
GM_INVITE_BODY = "Hi, a client would value your view. 1. Do you know the market? 2. Who competes? 3. When are you free?"


async def gmail_check(store, tmp_path, **extra):
    """A check whose Gmail-style app has read tools, with its new mail listed."""
    from odie.plugins import mcp
    from odie.watch.tools import Check, watch_tools
    mcp.write_config({"gmail-calendar": spec_for("gmailmcp", tmp_path, mail=GM_INVITE, bodies={"g1": GM_INVITE_BODY},
                                                 **extra)})
    await sources.detect_and_save(store)
    check = Check(fetch.Fetcher(store, NOW))
    tools = {t.name: t for t in watch_tools(check)}
    await tools["new_mail"].func()
    return check, tools


def calls_to(tmp_path, tool):
    lines = (tmp_path / "calls.log").read_text().splitlines()
    return [json.loads(line)["args"] for line in lines if json.loads(line)["tool"] == tool]


async def test_read_mail_opens_the_whole_mail_not_the_preview(store, tmp_path):
    # The preview reads like a newsletter; only the whole mail shows a person asking three questions (22 Oct).
    check, tools = await gmail_check(store, tmp_path)
    got = await tools["read_mail"].func(mail_id="g1")
    assert "When are you free?" in got["result"] and "only the preview" not in got["result"]
    await tools["read_mail"].func(mail_id="g1")
    assert calls_to(tmp_path, "gmail_read") == [{"message_id": "g1"}]  # opened once, then kept
    assert check.fetcher.read_mail("g1").thread == "t1"


async def test_a_failed_read_keeps_the_preview_and_says_so(store, tmp_path):
    check, tools = await gmail_check(store, tmp_path, read_fails=True)
    got = await tools["read_mail"].func(mail_id="g1")
    assert "Thanks for being part of our network!" in got["result"]
    assert "(only the preview: the app didn't open it)" in got["result"]


async def test_a_mail_not_in_this_check_is_still_refused(store, tmp_path):
    check, tools = await gmail_check(store, tmp_path)
    got = await tools["read_mail"].func(mail_id="nope")
    assert "error" in got


async def test_a_folded_mail_opens_through_the_app_that_holds_its_id(store, tmp_path):
    check, tools = await gmail_check(store, tmp_path)
    kept = check.fetcher.read_mail("g1")
    kept.sources = ["mail:mac", "mail:gmail-calendar"]  # Apple Mail had a copy too; the id is the connector's
    await tools["read_mail"].func(mail_id="g1")
    assert calls_to(tmp_path, "gmail_read") == [{"message_id": "g1"}]


async def test_apple_mail_opens_with_its_own_read(store, monkeypatch):
    from odie.mac import mail as mac_mail
    f = fetch.Fetcher(store, NOW)
    f._mail["mac:5"] = fetch.Mail("mac:5", "B <b@example.com>", "Hi", "2026-10-08T08:00:00Z", "short", [], "mail:mac",
                                  body="short", sources=["mail:mac"])
    asked = {}

    async def fake_read(mail_id):
        asked["id"] = mail_id
        return {"id": mail_id, "body": "the whole message"}
    monkeypatch.setattr(mac_mail, "read", fake_read)
    apple_mail = sources.Source("mail", "mac", "Apple Mail", "native", "mac_mail_new", {})
    monkeypatch.setattr(fetch, "saved", lambda _store: [apple_mail])
    m = await f.open_mail("mac:5")
    assert asked["id"] == "mac:5" and m.body == "the whole message" and m.opened
