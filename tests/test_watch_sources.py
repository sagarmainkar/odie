"""Which app reads mail and calendar: Zapier through its inspect tool (the search action, never the write one that
shares its key), Composio by its tool names, any other MCP server by tool names and parameters."""
from datetime import datetime, timedelta, UTC

from odie.store.db import Store
from odie.watch import sources
from tests.test_watch_calls import spec_for


async def test_zapier_detection_picks_the_search_action(tmp_path):
    found = await sources.detect({"zapier": spec_for("zapier", tmp_path)})
    mail = next(s for s in found if s.kind == "mail")
    assert mail.style == "zapier" and mail.tool == "execute_zapier_read_action"
    assert mail.fixed == {"selected_api": "GoogleMailV2CLIAPI", "action": "message", "tool_name": "gmail_find_email"}
    assert mail.query_param == "query" and mail.attachment["fixed"]["tool_name"] == "gmail_get_attachment_by_filename"
    cal = next(s for s in found if s.kind == "calendar")
    assert cal.fixed["tool_name"] == "google_calendar_find_events" and (cal.start_param, cal.end_param) == ("end_time", "start_time")
    assert cal.fixed["params"] == {"calendarid": "me@example.com"}  # its primary calendar, from Find Calendars


async def test_plain_servers_by_name_and_parameters(tmp_path):
    found = {s.kind: s for s in await sources.detect({"mymail": spec_for("plain", tmp_path)})}
    assert found["mail"].tool == "search_emails" and found["mail"].query_param == "query" and found["mail"].style == "plain"
    assert found["calendar"].tool == "list_events" and (found["calendar"].start_param, found["calendar"].end_param) == ("time_min", "time_max")
    assert found["mail"].attachment["tool"] == "get_attachment"
    assert all(s.tool != "send_email" for s in found.values())  # write tools are never chosen


async def test_composio_by_its_tool_names(tmp_path):
    found = {s.kind: s for s in await sources.detect({"composio": spec_for("composio", tmp_path)})}
    assert found["mail"].tool == "GMAIL_FETCH_EMAILS" and found["mail"].style == "composio"
    assert found["calendar"].tool == "GOOGLECALENDAR_EVENTS_LIST" and found["calendar"].start_param == "timeMin"


async def test_a_server_that_fails_is_skipped(tmp_path):
    found = await sources.detect({"broken": {"command": str(tmp_path / "missing")}, "mymail": spec_for("plain", tmp_path)})
    assert {s.server for s in found} == {"mymail"}


async def test_saved_and_stale(isolated_settings, tmp_path, monkeypatch):
    s = Store(tmp_path / "a.db")
    s.init_schema()
    from odie.plugins import mcp
    mcp.write_config({"mymail": spec_for("plain", tmp_path)})
    now = datetime.now(UTC)
    assert sources.stale(s, now)
    got = await sources.detect_and_save(s)
    assert {x.kind for x in got} == {"mail", "calendar"} and [x.id for x in sources.saved(s)] == [x.id for x in got]
    assert not sources.stale(s, now)
    assert sources.stale(s, now + timedelta(hours=25))
    mcp.write_config({})  # apps changed
    assert sources.stale(s, now)


# A line-style Gmail and Calendar server's tools, as its list_tools gives them (trimmed to the ones that matter).
GMAIL_MCP_TOOLS = [
    {"name": "gmail_search", "input_schema": {"type": "object", "properties": {"query": {"type": "string", "description": "Gmail search query"},
     "max_results": {"description": "Default 10", "type": "integer", "minimum": 1, "maximum": 50},
     "page_token": {"description": "next_page_token from a previous search", "type": "string"}}, "required": ["query"]}},
    {"name": "calendar_list_events", "input_schema": {"type": "object", "properties": {"date_from": {"type": "string", "description": "YYYY-MM-DD"},
     "date_to": {"description": "YYYY-MM-DD, default = date_from", "type": "string"}}, "required": ["date_from"]}},
    {"name": "calendar_create_event", "input_schema": {"type": "object", "properties": {"summary": {"type": "string"}}}},
]


def test_gmail_mcp_calendar_takes_days():
    found = {s.kind: s for s in sources._by_names("gmail-calendar", {}, GMAIL_MCP_TOOLS, "plain", "Gmail and Calendar")}
    cal = found["calendar"]
    assert (cal.tool, cal.start_param, cal.end_param, cal.dates) == ("calendar_list_events", "date_from", "date_to", True)
    assert found["mail"].tool == "gmail_search" and found["mail"].query_param == "query"


def test_which_parameters_take_a_day():
    assert sources._takes_a_date("date_from", {"type": "string"})
    assert sources._takes_a_date("from", {"type": "string", "format": "date"})
    assert sources._takes_a_date("start", {"type": "string", "description": "YYYY-MM-DD"})
    assert not sources._takes_a_date("time_min", {"type": "string", "description": "RFC3339"})
    assert not sources._takes_a_date("start", {"type": "string", "description": "YYYY-MM-DDTHH:MM:SS"})
    assert not sources._takes_a_date("start_date", {"type": "string", "format": "date-time"})


async def test_sources_saved_before_dates_were_known_are_found_again(isolated_settings, tmp_path):
    s = Store(tmp_path / "a.db")
    s.init_schema()
    from odie.plugins import mcp
    mcp.write_config({"mymail": spec_for("plain", tmp_path)})
    await sources.detect_and_save(s)
    old = s.get_setting(sources.KEY)
    del old["v"]  # what 2026-10-08's Odie saved
    s.set_setting(sources.KEY, old)
    assert sources.stale(s, datetime.now(UTC))
