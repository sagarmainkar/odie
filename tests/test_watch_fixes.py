"""From the 9b review: a calendar hiccup cancels nothing; a failing post never stops a check from saving its place; the
watch part has time for detection plus a turn; attachments never fetch a link an email planted (or a home address);
the watcher can't drive the browser or close the user's tasks; mail missed during a failed check is read next time;
background turns get the same result cuts and fencing as chat."""
import json
from datetime import datetime, timedelta, UTC
from types import SimpleNamespace

import pytest

from odie.store.db import Store
from odie.watch import check, fetch, sources
from tests.test_watch_calls import spec_for

NOW = datetime(2026, 10, 8, 9, 0, tzinfo=UTC)
SOON = [{"id": "e1", "summary": "Standup", "start": {"dateTime": "2026-10-08T10:00:00+00:00"}, "end": {"dateTime": "2026-10-08T10:15:00+00:00"}}]


@pytest.fixture
def store(isolated_settings, tmp_path):
    s = Store(tmp_path / "a.db")
    s.init_schema()
    return s


async def test_a_calendar_failure_cancels_nothing(store, tmp_path):
    from odie.plugins import mcp
    mcp.write_config({"cal": spec_for("plain", tmp_path, events=SOON)})
    await sources.detect_and_save(store)
    f = fetch.Fetcher(store, NOW)
    await f.upcoming_events()
    f.commit()
    mcp.write_config({"cal": {"command": str(tmp_path / "missing")}})  # the calendar app fails this time
    f2 = fetch.Fetcher(store, NOW + timedelta(minutes=30))
    assert [e.change for e in await f2.upcoming_events()] == []  # nothing "cancelled"
    f2.commit()
    assert "e1" in store.get_setting(fetch.STATE)["events"]  # the last good snapshot is kept


async def test_an_event_that_passed_isnt_cancelled(store, tmp_path):
    from odie.plugins import mcp
    data = tmp_path / "mail.json"
    mcp.write_config({"cal": spec_for("plain", tmp_path, events=SOON)})
    await sources.detect_and_save(store)
    f = fetch.Fetcher(store, NOW)
    await f.upcoming_events()
    f.commit()
    data.write_text(json.dumps({"mail": [], "events": []}))  # it's over, so the app no longer lists it
    f2 = fetch.Fetcher(store, NOW + timedelta(hours=3))
    assert [e.change for e in await f2.upcoming_events()] == []


async def test_a_failing_post_still_saves_the_checks_place(store, tmp_path):
    from odie.plugins import mcp
    mcp.write_config({"mymail": spec_for("plain", tmp_path, mail=[{"id": "m1", "subject": "Hi", "date": "2026-10-08T08:00:00Z"}])})

    async def turn(prompt, tools, instruction):
        t = {x.name: x for x in tools}
        await t["new_mail"].run_async(args={}, tool_context=SimpleNamespace())
        await t["report"].run_async(args={"needs_you": [], "line": "1 new email", "done": [{"message": "made it", "files": []}]},
                                    tool_context=SimpleNamespace())

    async def post(text, media=None, session_id=None):
        raise RuntimeError("chat is busy")
    assert await check.run_check(store, NOW, turn, post, lambda t, b: None) == "ok"
    assert store.get_setting(fetch.STATE)["last_check"] == NOW.isoformat(timespec="seconds")  # not repeated every 5 minutes


def test_the_watch_part_has_time_for_detection_and_a_turn(isolated_settings, tmp_path):
    from odie.app.main import background_for
    s = Store(tmp_path / "a.db")
    s.init_schema()
    part = next(p for p in background_for(s, None).parts if p.name == "watch")
    assert part.limit >= 280 + 240


async def test_attachments_never_fetch_a_planted_or_home_link(store, tmp_path):
    from odie.plugins import mcp
    mails = [{"id": "m1", "subject": "Hi", "date": "2026-10-08T08:00:00Z", "attachments": [{"filename": "a.txt"}]}]
    for answer in ({"content": "http://192.168.1.1/admin"}, {"url": "http://192.168.1.1/admin"}, {"url": "http://127.0.0.1:8000/api/x"}):
        d = tmp_path / answer.__class__.__name__
        spec = spec_for("plain", tmp_path, mail=mails)
        json_path = spec["env"]["MAIL_DATA"]
        data = json.loads(open(json_path).read())
        data["attachment_json"] = answer
        open(json_path, "w").write(json.dumps(data))
        mcp.write_config({"mymail": spec})
        await sources.detect_and_save(store)
        f = fetch.Fetcher(store, NOW)
        await f.new_mail()
        with pytest.raises(fetch.CallError):
            await f.save_attachment("m1", "a.txt")


def test_the_watcher_cant_drive_the_browser_or_close_tasks():
    for name in ("browser_open", "browser_click", "browser_type", "browser_scroll", "task_update"):
        assert check.guard(SimpleNamespace(name=name), {}, None) is not None, name
    assert check.guard(SimpleNamespace(name="task_add"), {}, None) is None
    # the one write the owner allows in the background: a calendar event for a bill or a deadline
    assert check.guard(SimpleNamespace(name="calendar_create_event", _require_confirmation=True), {}, None) is None
    assert check.guard(SimpleNamespace(name="gmail_send_draft", _require_confirmation=True), {}, None) is not None


async def test_mail_missed_during_a_failed_check_is_read_next_time(store, tmp_path):
    from odie.plugins import mcp
    good = spec_for("plain", tmp_path, mail=[])
    mcp.write_config({"mymail": good})
    await sources.detect_and_save(store)
    f = fetch.Fetcher(store, NOW)
    await f.new_mail()
    f.commit()  # mail read OK at 09:00
    mcp.write_config({"mymail": {"command": str(tmp_path / "missing")}})
    f2 = fetch.Fetcher(store, NOW + timedelta(minutes=30))
    await f2.new_mail()
    f2.commit()  # failed at 09:30
    mcp.write_config({"mymail": good})
    f3 = fetch.Fetcher(store, NOW + timedelta(minutes=60))
    await f3.new_mail()
    calls = [json.loads(line) for line in (tmp_path / "calls.log").read_text().splitlines() if '"search_emails"' in line]
    assert calls[-1]["args"]["query"] == f"after:{int(NOW.timestamp())}"  # since the last good read, not the failed check


async def test_background_turns_cut_big_app_results(isolated_settings, tmp_path, monkeypatch):
    from odie.agent import callbacks
    from odie.plugins import mcp
    s = Store(tmp_path / "a.db")
    s.init_schema()
    monkeypatch.setitem(mcp.TOOL_APP, "execute_zapier_read_action", "Zapier")
    after = callbacks.background_after_tool(callbacks.OdiePlugin(s))
    big = {"content": [{"type": "text", "text": "x" * 500_000}]}
    out = await after(SimpleNamespace(name="execute_zapier_read_action"), {}, SimpleNamespace(), big)
    assert out is not None and len(out["content"][0]["text"]) < callbacks.APP_RESULT_LIMIT + 400
